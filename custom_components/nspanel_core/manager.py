"""NSPanel Core manager — the integration's core.

Ports the external behavior of the C++ MQTT bridge onto HA's event bus:
- Panel registration (JSON register -> register_accept -> HTTP config)
- Light state machines driven by HA state events
- HA service calls for light commands (same semantics incl. optimistic mode)
- Plain-text light/entity state publication on firmware topics
- Command routing for panel JSON commands (method/set, scenes)
- Time/date/weather publishing to the legacy topics the firmware reads
- STOMP mirroring so the original web UI gets live updates
"""

from __future__ import annotations

import base64
import json
import logging
import os
import pathlib
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
import aiohttp
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    TOPIC_PANEL_STATUS,
    TOPIC_PANEL_STATUS_REPORT,
    TOPIC_MANAGER_COMMAND,
    panel_topic,
    panel_mqtt_topic,
    topic_safe,
    status_topic,
)
from .models import IntegrationConfig, LightConfig, PanelConfig, SceneConfig, ThermostatConfig, RelayGroupConfig, RoomConfig

_LOGGER = logging.getLogger(__name__)

_MANIFEST_PATH = pathlib.Path(__file__).parent / "manifest.json"
_MANAGER_VERSION = "v0.0.0"


def _read_manifest_version() -> str:
    """Read the integration version from manifest.json (executor only)."""
    try:
        return "v" + json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["version"]
    except Exception:  # noqa: BLE001
        return "v0.0.0"


def mac_from_topic(topic: str, suffix: str) -> str:
    parts = topic.split("/")
    if len(parts) >= 3 and parts[2] == suffix:
        return topic_safe(parts[1])
    return ""


