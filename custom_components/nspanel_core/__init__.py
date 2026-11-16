"""NSPanel Core v2 — HA glue: binds MQTT to the transport-injected core and
serves the OTA endpoints. Thin by design; all logic lives in the core."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.storage import Store

from . import firmware_store
from .const import (
    DOMAIN,
    OTA_ENDPOINTS,
    TOPIC_MANAGER_COMMAND,
    TOPIC_PANEL_STATUS,
    TOPIC_PANEL_STATUS_REPORT,
)
from .manager import Core, ManagerConfig
from .models import Panel

_LOGGER = logging.getLogger(__name__)

STORE_DIR = "nspanel_core/firmware"   # under hass config dir


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = ManagerConfig(
        manager_address=_manager_address(hass),
        manager_port=8123,
        panels=[],
    )
    # Persistence: panels (accepted/denied), deletions and settings survive
    # HA restarts — without this every restart reset acceptance to none.
    store = Store(hass, 1, "nspanel_core_state.json")
    saved = await store.async_load() or {}
    cfg.panels = [Panel.from_dict(d) for d in saved.get("panels", [])]
    cfg.deleted_macs = list(saved.get("deleted_macs", []))

    async def _save_state() -> None:
        await store.async_save({
            "panels": [p.to_dict() for p in core.config.panels],
            "deleted_macs": core.config.deleted_macs,
        })

    def _on_new_panel(panel) -> None:
        hass.add_job(_save_state())

    core = Core(cfg, publish=_make_publisher(hass), on_new_panel=_on_new_panel)
    active = await hass.async_add_executor_job(
        firmware_store.load_active, str(Path(hass.config.path()) / STORE_DIR)
    )

    async def on_register(msg):
        await hass.async_add_executor_job(core.handle_register_request, msg.payload)
        await _save_state()
        # refresh the served set opportunistically — never stale (P131/P132)
        await _refresh_firmware(hass, core)

    async def on_status_report(msg):
        segment = msg.topic.split("/")[1]
        await hass.async_add_executor_job(core.handle_status_report, segment, msg.payload)

    async def on_relay_state(msg):
        # nspanel/<hostname>/r{1,2}_state — segment = hostname, verbatim
        parts = msg.topic.split("/")
        segment, relay = parts[1], 1 if parts[2].startswith("r1") else 2
        await hass.async_add_executor_job(
            core.handle_relay_state, segment, relay, msg.payload
        )

    unsub_mqtt = [
        await mqtt.async_subscribe(hass, TOPIC_MANAGER_COMMAND, on_register),
        await mqtt.async_subscribe(hass, TOPIC_PANEL_STATUS_REPORT, on_status_report),
        await mqtt.async_subscribe(hass, TOPIC_PANEL_STATUS, _on_panel_status),
        await mqtt.async_subscribe(hass, "nspanel/+/r1_state", on_relay_state),
        await mqtt.async_subscribe(hass, "nspanel/+/r2_state", on_relay_state),
    ]
    _register_ota_views(hass, active)

    # P159: time/date/ampm publishing (v1 ScreensaverPage contract — the
    # panel's clock lives off these retained topics; every 60 s + at start)
    async def _publish_time(_now=None) -> None:
        from homeassistant.util import dt as dt_util

        now = dt_util.now()
        s = core.config.settings
        time_str = (
            now.strftime("%I:%M") if s.clock_us_style else now.strftime("%H:%M")
        )
        ampm = now.strftime("%p") if s.clock_us_style else ""
        try:
            date_str = now.strftime(s.date_format or "%d/%m")
        except (ValueError, TypeError):
            date_str = now.strftime("%d/%m")
        await mqtt.async_publish(hass, "nspanel/status/time", time_str, retain=True)
        await mqtt.async_publish(hass, "nspanel/status/date", date_str, retain=True)
        await mqtt.async_publish(hass, "nspanel/status/ampm", ampm, retain=True)

    from homeassistant.helpers.event import async_track_time_interval

    entry.async_on_unload(
        async_track_time_interval(hass, _publish_time, __import__("datetime").timedelta(seconds=60))
    )
    await _publish_time(None)
    # Dashboard + sidebar (parity: the management UI is back)
    from .dashboard import register_dashboard

    register_dashboard(hass)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "core": core,
        "unsub": unsub_mqtt,
        "active": active,
        "save": _save_state,
    }
    entry.async_on_unload(entry.add_update_listener(_reload))
    # Entity platforms (parity: sensors + relay switches + lights) — forward
    # AFTER hass.data is populated (the platforms read the core from it).
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "switch", "light"]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id)
    for unsub in data["unsub"]:
        unsub()
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _make_publisher(hass: HomeAssistant):
    """Return a THREAD-SAFE publish callable.

    The core runs inside hass.async_add_executor_job (a worker thread) —
    creating tasks directly on the loop from that thread is not thread-safe
    (P162 audit finding). call_soon_threadsafe is the correct bridge.
    """

    async def _publish(topic: str, payload: str, retain: bool = False) -> None:
        await mqtt.async_publish(hass, topic, payload, retain=retain)

    def publish(topic: str, payload: str, retain: bool = False) -> None:
        hass.loop.call_soon_threadsafe(
            hass.async_create_task, _publish(topic, payload, retain)
        )

    return publish


def _manager_address(hass: HomeAssistant) -> str:
    """LAN address HA answers OTA downloads on."""
    url = hass.config.internal_url or hass.config.external_url or ""
    return url.split("//")[-1].split(":")[0] if url else ""


async def _on_panel_status(msg):
    """Retained online/offline state — nothing to adopt in v2 core yet."""
    return


async def _refresh_firmware(hass: HomeAssistant, core: Core) -> None:
    """Fetch manifest + activate when newer. Serving is either verified-new
    or nothing (P131/P132)."""
    import dataclasses

    manifest = await firmware_store.fetch_manifest(hass)
    if not manifest:
        return
    data = hass.data[DOMAIN]
    entry_id = next(iter(data))
    active = data[entry_id].get("active")
    current = active.version if active else "0.0.0"
    if not firmware_store.is_newer(manifest["version"], current):
        return
    store = str(Path(hass.config.path()) / STORE_DIR)
    new = await firmware_store.download_and_activate(hass, manifest, store)
    if new is None:
        _LOGGER.error("Firmware activation failed — OTA serving stays on %s", current)
        return
    data[entry_id]["active"] = new
    for panel in core.config.panels:
        if panel.accepted:
            core.send_firmware_update(panel)
            _LOGGER.info("Pushed firmware %s to panel %s", new.version, panel.name)


_VIEW_HASS = {"hass": None}


class OtaFileView(HomeAssistantView):
    """Serves ONLY active-overlay bytes. No overlay → 503, never stale."""

    requires_auth = False

    _kind = ("", "")

    async def get(self, request, **kwargs):
        hass = _VIEW_HASS["hass"]
        kind, name = self._kind
        path = firmware_store.served_path(_current(hass), kind, name, "")
        if not path or not Path(path).is_file():
            return web.Response(status=503, text="No active verified firmware set")
        return web.FileResponse(path)


class DownloadFirmware(OtaFileView):
    url = "/download_firmware"
    name = "nspanel_core:ota:download_firmware"
    _kind = ("firmware/sonoff", "firmware.bin")


class DownloadDataFile(OtaFileView):
    url = "/download_data_file"
    name = "nspanel_core:ota:download_data_file"
    _kind = ("firmware/sonoff", "data_file.bin")


class ChecksumFirmware(OtaFileView):
    url = "/checksum_firmware"
    name = "nspanel_core:ota:checksum_firmware"
    _kind = ("firmware/sonoff", "firmware.bin")

    async def get(self, request, **kwargs):
        hass = _VIEW_HASS["hass"]
        kind, name = self._kind
        path = firmware_store.served_path(_current(hass), kind, name, "")
        if not path or not Path(path).is_file():
            return web.Response(status=503, text="No active verified firmware set")
        return web.Response(text=firmware_store.md5_of(path))


class ChecksumDataFile(OtaFileView):
    url = "/checksum_data_file"
    name = "nspanel_core:ota:checksum_data_file"
    _kind = ("firmware/sonoff", "data_file.bin")

    async def get(self, request, **kwargs):
        hass = _VIEW_HASS["hass"]
        kind, name = self._kind
        path = firmware_store.served_path(_current(hass), kind, name, "")
        if not path or not Path(path).is_file():
            return web.Response(status=503, text="No active verified firmware set")
        return web.Response(text=firmware_store.md5_of(path))


class DownloadTftEu(OtaFileView):
    url = "/download_tft_eu"
    name = "nspanel_core:ota:download_tft_eu"
    _kind = ("tft", "gui.tft")


class DownloadTftUs(OtaFileView):
    url = "/download_tft_us"
    name = "nspanel_core:ota:download_tft_us"
    _kind = ("tft", "gui_us.tft")


def _register_ota_views(hass: HomeAssistant, active) -> None:
    _VIEW_HASS["hass"] = hass
    for cls in (DownloadFirmware, DownloadDataFile, ChecksumFirmware,
                ChecksumDataFile, DownloadTftEu, DownloadTftUs):
        hass.http.register_view(cls())


def _current(hass: HomeAssistant):
    data = hass.data.get(DOMAIN) or {}
    if not data:
        return None
    entry_id = next(iter(data))
    return data[entry_id].get("active")