class NSPanelCoreManager:
    """Central coordinator."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = IntegrationConfig()
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._unsub = []
        self._new_panel_listeners: list = []
        self._report_listeners: list = []
        self._relay_listeners: dict = {}
        self._relay_state: dict = {}
        self._mqtt_unsubs: list = []
        self._last_telemetry: dict[str, dict] = {}
        self._log_backlog: dict[str, list] = {}
        self._last_ota_trigger: dict[str, float] = {}
        self._save_timer = None
        self._weather_unsubs: list = []
        self._ota_md5: dict[str, str] | None = None
        self._ota_overlay: dict[str, str] = {}
        self._ota_active_version: str = ""
        self._firmware_unsubs: list = []
        self._firmware_notified_version: str = ""
        self._firmware_status: dict = {"checking": False, "error": ""}
        self.stomp = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        data = await self._store.async_load()
        self.config = IntegrationConfig.from_dict(data or {})

        # Read manifest.json in the executor: it is blocking I/O and this
        # runs on the event loop.
        global _MANAGER_VERSION
        _MANAGER_VERSION = await self.hass.async_add_executor_job(_read_manifest_version)

        # Original manager UI: STOMP server (live updates) + converted pages.
        from .stomp_server import StompServer
        from . import dashboard
        from .dashboard import async_register_ui

        dashboard._DASHBOARD_VERSION = _MANAGER_VERSION

        self.stomp = StompServer(self.hass)
        async_register_ui(self.hass, self.entry.entry_id)

        # Panel-facing topics. The firmware speaks JSON on hostname-based
        # topics (wifi_hostname, NOT the MAC): status reports, relay states,
        # logs and light/scene commands. There is no protobuf on the wire.
        for sub in (
            (TOPIC_PANEL_STATUS, self._on_panel_status, None),
            (TOPIC_PANEL_STATUS_REPORT, self._on_panel_status_report, None),
            (TOPIC_MANAGER_COMMAND, self._on_manager_command, None),
            ("nspanel/+/r1_state", self._on_relay_state, None),
            ("nspanel/+/r2_state", self._on_relay_state, None),
            ("nspanel/+/log", self._on_panel_log, None),
        ):
            topic, handler, enc = sub
            kwargs = {} if enc is None else {"encoding": enc}
            self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, topic, handler, **kwargs))

        # Bridge UI actions (STOMP SEND from the browser, e.g. reboot and OTA
        # buttons) to MQTT. The UI cannot publish MQTT itself.
        if self.stomp is not None:
            self.stomp.attach_global_callback(self._on_stomp_send)

        # Track HA state for every mapped light entity.
        entity_ids = [l.ha_entity for l in self.config.lights if l.ha_entity]
        if entity_ids:
            self._unsub.append(
                async_track_state_change_event(self.hass, entity_ids, self._on_light_state_event)
            )
        # Track HA state for every mapped thermostat entity.
        therm_ids = [t.ha_entity for t in self.config.thermostats if t.ha_entity]
        if therm_ids:
            self._unsub.append(
                async_track_state_change_event(self.hass, therm_ids, self._on_thermostat_state_event)
            )

        # Minute-aligned time publishing.
        self._unsub.append(
            async_track_time_interval(self.hass, self._publish_time, timedelta(seconds=60))
        )
        await self._publish_time(None)
        await self._publish_manager_status()
        # Republish all state for already-accepted panels.
        await self._republish_all_state()
        # Weather polling (open-meteo) — mirrors the C++/Go weather package.
        self._reschedule_weather()
        self.hass.async_create_task(self._poll_weather(None))
        # Hash AFTER restoring the overlay: _hash_ota_files hashes bundled
        # paths only, so hashing first would leave the checksum cache saying
        # bundled while /download_* serves overlay bytes — permanent OTA
        # re-trigger loop after every restart with an active overlay.
        # NOTE: refresh_ota_cache is a COROUTINE — it must be awaited on the
        # loop, never passed to the executor (that schedules the coroutine
        # object itself and _ota_md5 becomes unusable → every later upload
        # 500s with "'coroutine' object does not support item assignment").
        self._restore_firmware_overlay()
        await self.refresh_ota_cache()
        self._reschedule_firmware_check()
        _LOGGER.info("NSPanel Core manager started")

    async def async_stop(self) -> None:
        for unsub in self._mqtt_unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._mqtt_unsubs = []
        for unsub in self._firmware_unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._firmware_unsubs = []
        for unsub in self._unsub:
            unsub()
        self._unsub = []
        for unsub in self._weather_unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._weather_unsubs = []
        if self._save_timer is not None:
            try:
                self._save_timer()
            except Exception:  # noqa: BLE001
                pass
            self._save_timer = None

    @staticmethod
    def validate_settings(user_input: dict, current: dict | None = None) -> tuple[dict, dict[str, str]]:
        """Validate + coerce settings input. Returns (clean, errors).

        Unknown keys are ignored (legacy form fields); known keys are
        coerced to their GlobalSettings types and range-checked. Nothing is
        written — call apply_settings() with the clean dict afterwards.
        """
        from .const import topic_safe

        current = current or {}
        user_input = dict(user_input)
        # The settings form posts the "or" spelling; the model uses "our".
        if "turn_on_behavior" in user_input and "turn_on_behaviour" not in user_input:
            user_input["turn_on_behaviour"] = user_input.pop("turn_on_behavior")
        clean: dict = {}
        errors: dict[str, str] = {}

        def _bool(v) -> bool | None:
            if isinstance(v, bool):
                return v
            s = str(v).strip().lower()
            if s in ("true", "1", "yes", "on", "optimistic"):
                return True
            if s in ("false", "0", "no", "off", "wait", ""):
                return False
            return None

        def _int(key, v, lo=None, hi=None):
            try:
                n = int(str(v).strip())
            except (ValueError, TypeError):
                errors[key] = "must be a number"
                return None
            if lo is not None and n < lo:
                errors[key] = f"must be >= {lo}"
                return None
            if hi is not None and n > hi:
                errors[key] = f"must be <= {hi}"
                return None
            return n

        for key, value in user_input.items():
            if key == "manager_address":
                v = str(value or "").strip()
                if not v or not topic_safe(v):
                    errors[key] = "address must not be empty"
                else:
                    clean[key] = v
            elif key == "manager_port":
                n = _int(key, value, 1, 65535)
                if n is not None:
                    clean[key] = n
            elif key in ("color_temp_min", "color_temp_max"):
                n = _int(key, value, 1000, 10000)
                if n is not None:
                    clean[key] = n
            elif key == "date_format":
                v = str(value or "").strip() or "%d/%m"
                clean[key] = v
            elif key in ("location_latitude", "location_longitude"):
                v = str(value or "").strip()
                if v == "":
                    clean[key] = ""
                else:
                    try:
                        f = float(v)
                    except (ValueError, TypeError):
                        errors[key] = "must be a number"
                        continue
                    lo, hi = (-90, 90) if key == "location_latitude" else (-180, 180)
                    if not (lo <= f <= hi):
                        errors[key] = f"must be between {lo} and {hi}"
                    else:
                        clean[key] = v
            elif key == "weather_update_interval":
                n = _int(key, value, 5, 120)
                if n is not None:
                    clean[key] = n
            elif key == "precipitation_format":
                if str(value) in ("mm", "inch"):
                    clean[key] = str(value)
                else:
                    errors[key] = "must be mm or inch"
            elif key == "wind_speed_format":
                wv = str(value).strip().lower()
                if wv == "knots":
                    wv = "kn"  # template posts "knots"; canonical value is "kn"
                if wv in ("kmh", "ms", "mph", "kn"):
                    clean[key] = wv
                else:
                    errors[key] = "must be kmh, ms, mph or kn"
            elif key in ("use_fahrenheit", "reverse_color_temp", "optimistic_mode",
                         "clock_us_style", "auto_tft_updates"):
                b = _bool(value)
                if b is None:
                    errors[key] = "must be true or false"
                else:
                    clean[key] = b
            elif key == "turn_on_behaviour":
                if str(value) in ("color_temp", "restore"):
                    clean[key] = str(value)
                else:
                    errors[key] = "must be color_temp or restore"
            elif key in ("light_turn_on_brightness", "raise_to_100_light_level"):
                n = _int(key, value, 0, 100)
                if n is not None:
                    clean[key] = n
            elif key == "theme":
                if str(value) in ("nspmwip",):
                    clean[key] = str(value)
                else:
                    errors[key] = "unknown theme"
            elif key in ("outside_temp_sensor_entity", "outside_temp_provider"):
                clean[key] = str(value or "").strip()
            elif key == "screensaver_mode":
                if str(value) in ("with_background", "without_background",
                                  "datetime_with_background", "datetime_without_background",
                                  "no_screensaver"):
                    clean[key] = str(value)
                else:
                    errors[key] = "must be a known screensaver mode"
            # else: legacy/unknown form field — ignored deliberately
        cmin = clean.get("color_temp_min", current.get("color_temp_min", 2700))
        cmax = clean.get("color_temp_max", current.get("color_temp_max", 6500))
        if cmin >= cmax:
            errors["color_temp_max"] = "max must be greater than min"
            clean.pop("color_temp_min", None)
            clean.pop("color_temp_max", None)
        return clean, errors

    async def apply_settings(self, user_input: dict) -> dict[str, str]:
        """Validate, persist and apply settings. Returns validation errors."""
        clean, errors = self.validate_settings(user_input, self.config.settings.to_dict())
        if errors:
            return errors
        s = self.config.settings
        old_interval = s.weather_update_interval
        for key, value in clean.items():
            setattr(s, key, value)
        await self.async_save()
        await self._publish_manager_status()
        if clean.get("weather_update_interval", old_interval) != old_interval:
            self._reschedule_weather()
        return {}

    _FIRMWARE_CHECK_HOURS = 6

    def _reschedule_firmware_check(self) -> None:
        for unsub in list(self._firmware_unsubs):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._firmware_unsubs = []
        # Fixed 6-hour cadence — the only source and schedule, no UI for it.
        self._firmware_unsubs.append(
            async_track_time_interval(
                self.hass, self._poll_firmware_manifest, timedelta(hours=self._FIRMWARE_CHECK_HOURS)
            )
        )

    async def _poll_firmware_manifest(self, _now) -> None:
        status = await self.check_firmware_updates(auto=True)
        latest = status.get("latest") if isinstance(status, dict) else ""
        if (
            status.get("update_available")
            and latest
            and latest != self._firmware_notified_version
        ):
            self._firmware_notified_version = latest
            self.add_message(
                "Panel firmware update available",
                f"Version {latest} is ready ({status.get('notes', '') or 'see manifest notes'})."
                " Install it from the Actions menu (Download + activate latest).",
            )

    def servable_path(self, kind: str, name: str) -> str | None:
        """Resolve an OTA file to disk: active overlay first, bundled fallback."""
        key = f"{kind}/{name}"
        overlay = self._ota_overlay.get(key)
        if overlay and os.path.isfile(overlay):
            return overlay
        base = os.path.join(os.path.dirname(__file__), kind)
        path = os.path.join(base, name)
        return path if os.path.isfile(path) else None

    def set_firmware_overlay(self, version: str, paths: dict[str, str], md5s: dict | None = None) -> None:
        self._ota_overlay = dict(paths)
        self._ota_active_version = version
        try:
            self.config.settings.firmware_active_md5s = dict(md5s or {})
        except Exception:  # noqa: BLE001
            pass
        try:
            self.config.settings.firmware_active_version = version
        except Exception:  # noqa: BLE001
            pass
        self.hass.async_create_task(self.async_save())

    def note_custom_file(self, kind: str, name: str, label: str) -> dict:
        """Pin a manually uploaded file so it is served EXACTLY.

        Copies the uploaded bytes over any overlay copy (overlays silently
        shadow bundled files — the panel would otherwise keep downloading/
        flashing the OLD release bytes while the checksum cache claimed the
        new hash, causing endless reflash loops), re-hashes the served path,
        and records name/md5/size/time in settings.
        Returns the served-file proof dict.
        """
        import hashlib as _hashlib
        import os as _os
        import shutil as _shutil
        from datetime import datetime, timezone

        bundled = _os.path.join(_os.path.dirname(__file__), kind, name)
        # Overlay would shadow the upload — overwrite it with the exact bytes.
        overlay = self._ota_overlay.get(f"{kind}/{name}", "")
        if overlay and _os.path.abspath(overlay) != _os.path.abspath(bundled):
            try:
                _os.makedirs(_os.path.dirname(overlay), exist_ok=True)
                _shutil.copyfile(bundled, overlay)
            except OSError:
                _LOGGER.warning("Could not mirror custom TFT into overlay", exc_info=True)
        served = self.servable_path(kind, name) or bundled
        h = _hashlib.md5()
        size = 0
        try:
            with open(served, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
                    size += len(chunk)
            digest = h.hexdigest()
        except OSError:
            digest = ""
        try:
            self._ota_md5[f"{kind}/{name}"] = digest
        except (AttributeError, TypeError):
            self._ota_md5 = {f"{kind}/{name}": digest}
        s = self.config.settings
        s.custom_tft_name = name if kind == "tft" else s.custom_tft_name
        s.custom_tft_md5 = digest
        s.custom_tft_size = size
        s.custom_tft_uploaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        s.custom_tft_source = label
        return {
            "filename": name,
            "bytes": size,
            "md5": digest,
            "source": label,
            "uploaded_at": s.custom_tft_uploaded_at,
        }

    def note_custom_tft(self, filename: str) -> dict:
        """TFT-specific pin (kept for callers/tests)."""
        return self.note_custom_file("tft", filename, "manual upload")

    def served_tft_info(self) -> dict:
        """Proof of what the panels actually download, per variant."""
        import hashlib as _hashlib
        import os as _os

        out = {}
        for filename in ("gui.tft", "gui_us.tft"):
            path = self.servable_path("tft", filename)
            overlay_path = self._ota_overlay.get(f"tft/{filename}", "")
            info = {"filename": filename, "bytes": 0, "md5": "", "source": "missing"}
            if path and _os.path.isfile(path):
                h = _hashlib.md5()
                size = 0
                try:
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h.update(chunk)
                            size += len(chunk)
                    info["bytes"] = size
                    info["md5"] = h.hexdigest()
                except OSError:
                    pass
                if info["md5"]:
                    s = self.config.settings
                    if (
                        s.custom_tft_name == filename
                        and s.custom_tft_md5
                        and s.custom_tft_md5 == info["md5"]
                    ):
                        info["source"] = (
                            f"manual upload ({s.custom_tft_uploaded_at})"
                            + (" — pinned over overlay" if overlay_path and _os.path.isfile(overlay_path) else "")
                        )
                    elif overlay_path and _os.path.abspath(path) == _os.path.abspath(overlay_path):
                        info["source"] = f"GitHub release (firmware {self._ota_active_version or 'bundled'})"
                    else:
                        info["source"] = "bundled with integration"
            out["eu" if filename == "gui.tft" else "us"] = info
        return out

    async def refresh_ota_cache(self) -> None:
        """Re-hash served OTA files (bundled + overlay) in the executor."""
        def _rehash() -> dict[str, str]:
            import hashlib

            out: dict[str, str] = {}
            for key in (
                "firmware/sonoff/firmware.bin",
                "firmware/sonoff/data_file.bin",
                "firmware/custom/firmware.bin",
                "firmware/custom/data_file.bin",
                "tft/gui.tft",
                "tft/gui_us.tft",
            ):
                kind, name = key.split("/", 1)
                path = self.servable_path(kind, name)
                if not path:
                    out[key] = ""
                    continue
                h = hashlib.md5()
                try:
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h.update(chunk)
                    out[key] = h.hexdigest()
                except OSError:
                    out[key] = ""
            return out

        self._ota_md5 = await self.hass.async_add_executor_job(_rehash)

    def _restore_firmware_overlay(self) -> None:
        """Re-activate a previously downloaded firmware set (no I/O on loop)."""
        from . import firmware_store as _fs

        version = (self.config.settings.firmware_active_version or "").strip()
        if not version:
            return
        target = _fs.overlay_dir(self.hass.config.path(), version)
        paths = {
            key: os.path.join(target, key.replace("/", "__")) for key in _fs.SERVABLE_FILES
        }
        recorded = dict(getattr(self.config.settings, "firmware_active_md5s", {}) or {})
        if _fs.validate_manifest_against(paths, {"files": {k: {"md5": v} for k, v in recorded.items()}}):
            self._ota_overlay = paths
            self._ota_active_version = version
            _LOGGER.info("Restored firmware overlay %s (md5-verified)", version)
        else:
            _LOGGER.warning(
                "Firmware overlay %s failed hash verification at boot; ignoring (bundled files served)",
                version,
            )

    async def check_firmware_updates(self, auto: bool = False) -> dict:
        """Fetch the manifest, compare with the served version. No download."""
        from . import firmware_store as _fs
        from datetime import datetime, timezone

        if self._firmware_status.get("checking"):
            return dict(self._firmware_status)
        self._firmware_status = {"checking": True, "error": ""}
        try:
            manifest = await _fs.fetch_manifest(self.hass, _fs.DEFAULT_MANIFEST_URL)
            from datetime import datetime, timezone

            self.config.settings.firmware_last_check = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            if not manifest:
                self._firmware_status = {"checking": False, "error": "fetch failed"}
                return dict(self._firmware_status)
            latest = str(manifest.get("version", ""))
            self.config.settings.firmware_latest_version = latest
            current = self._ota_active_version or await self.hass.async_add_executor_job(
                _fs.bundled_version, os.path.dirname(__file__)
            )
            update_available = _fs.is_newer(latest, current) if latest else False
            self._firmware_status = {
                "checking": False,
                "error": "",
                "latest": latest,
                "current": current,
                "update_available": update_available,
                "notes": manifest.get("notes", ""),
            }
            await self.async_save()
        finally:
            if self._firmware_status.get("checking"):
                self._firmware_status = {"checking": False, "error": "aborted"}
        return dict(self._firmware_status)

    async def activate_firmware_version(self) -> tuple[bool, str]:
        """Download + activate the latest manifest firmware, then push OTA.

        Same OTA path as the per-panel update buttons: every accepted panel
        is evaluated against the newly served checksums immediately instead
        of waiting for its next register.
        """
        from . import firmware_store as _fs

        manifest = await _fs.fetch_manifest(self.hass, _fs.DEFAULT_MANIFEST_URL)
        if not manifest:
            return False, "manifest fetch failed"
        ok, message = await _fs.download_and_activate(self.hass, self, manifest)
        if not ok:
            return ok, message
        pushed = 0
        for panel in self.config.panels:
            if not panel.accepted or panel.denied:
                continue
            self._last_ota_trigger.pop(panel.mac, None)
            await self._maybe_trigger_firmware_ota(
                panel,
                {
                    "md5_firmware": panel.firmware_md5,
                    "md5_littlefs": panel.littlefs_md5,
                    "md5_tft_file": panel.tft_md5,
                },
            )
            pushed += 1
        return True, f"{message}; OTA pushed to {pushed} panel(s)"

    def _reschedule_weather(self) -> None:
        for unsub in list(self._weather_unsubs):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._weather_unsubs = []
        self._weather_unsubs.append(
            async_track_time_interval(
                self.hass, self._poll_weather,
                timedelta(minutes=self.config.settings.weather_update_interval or 30),
            )
        )

    async def async_save(self) -> None:
        await self._store.async_save(self.config.to_dict())

    def add_message(self, title: str, message: str) -> None:
        """Add an inbox notification (shown by the navbar inbox)."""
        from .models import MessageConfig

        self.config.messages.append(MessageConfig(
            id=self.config.next_id_for("message"),
            title=str(title)[:120],
            message=str(message)[:500],
            read=False,
        ))
        del self.config.messages[:-50]
        self._schedule_save()

    def get_messages(self) -> list[dict]:
        return [asdict(m) for m in self.config.messages]

    def mark_messages_read(self) -> None:
        if any(not m.read for m in self.config.messages):
            for m in self.config.messages:
                m.read = True
            self._schedule_save()

    def _schedule_save(self) -> None:
        """Coalesced storage write for high-frequency state paths.

        State events can arrive many times per second; writing the full JSON
        store on each one burns disk and risks corruption. Coalesce to one
        write ~5s after the last change.
        """
        if self._save_timer is not None:
            try:
                self._save_timer()
            except Exception:  # noqa: BLE001
                pass
        self._save_timer = async_call_later(self.hass, 5, self._delayed_save)

    async def _delayed_save(self, _now) -> None:
        self._save_timer = None
        try:
            await self.async_save()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Delayed storage save failed")

    # ------------------------------------------------------------------
    # MQTT helpers
    # ------------------------------------------------------------------

    async def _publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        await mqtt.async_publish(self.hass, topic, payload, 0, retain)
        if self.stomp is not None:
            self.stomp.mirror_mqtt(topic, payload, retain)

    async def _publish_manager_status(self) -> None:
        await self._publish(
            status_topic(self.config.settings.manager_address),
            json.dumps({"state": "online", "version": _MANAGER_VERSION}),
            True,
        )

    async def _publish_panel_status(
        self, panel: PanelConfig, state: str, progress: int = 0, warnings: list | None = None,
        telemetry: dict | None = None,
    ) -> None:
        if self.stomp is None:
            return
        # Remember the last live values: state-only publishes (online/offline
        # flaps) must not wipe them or the UI blanks until the next report.
        if telemetry:
            last = self._last_telemetry.setdefault(panel.mac, {})
            for key in ("rssi", "temperature", "ram_usage", "ip"):
                value = telemetry.get(key)
                if value is not None:
                    last[key] = value
        payload: dict = {"state": state, "update_progress": progress, "warnings": warnings or []}
        payload.update(self._last_telemetry.get(panel.mac, {}))
        self.stomp.set_retained(panel_topic(panel.mac, "status"), True)
        self.stomp.update_topic(
            panel_topic(panel.mac, "status"),
            json.dumps(payload),
        )

    # ------------------------------------------------------------------
    # Panel registration (JSON flow, same as the add-on)
    # ------------------------------------------------------------------

    async def _on_panel_status(self, msg) -> None:
        """Availability topic: nspanel/<wifi_hostname>/status (retained JSON).

        The panel's MQTT last-will publishes {"state": "offline"} here and
        {"state": "online"} on connect. The topic segment is the panel's
        wifi hostname, not its MAC.
        """
        from .const import topic_safe

        segment = mac_from_topic(msg.topic, "status")
        if not segment:
            return
        panel = self._panel_by_topic(segment)
        if panel is None:
            # Try the verbatim segment before giving up: mac_from_topic
            # normalizes, but hostnames keep case/spaces on the wire.
            panel = self._panel_by_topic(self._topic_segment(msg.topic))
        if panel is None:
            return
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.debug("Ignoring non-JSON status from %s", segment)
            return
        if not isinstance(data, dict):
            return

        state = data.get("state", "")
        if state == "register_request":
            # Legacy register path (original bridge); current firmware uses
            # nspanel/mqttmanager/command instead. Handled for completeness —
            # works for unknown panels (this is how they first appear).
            await self._handle_register_request(data.get("mac_origin") or "", data)
            return
        self._note_panel_hostname(panel, self._topic_segment(msg.topic))
        if state == "online":
            if not panel.online:
                panel.online = True
                await self.async_save()
                await self._publish_panel_status(panel, "online")
        elif state == "offline":
            if panel.online:
                panel.online = False
                await self.async_save()
                await self._publish_panel_status(panel, "offline")

    async def _handle_register_request(self, mac: str, data: dict) -> None:
        mac = topic_safe(mac)
        if not mac:
            _LOGGER.warning("Ignoring register request with empty MAC")
            return
        panel = self._panel_by_mac(mac)
        created = panel is None
        if created:
            friendly = data.get("friendly_name", f"NSPanel {mac[-4:].upper()}")
            if not self.config.rooms:
                # Rooms tab was removed from the UI — a panel must belong
                # somewhere, so keep a single automatic default room.
                self.config.rooms.append(
                    RoomConfig(id=self.config.next_id_for("room"), name="Default room")
                )
                await self.async_save()
                _LOGGER.info("Auto-created default room for panel registration")
            panel = PanelConfig(
                id=self.config.next_id_for("panel"),
                mac=mac,
                name=friendly,
                wifi_hostname=friendly,
                model=data.get("model", "sonoff"),
                room_id=self.config.rooms[0].id,
                version=data.get("version", "UNKNOWN"),
            )
            self.config.panels.append(panel)
            await self.async_save()
            _LOGGER.info("New panel registered as awaiting accept: %s (%s)", friendly, mac)
            self.add_message(
                "Panel requesting access",
                f"NSPanel '{friendly}' ({mac}) wants to join. Accept or deny it on the NSPanels page.",
            )

        await self._publish_panel_status(panel, "awaiting_accept")

        # Store registration metadata (same fields the C++ bridge kept).
        # The manager is the authority on the panel name for accepted panels:
        # after a config wipe the firmware reports the compiled default
        # ("NSPanelCore") as friendly_name — adopting it would clobber the
        # user's curated name and move all command topics. Only adopt the
        # device name for panels that haven't been accepted yet.
        if not panel.accepted:
            panel.name = data.get("friendly_name") or panel.name
        elif data.get("friendly_name") and data.get("friendly_name") != panel.name:
            _LOGGER.warning(
                "Panel %s reports hostname %r — keeping manager name (fix it on the panel or rename here)",
                panel.name,
                data.get("friendly_name"),
            )
        # The wire hostname is tracked separately from the display name so a
        # manager-side rename never moves the command topics (split-brain fix).
        # Not adopted when the firmware reports the compiled default after a
        # config wipe — that would point commands at a hostname the panel
        # abandons on its next register.
        _friendly = str(data.get("friendly_name") or "")
        if _friendly and _friendly != "NSPanelCore":
            panel.wifi_hostname = _friendly
        if data.get("model"):
            panel.model = data["model"]
        if data.get("version"):
            panel.version = data["version"]
        if data.get("md5_firmware"):
            panel.firmware_md5 = data["md5_firmware"]
        if data.get("md5_tft_file"):
            panel.tft_md5 = data["md5_tft_file"]
        if data.get("md5_data_file"):
            panel.littlefs_md5 = data["md5_data_file"]

        reply = self._register_accept_reply(panel)
        if panel.accepted and not panel.denied:
            # Accepted panels get the accept reply + a config reload nudge on
            # their own hostname-based command topic (the only topic the
            # panel subscribes to).
            await self._publish(
                self._panel_cmd_topic(panel, "command"), reply, True
            )
            await self._publish(
                self._panel_cmd_topic(panel, "command"),
                json.dumps({"command": "reload"}),
            )
            await self._publish_panel_status(panel, "online")

        # Registration carries the panel's current checksums — evaluate OTA
        # here, but ONLY for accepted panels. Flashing an unaccepted (merely
        # seen) panel would replace its firmware without any consent.
        # Cooldown-guarded: a panel mid-download re-registers on reconnect and
        # must not be re-triggered into an update loop.
        if panel.accepted and not panel.denied:
            await self._maybe_trigger_firmware_ota_cooled(panel, self._normalize_ota_report(data))

        if created and not panel.accepted:
            # New registration: notify the UI (original event chain)
            if self.stomp is not None:
                self.stomp.update_topic(
                    "mqttmanager/events",
                    json.dumps({"event_type": "register_request", "nspanel_id": panel.id}),
                )
        await self.async_save()

    async def _send_panel_config(self, panel: PanelConfig) -> None:
        """Deliver config to an accepted panel.

        Panels fetch their full config over HTTP
        (GET /api/get_nspanel_config); the manager only sends the
        register_accept reply plus a reload nudge on the panel's own
        hostname-based command topic — the only topic it subscribes to.
        There is no protobuf on the wire.
        """
        await self._publish(
            self._panel_cmd_topic(panel, "command"),
            json.dumps(self._register_accept_reply(panel)),
            True,
        )
        await self._publish(
            self._panel_cmd_topic(panel, "command"),
            json.dumps({"command": "reload"}),
        )
        # The stored checksums (from registration) decide OTA here: accept is
        # the consent gate, so a newly accepted panel updates on the spot
        # instead of waiting for its next register. Cooldown-guarded (see
        # register path) to avoid update loops on accept retries.
        await self._maybe_trigger_firmware_ota_cooled(panel, {
            "md5_firmware": panel.firmware_md5,
            "md5_littlefs": panel.littlefs_md5,
            "md5_tft_file": panel.tft_md5,
        })
        _LOGGER.info("Sent register accept + reload to panel %s", panel.name)
        await self._publish_panel_status(panel, "online")

    async def _on_panel_status_report(self, msg) -> None:
        """Status report: nspanel/<panel>/status_report (retained).

        Two wire formats, both accepted:
        - JSON (current firmware): state/progress/rssi/heap_used_pct/mac/
          temperature (string)/ip/warnings (string).
        - Protobuf (legacy firmware <=0.3.x, MAC topics): parsed with the
          panel_pb codec; carries rssi/temperature/mac/ip plus the md5
          checksums used for OTA decisions.
        ``state`` is only present while updating (updating_tft/fw/fs);
        otherwise the panel is online.
        """
        segment = mac_from_topic(msg.topic, "status_report")
        if not segment:
            return
        panel = self._panel_by_topic(segment)
        if not panel:
            return
        self._note_panel_hostname(panel, self._topic_segment(msg.topic))
        md5s: dict = {}
        try:
            data = json.loads(msg.payload)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            state = str(data.get("state") or "")
            try:
                temperature = float(str(data.get("temperature", "")))
            except (ValueError, TypeError):
                temperature = None
            try:
                rssi = int(data.get("rssi")) if data.get("rssi") is not None else None
            except (ValueError, TypeError):
                rssi = None
            try:
                heap = int(data.get("heap_used_pct")) if data.get("heap_used_pct") is not None else None
            except (ValueError, TypeError):
                heap = None
            ip = str(data.get("ip") or "").strip() or None
            raw_warnings = data.get("warnings", "")
            warnings: list = []
            if isinstance(raw_warnings, list):
                warnings = raw_warnings
            elif isinstance(raw_warnings, str) and raw_warnings.strip():
                warnings = [
                    {"level": "warning", "text": line}
                    for line in raw_warnings.splitlines()
                    if line.strip()
                ]
            report = {
                "temperature": temperature,
                "rssi": rssi,
                "heap_used_pct": heap,
                "ip": ip,
                "has_humidity": False,
                "has_pressure": False,
                "warnings": warnings,
                "state": state,
                "progress": data.get("progress", 0),
            }
        except (ValueError, TypeError):
            # Legacy protobuf report — parse with the panel_pb codec.
            try:
                from .panel_pb import messages as pbw

                payload = msg.payload
                if isinstance(payload, str):
                    payload = payload.encode("utf-8", "replace")
                preport = pbw.parse_nspanel_status_report(bytes(payload))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Ignoring unparsable status report from %s", segment)
                return
            updaters = {"updating_tft", "updating_fw", "updating_fs"}
            state = preport.get("updater_state", "")
            report = {
                "temperature": preport.get("temperature"),
                "rssi": preport.get("rssi"),
                "has_humidity": bool(preport.get("has_humidity")),
                "has_pressure": bool(preport.get("has_pressure")),
                "warnings": preport.get("warnings", []),
                "state": state if state in updaters else "",
                "progress": preport.get("update_progress", 0),
            }
            md5s = {
                "md5_firmware": preport.get("md5_firmware", ""),
                "md5_littlefs": preport.get("md5_littlefs", ""),
                "md5_tft_file": preport.get("md5_tft_gui", "") or preport.get("md5_tft_file", ""),
            }
        was_online = panel.online
        panel.online = report.get("state", "") not in ("updating_tft", "updating_fw", "updating_fs")
        caps_changed = False
        for cap in ("has_humidity", "has_pressure"):
            if bool(report.get(cap)) and not getattr(panel, cap, False):
                setattr(panel, cap, True)
                caps_changed = True
        self._schedule_save()
        if panel.online != was_online or caps_changed:
            for listener in list(self._new_panel_listeners):
                try:
                    listener()
                except Exception:  # noqa: BLE001 — one bad listener must not break the rest
                    _LOGGER.exception("New-panel listener failed")
        for listener in list(self._report_listeners):
            try:
                listener(panel.mac, report)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Report listener failed")
        if self.stomp is not None and panel.accepted:
            state_map = {
                "": "online",
                "updating_tft": "updating_tft",
                "updating_fw": "updating_fw",
                "updating_fs": "updating_fs",
            }
            try:
                progress = int(report.get("progress", 0))
            except (ValueError, TypeError):
                progress = 0
            await self._publish_panel_status(
                panel, state_map.get(report.get("state", ""), "online"), progress, report.get("warnings", []),
                telemetry={
                    "rssi": report.get("rssi"),
                    "temperature": report.get("temperature"),
                    "ram_usage": report.get("heap_used_pct"),
                    "ip": report.get("ip"),
                },
            )
        # Legacy reports carry checksums: evaluate OTA here too (accepted
        # panels only, cooldown-guarded). JSON reports don't include md5s.
        if md5s and any(md5s.values()):
            await self._maybe_trigger_firmware_ota_cooled(panel, md5s)

    async def _maybe_trigger_firmware_ota_cooled(self, panel: PanelConfig, report: dict) -> None:
        """OTA evaluation with a per-panel cooldown.

        Status reports arrive every ~30s; without this, a panel mid-download
        would be re-triggered on every report and never finish flashing.
        Skips panels already reporting an updating state (their flash is in
        flight — re-triggering mid-flash corrupts it). The cooldown stamp is
        written AFTER evaluation so a startup-window registration (md5 cache
        not ready) is not blacked out for the next 30 minutes.
        """
        import time as _time

        if report.get("state") in ("updating_tft", "updating_fw", "updating_fs"):
            return
        now = _time.monotonic()
        last = self._last_ota_trigger.get(panel.mac, 0)
        if now - last < 1800:
            return
        await self._maybe_trigger_firmware_ota(panel, report)
        self._last_ota_trigger[panel.mac] = _time.monotonic()

    @staticmethod
    def _normalize_ota_report(data: dict) -> dict:
        """Normalize register-payload md5 keys to the OTA evaluator's names.

        Firmware sends md5_data_file / md5_tft_gui variants; the evaluator
        expects md5_littlefs / md5_tft_file. Single place so the data-file
        branch can't silently go dead on one path and live on another.
        """
        if not isinstance(data, dict):
            return {}
        out = dict(data)
        if "md5_data_file" in out and "md5_littlefs" not in out:
            out["md5_littlefs"] = out["md5_data_file"]
        if "md5_tft_gui" in out and "md5_tft_file" not in out:
            out["md5_tft_file"] = out["md5_tft_gui"]
        return out

    def _panel_cmd_topic(self, panel: PanelConfig, suffix: str) -> str:
        """Command topic the panel subscribes to.

        Always hostname-based: the firmware subscribes on
        nspanel/<wifi_hostname>/..., never on the curated display name.
        """
        return panel_mqtt_topic(panel.wifi_hostname or panel.name, suffix)

    @staticmethod
    def _topic_segment(topic: str) -> str:
        """Verbatim nspanel/<segment>/... segment (case/spaces preserved).

        mac_from_topic() normalizes (lowercase/underscores) for lookup, but
        the stored wifi_hostname must match the panel's subscription byte
        for byte, so command topics have to use the verbatim form.
        """
        try:
            parts = str(topic).split("/")
            if len(parts) >= 3 and parts[0] == "nspanel":
                return parts[1]
        except (AttributeError, TypeError):
            pass
        return ""

    def _note_panel_hostname(self, panel: PanelConfig, segment: str) -> None:
        """Remember the topic segment a panel was last seen on.

        Called on every inbound message so a hostname change on the device
        (or a manager-side rename) heals routing instead of black-holing it.
        """
        if segment and segment != panel.wifi_hostname:
            panel.wifi_hostname = segment

    def _panel_by_topic(self, segment: str) -> PanelConfig | None:
        """Find a panel by a topic segment: hostname (wifi_hostname) or MAC.

        The wifi_hostname is checked FIRST: it is the topic the firmware
        actually publishes on. The curated display name is only a fallback
        (it equals the hostname until the user renames the panel).
        Verbatim match first (MQTT topics are case-sensitive); normalized
        match second with a drift warning so a case/charset mismatch that
        would black-hole commands is visible instead of silent.
        """
        if not segment:
            return None
        for panel in self.config.panels:
            if panel.wifi_hostname and panel.wifi_hostname == segment:
                return panel
        for panel in self.config.panels:
            if panel.name == segment or panel.mac == segment:
                return panel
        want = topic_safe(segment)
        for panel in self.config.panels:
            if topic_safe(panel.name) == want or topic_safe(panel.mac) == want:
                _LOGGER.warning(
                    "Topic segment %r matched panel %r only after normalization — "
                    "check hostname case/characters (MQTT is case-sensitive)",
                    segment,
                    panel.name,
                )
                return panel
        return None

    def _panel_by_mac(self, mac: str) -> PanelConfig | None:
        from .const import topic_safe

        want = topic_safe(mac)
        for panel in self.config.panels:
            if topic_safe(panel.mac) == want:
                return panel
        return None

    def _light_by_id(self, light_id: int) -> LightConfig | None:
        for light in self.config.lights:
            if light.id == light_id:
                return light
        return None

    def _room_by_id(self, room_id: int):
        for room in self.config.rooms:
            if room.id == room_id:
                return room
        return None

    # ------------------------------------------------------------------
    # Lookups / listeners
    # ------------------------------------------------------------------

    def panels(self) -> list[PanelConfig]:
        return list(self.config.panels)

    def pages(self) -> list:
        return list(self.config.pages)

    async def _maybe_trigger_firmware_ota(self, panel: PanelConfig, report: dict) -> None:
        """Trigger OTA when the panel's checksums differ from the cached ones.

        Uses the startup-computed MD5 cache — no disk I/O on the event loop.
        Panels only send md5s in the register request, so this is evaluated
        there (status reports carry no checksums).
        """
        if self._ota_md5 is None:
            return
        model = panel.model if panel.model in ("sonoff", "custom") else "sonoff"

        fw_md5 = self.ota_md5("firmware", f"{model}/firmware.bin")
        data_md5 = self.ota_md5("firmware", f"{model}/data_file.bin")

        if fw_md5 and report.get("md5_firmware") and report["md5_firmware"] != fw_md5:
            _LOGGER.info("Firmware update available for panel %s — triggering OTA", panel.name)
            await self._publish(self._panel_cmd_topic(panel, "command"), json.dumps({"command": "firmware_update"}))

        if data_md5 and report.get("md5_littlefs") and report["md5_littlefs"] != data_md5:
            # NOTE: data_file updates are DELIBERATELY never triggered
            # automatically. The data partition holds /littlefs/config.json
            # (WiFi + MQTT credentials); flashing it wipes the panel's network
            # config and drops it into AP mode — unacceptable without an
            # explicit user action, especially for remote panels.
            _LOGGER.info(
                "Data file update available for panel %s — NOT triggering automatically "
                "(would wipe its WiFi config; update it manually if needed)", panel.name
            )

        tft_filename = "gui_us.tft" if panel.is_us_panel else "gui.tft"
        tft_md5 = self.ota_md5("tft", tft_filename)
        if tft_md5 and report.get("md5_tft_file") and report["md5_tft_file"] != tft_md5:
            if not self.config.settings.auto_tft_updates:
                _LOGGER.info(
                    "TFT update available for panel %s — NOT triggering automatically "
                    "(auto display updates disabled; flash it from the panel Actions menu)",
                    panel.name,
                )
            else:
                _LOGGER.info("TFT update available for panel %s — triggering OTA", panel.name)
                await self._publish(self._panel_cmd_topic(panel, "command"), json.dumps({"command": "tft_update"}))

    def relay_state(self, panel: PanelConfig, relay: int) -> bool:
        return self._relay_state.get((topic_safe(panel.mac), int(relay)), False)

    @staticmethod
    def _hash_ota_files() -> dict[str, str]:
        """MD5 of every servable OTA binary (runs in the executor).

        Keyed "firmware/<model>/<file>" and "tft/<file>". Missing files map
        to "" — callers treat "" as 'unknown, never trigger'.
        """
        import hashlib
        import os

        base = os.path.join(os.path.dirname(__file__), "firmware")
        out: dict[str, str] = {}

        def md5_file(path: str) -> str:
            h = hashlib.md5()
            try:
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
            except OSError:
                return ""
            return h.hexdigest()

        for model in ("sonoff", "custom"):
            for filename in ("firmware.bin", "data_file.bin"):
                out[f"firmware/{model}/{filename}"] = md5_file(
                    os.path.join(base, model, filename)
                )
        tft_dir = os.path.join(os.path.dirname(__file__), "tft")
        for filename in ("gui.tft", "gui_us.tft"):
            out[f"tft/{filename}"] = md5_file(os.path.join(tft_dir, filename))
        return out

    def ota_md5(self, kind: str, name: str) -> str:
        """Cached MD5 for an OTA file; "" when unknown (startup race)."""
        if self._ota_md5 is None:
            return ""
        return self._ota_md5.get(f"{kind}/{name}", "")

    def invalidate_ota_cache(self, kind: str, name: str, path: str) -> None:
        """Re-hash one file after an upload (call from the executor)."""
        import hashlib

        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        except OSError:
            digest = ""
        if self._ota_md5 is None:
            self._ota_md5 = {}
        self._ota_md5[f"{kind}/{name}"] = digest

    async def set_relay(self, panel: PanelConfig, relay: int, state: bool) -> None:
        await self._publish(
            self._panel_cmd_topic(panel, f"r{relay}_cmd"), "1" if state else "0"
        )

    async def set_relay_group(self, group_id: int, state: bool) -> None:
        group = next((g for g in self.config.relay_groups if g.id == group_id), None)
        if group is None:
            return
        for binding in group.bindings:
            mac = binding.get("panel_mac", "")
            relay = binding.get("relay_num", 1)
            panel = self._panel_by_mac(mac) if mac else None
            if panel is not None:
                await self.set_relay(panel, relay, state)

    def notify_panels_changed(self) -> None:
        """Re-run new-panel listeners (entity add/remove re-evaluation).

        Called after settings saves / accept / deny: relay is_light flips,
        capability changes etc. only take effect in HA when the entity
        platforms re-evaluate.
        """
        for listener in list(self._new_panel_listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("New-panel listener failed")

    def add_new_panel_listener(self, listener):
        """Register a listener; returns an unsubscribe closure for async_on_unload."""
        self._new_panel_listeners.append(listener)

        def _unsubscribe() -> None:
            try:
                self._new_panel_listeners.remove(listener)
            except ValueError:
                pass

        return _unsubscribe

    def add_report_listener(self, listener):
        """Register a listener; returns an unsubscribe closure for async_on_unload."""
        self._report_listeners.append(listener)

        def _unsubscribe() -> None:
            try:
                self._report_listeners.remove(listener)
            except ValueError:
                pass

        return _unsubscribe

    def add_relay_listener(self, panel: PanelConfig, relay: int, listener):
        key = (topic_safe(panel.mac), int(relay))
        self._relay_listeners.setdefault(key, []).append(listener)

        def _unsubscribe() -> None:
            try:
                self._relay_listeners.get(key, []).remove(listener)
            except ValueError:
                pass

        return _unsubscribe

    # ------------------------------------------------------------------
    # Dashboard CRUD
    # ------------------------------------------------------------------

    async def add_room(self, name: str) -> None:
        from .models import RoomConfig, EntityPageConfig

        room = RoomConfig(id=self.config.next_id_for("room"), name=name)
        self.config.rooms.append(room)
        page = next(
            (p for p in self.config.pages if p.room_id == room.id and not p.is_scenes_page),
            None,
        )
        if page is None:
            self.config.pages.append(
                EntityPageConfig(
                    id=self.config.next_id_for("page"),
                    room_id=room.id,
                    page_type=4,
                    is_scenes_page=False,
                )
            )
        await self.async_save()

    async def remove_room(self, room_id: int) -> None:
        self.config.rooms = [r for r in self.config.rooms if r.id != room_id]
        self.config.lights = [l for l in self.config.lights if l.room_id != room_id]
        self.config.pages = [p for p in self.config.pages if p.room_id != room_id]
        fallback = self.config.rooms[0].id if self.config.rooms else 0
        for panel in self.config.panels:
            panel.rooms = [rid for rid in panel.rooms if rid != room_id]
            if panel.room_id == room_id:
                panel.room_id = fallback
        await self.async_save()

    async def add_light(
        self,
        name: str,
        ha_entity: str,
        room_id: int,
        page_id: int,
        page_slot: int,
        light_type: str = "table",
        can_dim: bool = False,
        can_color_temperature: bool = False,
        can_rgb: bool = False,
    ) -> None:
        from .models import LightConfig

        light = LightConfig(
            id=self.config.next_id_for("light"),
            name=name,
            ha_entity=ha_entity,
            room_id=room_id,
            page_id=page_id,
            page_slot=page_slot,
            light_type=light_type,
            can_dim=can_dim,
            can_color_temperature=can_color_temperature,
            can_rgb=can_rgb,
        )
        self.config.lights.append(light)
        await self.async_save()
        self._unsub.append(
            async_track_state_change_event(self.hass, [ha_entity], self._on_light_state_event)
        )
        state = self.hass.states.get(ha_entity)
        if state is not None:
            await self._ingest_light_state(light, state)
        pass  # panels load rooms/pages via HTTP config; no MQTT publish needed

    async def remove_light(self, light_id: int) -> None:
        light = self._light_by_id(light_id)
        self.config.lights = [l for l in self.config.lights if l.id != light_id]
        await self.async_save()
        pass

    async def update_panel(self, panel_id: int, body: dict) -> None:
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        if panel is None:
            return
        if "accepted" in body:
            panel.accepted = bool(body["accepted"])
        if "name" in body and body["name"]:
            panel.name = str(body["name"])
        if "room_id" in body:
            panel.room_id = int(body["room_id"] or 0)
        await self.async_save()
        if panel.accepted and not panel.denied:
            # _send_panel_config already delivers register_accept + reload
            # AND the online status; a second status publish here duplicated
            # every STOMP status frame on every panel save.
            await self._send_panel_config(panel)

    async def remove_panel(self, panel_id: int) -> None:
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        self.config.panels = [p for p in self.config.panels if p.id != panel_id]
        if panel is not None:
            # Purge per-MAC caches/listeners so removals don't leak state.
            mac = topic_safe(panel.mac)
            self._relay_state = {k: v for k, v in self._relay_state.items()
                                 if not (isinstance(k, tuple) and k[0] == mac) and k != panel.mac}
            self._log_backlog.pop(panel.mac, None)
            self._last_telemetry.pop(panel.mac, None)
            self._last_ota_trigger.pop(panel.mac, None)
            self._relay_listeners = {k: v for k, v in self._relay_listeners.items() if v}
        await self.async_save()
        self.notify_panels_changed()

    def export_state(self) -> dict:
        data = self.config.to_dict()
        data["panels"] = [asdict(p) for p in self.config.panels]
        return data

    # ------------------------------------------------------------------
    # Light state machines
    # ------------------------------------------------------------------

    async def _on_light_state_event(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        entity_id = event.data.get("entity_id")
        if new_state is None or entity_id is None:
            return
        light = next((l for l in self.config.lights if l.ha_entity == entity_id), None)
        if light is None:
            return
        await self._ingest_light_state(light, new_state)

    async def _on_thermostat_state_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        for th in self.config.thermostats:
            if th.ha_entity == new_state.entity_id:
                try:
                    th.current_temperature = float(new_state.attributes.get("current_temperature", 0))
                except (ValueError, TypeError):
                    pass
                try:
                    th.set_temperature = float(new_state.attributes.get("temperature", th.set_temperature))
                except (ValueError, TypeError):
                    pass
                pass  # firmware has no thermostat MQTT consumer; state stays in HA


    async def _ingest_light_state(self, light: LightConfig, new_state: State) -> None:
        changed = False
        attrs = new_state.attributes or {}
        ha_state = new_state.state

        if ha_state == "on":
            if not light.state:
                changed = True
            light.state = True
            if light.can_dim:
                if attrs.get("brightness") is not None:
                    brightness = int(float(attrs["brightness"]) / 255 * 100)
                else:
                    brightness = 100
                if brightness != light.brightness:
                    changed = True
                light.brightness = brightness
            else:
                if light.brightness != 100:
                    changed = True
                light.brightness = 100
        elif ha_state == "off":
            if light.state:
                changed = True
            light.state = False

        color_mode = attrs.get("color_mode")
        if color_mode == "color_temp" and light.can_color_temperature:
            light.mode = "default"
            kelvin = attrs.get("color_temp_kelvin")
            if kelvin is not None and int(kelvin) != light.color_temp:
                changed = True
                light.color_temp = int(kelvin)
        elif color_mode == "hs" and light.can_rgb:
            light.mode = "rgb"
            hs = attrs.get("hs_color")
            if hs and len(hs) >= 2 and (int(hs[0]) != light.hue or int(hs[1]) != light.saturation):
                changed = True
                light.hue = int(hs[0])
                light.saturation = int(hs[1])

        if changed:
            self._schedule_save()
            await self._publish_light_state(light)

    async def _publish_light_state(self, light: LightConfig) -> None:
        """Publish plain-text light state the firmware subscribes to.

        nspanel/entities/light/<id>/{state_brightness_pct,state_kelvin,
        state_hue,state_sat} — atoi-parsed by the panel. Kelvin is absolute
        (the panel clamps to color_temp_min/max and applies reverse itself).
        """
        settings = self.config.settings
        base = f"nspanel/entities/light/{light.id}"
        kelvin = light.color_temp or settings.color_temp_min
        kelvin = min(max(int(kelvin), settings.color_temp_min), settings.color_temp_max)
        await self._publish(f"{base}/state_brightness_pct", str(light.brightness if light.state else 0), True)
        await self._publish(f"{base}/state_kelvin", str(kelvin), True)
        await self._publish(f"{base}/state_hue", str(int(light.hue)), True)
        await self._publish(f"{base}/state_sat", str(int(light.saturation)), True)



    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _on_manager_command(self, msg) -> None:
        """Panel JSON commands on nspanel/mqttmanager/command.

        Firmware shapes (all JSON):
        - {"command": "register_request", "mac_origin", "friendly_name", ...}
        - {"method": "set", "attribute": "brightness"|"kelvin"|"saturation"|"hue",
           <attribute>: <int>, "entity_ids": [<panel light ids>]}
        - {"command": "activate_scene"|"save_scene", "scene_id": <id>}
        """
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("command") == "register_request":
            mac = data.get("mac_origin") or data.get("mac_address") or data.get("mac") or ""
            if mac:
                await self._handle_register_request(mac, data)
            return
        if data.get("command") == "activate_scene":
            scene = next(
                (s for s in self.config.scenes if s.id == data.get("scene_id")), None
            )
            if scene is not None:
                await self._activate_scene(scene, None)
            else:
                _LOGGER.warning("activate_scene for unknown scene %r", data.get("scene_id"))
            return
        if data.get("command") == "save_scene":
            scene = next(
                (s for s in self.config.scenes if s.id == data.get("scene_id")), None
            )
            if scene is not None and not scene.ha_entity:
                await self._save_scene(scene)
            else:
                _LOGGER.warning("save_scene for unknown/managed scene %r", data.get("scene_id"))
            return
        if data.get("method") == "set":
            attribute = data.get("attribute", "")
            entity_ids = data.get("entity_ids") or []
            value_key = {"brightness": "brightness", "kelvin": "kelvin",
                         "saturation": "saturation", "hue": "hue"}.get(attribute)
            if value_key is None:
                _LOGGER.warning("Unknown panel light attribute %r", attribute)
                return
            try:
                value = int(data.get(value_key, 0))
            except (ValueError, TypeError):
                _LOGGER.warning("Bad panel light value %r", data.get(value_key))
                return
            for light_id in entity_ids:
                try:
                    lid = int(light_id)
                except (ValueError, TypeError):
                    continue
                light = self._light_by_id(lid)
                if light is None:
                    _LOGGER.warning("Panel set for unknown light id %r", light_id)
                    continue
                if attribute == "brightness":
                    lc = {"has_brightness": True, "brightness": value}
                elif attribute == "kelvin":
                    lc = {"has_color_temperature": True, "color_temperature": value}
                elif attribute == "hue":
                    lc = {"has_hue": True, "hue": value}
                else:  # saturation
                    lc = {"has_saturation": True, "saturation": value}
                await self._apply_light_command(light, lc)
            return
        _LOGGER.debug("Ignoring unknown manager command %r", data.get("command") or data.get("method"))

    async def _on_relay_state(self, msg) -> None:
        state = str(msg.payload).strip().lower() in ("1", "true", "on")
        # Dispatch by (mac, relay), never by topic string: the topic carries
        # the hostname, which changes on rename — MAC-keyed state survives.
        # Parse the segment verbatim (hostnames keep case/spaces on the wire).
        segment, relay = "", 0
        try:
            parts = str(msg.topic).split("/")
            if len(parts) == 3 and parts[0] == "nspanel" and parts[2] in ("r1_state", "r2_state"):
                segment = parts[1]
                relay = int(parts[2][1])
        except (ValueError, TypeError, IndexError):
            segment, relay = "", 0
        panel = self._panel_by_topic(segment) if segment else None
        key = (topic_safe(panel.mac), relay) if panel is not None and relay in (1, 2) else None
        if key is None:
            # Unparseable or unknown panel: keep the raw topic as a fallback
            # key so the payload is still recorded.
            self._relay_state[msg.topic] = state
            return
        self._relay_state[key] = state
        for listener in list(self._relay_listeners.get(key, [])):
            try:
                listener(state)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Relay listener failed")

    def _on_stomp_send(self, frame: dict) -> None:
        """Bridge UI actions (STOMP SEND from the browser) to MQTT.

        The browser cannot publish MQTT itself. Only nspanel/<panel>/command
        destinations from a known panel are forwarded, and the payload is
        normalized to the JSON the firmware parses (bare words like
        'reboot' become {"command": "reboot"}; gui_update maps to tft_update).
        """
        dest = str(frame.get("destination", ""))
        parts = dest.split("/")
        if len(parts) != 3 or parts[0] != "nspanel" or parts[2] != "command":
            return
        panel = self._panel_by_topic(parts[1])
        if panel is None or not panel.accepted:
            _LOGGER.warning("STOMP SEND to unknown/unaccepted panel %r ignored", parts[1])
            return
        body = str(frame.get("body", "") or "").strip()
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or "command" not in payload:
                raise ValueError("no command key")
        except (ValueError, TypeError):
            command = {"gui_update": "tft_update", "firmware_update_force": "firmware_update"}.get(body, body)
            payload = {"command": command}
        self.hass.async_create_task(
            self._publish(self._panel_cmd_topic(panel, "command"), json.dumps(payload))
        )

    async def _on_panel_log(self, msg) -> None:
        """Forward panel log lines to the UI over STOMP.

        The firmware publishes JSON lines to nspanel/<hostname>/log; the edit
        page subscribes to nspanel/<mac>/log (live) and .../log_backlog.
        """
        segment = mac_from_topic(msg.topic, "log")
        if not segment:
            return
        panel = self._panel_by_topic(segment)
        if panel is None or self.stomp is None:
            return
        self._note_panel_hostname(panel, self._topic_segment(msg.topic))
        if isinstance(msg.payload, (bytes, bytearray)):
            text = msg.payload.decode("utf-8", "replace")
        else:
            text = str(msg.payload)
        try:
            entry = json.loads(text)
            if not isinstance(entry, dict):
                entry = {"time": "", "level": "INFO", "message": text}
        except (ValueError, TypeError):
            entry = {"time": "", "level": "INFO", "message": text}
        backlog = self._log_backlog.setdefault(panel.mac, [])
        backlog.append(entry)
        del backlog[:-50]
        base = panel_topic(panel.mac, "log")
        self.stomp.update_topic(base, json.dumps(entry))
        self.stomp.set_retained(f"{base}_backlog", True)
        self.stomp.update_topic(f"{base}_backlog", json.dumps({"logs": backlog}))

    def _register_accept_reply(self, panel: PanelConfig) -> str:
        return json.dumps({
            "command": "register_accept",
            "address": self.config.settings.manager_address,
            "port": self.config.settings.manager_port,
            "config_topic": f"nspanel/{panel.mac}/config",
        })

    async def _apply_light_command(self, light: LightConfig, lc: dict | None, toggle_on: bool | None = None) -> None:
        settings = self.config.settings
        service_data: dict[str, Any] = {}

        if toggle_on is not None:
            light.state = toggle_on
            service = "turn_on" if toggle_on else "turn_off"
        elif lc is not None:
            if lc.get("has_brightness"):
                light.brightness = min(max(int(lc.get("brightness", 0)), 0), 100)
            if lc.get("has_color_temperature"):
                light.mode = "default"
                light.color_temp = int(lc.get("color_temperature", 0))
            if lc.get("has_hue") or lc.get("has_saturation"):
                light.mode = "rgb"
                light.hue = int(lc.get("hue", 0))
                light.saturation = int(lc.get("saturation", 0))
            if lc.get("has_brightness"):
                light.state = light.brightness > 0
            service = "turn_on" if light.state else "turn_off"
        else:
            service = "turn_on" if light.state else "turn_off"

        if service == "turn_on":
            if light.can_dim and light.brightness:
                service_data["brightness_pct"] = light.brightness
            if light.mode == "default" and light.can_color_temperature:
                service_data["color_temp_kelvin"] = light.color_temp or settings.color_temp_min
            elif light.mode == "rgb" and light.can_rgb:
                service_data["hs_color"] = (light.hue, light.saturation)

        await self.hass.services.async_call(
            "light", service, {"entity_id": light.ha_entity, **service_data}
        )
        await self._publish_light_state(light)

    async def _save_scene(self, scene: SceneConfig) -> None:
        """Save current light states into an NSPM-managed scene."""
        page = next((p for p in self.config.pages if p.id == scene.page_id), None)
        room_id = page.room_id if page and page.room_id else None
        light_states = []
        for light in self.config.lights:
            if room_id is None or light.room_id != room_id:
                continue
            light_states.append(
                {
                    "light_id": light.id,
                    "light_level": light.brightness if light.state else 0,
                    "color_mode": "rgb" if light.mode == "rgb" else "dimmer",
                    "color_temperature": light.color_temp,
                    "hue": light.hue,
                    "saturation": light.saturation,
                }
            )
        scene.light_states = light_states
        await self.async_save()
        _LOGGER.info("Saved scene %s (%s)", scene.id, scene.name)

    async def _poll_weather(self, now) -> None:
        """Poll open-meteo and publish the JSON the firmware renders.

        nspanel/status/weather (retained JSON): icon/temp/wind/sunrise/
        sunset/maxmin/prepro + forecast[] of {day,icon,maxmin,prepro,wind}.
        """
        from homeassistant.helpers import aiohttp_client
        from homeassistant.util import dt as dt_util

        s = self.config.settings
        try:
            lat = float(s.location_latitude)
            lon = float(s.location_longitude)
        except (ValueError, TypeError):
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        try:
            temp_unit = "fahrenheit" if s.use_fahrenheit else "celsius"
            precip_unit = "inch" if s.precipitation_format == "inch" else "mm"
            wind_unit = {"kmh": "kmh", "ms": "ms", "mph": "mph", "kn": "kn"}.get(s.wind_speed_format, "kmh")
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max"
                f"&timeformat=unixtime&temperature_unit={temp_unit}&precipitation_unit={precip_unit}&wind_speed_unit={wind_unit}&timezone=auto"
            )
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Weather fetch failed: HTTP %s", resp.status)
                    return
                data = await resp.json()
            ICONS = {0: "sunny", 1: "partlytuner_day", 2: "cloudy_weather_day", 3: "overcast",
                     45: "fog", 48: "fog", 51: "rainy", 53: "rainy", 55: "rainy", 56: "sleet", 57: "sleet",
                     61: "rainy", 63: "rainy", 65: "rainy", 66: "sleet", 67: "sleet", 71: "snowy", 73: "snowy",
                     75: "snowy", 77: "snowy", 80: "rainy", 81: "rainy", 82: "rainy", 85: "snowy", 86: "snowy",
                     95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm"}
            def icon(code):
                try:
                    return ICONS.get(int(code), "cloudy_weather_day")
                except (ValueError, TypeError):
                    return "cloudy_weather_day"
            def num(v, default=0):
                try:
                    return v if isinstance(v, (int, float)) else float(v)
                except (ValueError, TypeError):
                    return default
            def fmt_temp(v):
                v = num(v)
                if s.use_fahrenheit:
                    return f"{int(round(v))}°F"
                return f"{int(round(v))}°C"
            def fmt_wind(v):
                v = num(v)
                if s.wind_speed_format == "ms":
                    return f"{v:.1f} m/s"
                if s.wind_speed_format == "mph":
                    return f"{int(round(v))} mph"
                if s.wind_speed_format == "kn":
                    return f"{int(round(v))} kn"
                return f"{int(round(v))} km/h"
            def fmt_time_local(ts):
                try:
                    return dt_util.as_local(
                        dt_util.utc_from_timestamp(int(ts))
                    ).strftime("%H:%M")
                except Exception:  # noqa: BLE001
                    return ""
            def day_name(ts):
                try:
                    return dt_util.as_local(
                        dt_util.utc_from_timestamp(int(ts))
                    ).strftime("%a")
                except Exception:  # noqa: BLE001
                    return ""
            cur = data.get("current", {}) or {}
            daily = data.get("daily", {}) or {}

            # Outside temperature from a HA sensor instead of open-meteo
            # when the user picked a sensor provider on the weather page.
            outside_temp = None
            provider = (s.outside_temp_provider or "").strip()
            sensor_entity = (s.outside_temp_sensor_entity or "").strip()
            if provider and sensor_entity:
                st = self.hass.states.get(sensor_entity)
                if st is not None and st.state not in ("unknown", "unavailable", ""):
                    try:
                        outside_temp = float(st.state)
                    except (ValueError, TypeError):
                        outside_temp = None

            def dl(key, i, default=0):
                vals = daily.get(key) or []
                return vals[i] if i < len(vals) else default

            n_days = min(5, len(daily.get("weather_code", []) or []))
            forecast = []
            for i in range(n_days):
                forecast.append({
                    "day": day_name(dl("time", i, 0)),
                    "icon": icon(dl("weather_code", i, 0)),
                    "maxmin": f"{fmt_temp(dl('temperature_2m_max', i))}/{fmt_temp(dl('temperature_2m_min', i))}",
                    "prepro": f"{precip_unit} {int(num(dl('precipitation_probability_max', i)))}%",
                    "wind": fmt_wind(dl("wind_speed_10m_max", i)),
                })
            payload = {
                "icon": icon(cur.get("weather_code", 0)),
                "temp": fmt_temp(outside_temp if outside_temp is not None else cur.get("temperature_2m", 0)),
                "wind": fmt_wind(cur.get("wind_speed_10m", 0)),
                "sunrise": fmt_time_local(dl("sunrise", 0, 0)),
                "sunset": fmt_time_local(dl("sunset", 0, 0)),
                "maxmin": f"{fmt_temp(dl('temperature_2m_max', 0))}/{fmt_temp(dl('temperature_2m_min', 0))}",
                "prepro": f"{num(cur.get('precipitation', 0))} {precip_unit}",
                "forecast": forecast,
            }
            await self._publish("nspanel/status/weather", json.dumps(payload), True)
            _LOGGER.debug("Weather update published")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Weather poll failed: %s", exc)

    async def _activate_scene(self, scene: SceneConfig, triggering_room_id: int | None = None) -> None:
        """Activate a scene — HA scene/script or NSPM-saved light states."""
        if scene.ha_entity:
            # HA-backed scene/script
            if scene.ha_entity.startswith("scene."):
                await self.hass.services.async_call(
                    "scene", "turn_on", {"entity_id": scene.ha_entity}
                )
            elif scene.ha_entity.startswith("script."):
                await self.hass.services.async_call(
                    "script", "turn_on",
                    {"entity_id": scene.ha_entity, "variables": {"nspanelmanager": {
                        "scene_name": scene.name,
                        "scene_id": scene.id,
                    }}},
                )
            return
        # NSPM-managed scene: apply saved light states
        for ls in scene.light_states:
            light = self._light_by_id(ls.get("light_id", 0))
            if light is None:
                continue
            level = ls.get("light_level", 0)
            if level <= 0:
                light.state = False
                await self.hass.services.async_call("light", "turn_off", {"entity_id": light.ha_entity})
            else:
                light.state = True
                light.brightness = level
                svc_data = {"entity_id": light.ha_entity, "brightness_pct": level}
                if ls.get("color_mode") == "dimmer" and light.can_color_temperature:
                    light.color_temp = ls.get("color_temperature", light.color_temp)
                    svc_data["color_temp_kelvin"] = light.color_temp
                elif ls.get("color_mode") == "rgb" and light.can_rgb:
                    light.mode = "rgb"
                    light.hue = ls.get("hue", 0)
                    light.saturation = ls.get("saturation", 0)
                    svc_data["hs_color"] = (light.hue, light.saturation)
                await self.hass.services.async_call("light", "turn_on", svc_data)
            await self._publish_light_state(light)

    async def _republish_all_state(self) -> None:
        """Republish light states for all mapped lights (plain-text topics)."""
        for light in self.config.lights:
            await self._publish_light_state(light)
        await self._publish_time(None)

    # ------------------------------------------------------------------
    # Time publishing
    # ------------------------------------------------------------------


    async def _publish_time(self, now) -> None:
        from homeassistant.util import dt as dt_util

        settings = self.config.settings
        current = dt_util.as_local(now) if now else dt_util.now()
        time_str = (
            current.strftime("%I:%M")
            if settings.clock_us_style
            else current.strftime("%H:%M")
        )
        ampm = current.strftime("%p") if settings.clock_us_style else ""
        try:
            date_str = current.strftime(settings.date_format or "%d/%m")
        except (ValueError, TypeError):
            date_str = current.strftime("%d/%m")
        # Legacy fixed topics the firmware subscribes to (ScreensaverPage).
        await self._publish("nspanel/status/time", time_str, True)
        await self._publish("nspanel/status/date", date_str, True)
        await self._publish("nspanel/status/ampm", ampm, True)
        # Per-panel screensaver mode (ScreensaverPage subscribes to it).
        # "global" must be resolved to the actual mode: the firmware treats
        # the raw payload as the mode string and logs Unknown-mode errors.
        from .dashboard import _resolve_screensaver_mode

        for panel in self.config.panels:
            if panel.accepted:
                mode = _resolve_screensaver_mode(panel, settings)
                await self._publish(
                    self._panel_cmd_topic(panel, "screensaver_mode"),
                    mode,
                    True,
                )
