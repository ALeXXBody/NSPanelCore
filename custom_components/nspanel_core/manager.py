"""NSPanel Core manager — the integration's core.

Ports the external behavior of the C++ MQTT bridge onto HA's event bus:
- Panel registration (JSON status -> register_accept -> NSPanelConfig protobuf)
- Light state machines driven by HA state events
- HA service calls for light commands (same semantics incl. optimistic mode)
- Room aggregation and NSPanelRoomStatus protobuf publication
- Command routing for NSPanelMQTTManagerCommand
- Minute-aligned time/date publishing
- STOMP mirroring so the original web UI gets live updates
"""

from __future__ import annotations

import base64
import json
import logging
import pathlib
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
import aiohttp
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    TOPIC_PANEL_STATUS,
    TOPIC_PANEL_COMMAND,
    TOPIC_PANEL_STATUS_REPORT,
    TOPIC_MANAGER_COMMAND,
    panel_topic,
    room_state_topic,
    light_state_topic,
    entity_page_state_topic,
    time_topic,
    weather_topic,
    date_topic,
    ampm_topic,
    status_topic,
    config_reload_topic,
)
from .models import IntegrationConfig, LightConfig, PanelConfig, SceneConfig, ThermostatConfig, RelayGroupConfig
from .panel_pb import messages as pbw

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
        return parts[1]
    return ""


class NSPanelManager:
    """Central coordinator."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = IntegrationConfig()
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._unsub = []
        self._new_panel_listeners: list = []
        self._report_listeners: list = []
        self._relay_listeners: dict[str, list] = {}
        self._relay_state: dict[str, bool] = {}
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

        self.stomp = StompServer()
        async_register_ui(self.hass, self.entry.entry_id)

        # Protobuf topics: binary payloads (encoding=None → bytes)
        await mqtt.async_subscribe(
            self.hass, TOPIC_PANEL_COMMAND, self._on_panel_command, encoding=None
        )
        await mqtt.async_subscribe(
            self.hass, TOPIC_PANEL_STATUS_REPORT, self._on_panel_status_report, encoding=None
        )
        await mqtt.async_subscribe(self.hass, TOPIC_PANEL_STATUS, self._on_panel_status)
        await mqtt.async_subscribe(self.hass, TOPIC_MANAGER_COMMAND, self._on_manager_command)
        await mqtt.async_subscribe(self.hass, "nspanel/+/relay1_state", self._on_relay_state)
        await mqtt.async_subscribe(self.hass, "nspanel/+/relay2_state", self._on_relay_state)

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
        self._unsub.append(async_track_time_interval(self.hass, self._poll_weather, timedelta(minutes=self.config.settings.weather_update_interval or 30)))
        self.hass.async_create_task(self._poll_weather(None))
        _LOGGER.info("NSPanel Core manager started")

    async def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub = []

    async def apply_settings(self, user_input: dict) -> None:
        s = self.config.settings
        for key, value in user_input.items():
            if hasattr(s, key) and key in s.__dataclass_fields__:
                setattr(s, key, value)
        await self.async_save()
        await self._publish_manager_status()

    async def async_save(self) -> None:
        await self._store.async_save(self.config.to_dict())

    # ------------------------------------------------------------------
    # MQTT helpers
    # ------------------------------------------------------------------

    async def _publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        await mqtt.async_publish(self.hass, topic, payload, 0, retain)
        if self.stomp is not None:
            self.stomp.mirror_mqtt(topic, payload, retain)

    async def _publish_protobuf(self, topic: str, message: bytes, retain: bool = False) -> None:
        await self._publish(topic, message, retain)

    async def _publish_manager_status(self) -> None:
        await self._publish(
            status_topic(self.config.settings.manager_address),
            json.dumps({"state": "online", "version": _MANAGER_VERSION}),
            True,
        )

    async def _publish_panel_status(self, panel: PanelConfig, state: str, progress: int = 0) -> None:
        if self.stomp is None:
            return
        self.stomp.set_retained(panel_topic(panel.mac, "status"), True)
        self.stomp.update_topic(panel_topic(panel.mac, "status"), json.dumps({"state": state, "progress": progress}))

    # ------------------------------------------------------------------
    # Panel registration (JSON flow, same as the add-on)
    # ------------------------------------------------------------------

    async def _on_panel_status(self, msg) -> None:
        mac = mac_from_topic(msg.topic, "status")
        if not mac:
            return
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.debug("Ignoring non-JSON status from %s", mac)
            return

        state = data.get("state", "")
        panel = self._panel_by_mac(mac)

        if state == "register_request":
            await self._handle_register_request(mac, data)
        elif state == "online":
            if panel:
                panel.online = True
                await self.async_save()
                await self._send_panel_config(panel)
                await self._publish_panel_status(panel, "online")

    async def _handle_register_request(self, mac: str, data: dict) -> None:
        panel = self._panel_by_mac(mac)
        if panel is None:
            friendly = data.get("friendly_name", f"NSPanel {mac[-4:].upper()}")
            if not self.config.rooms:
                _LOGGER.error("Cannot register NSPanel: no rooms exist. Create a room first.")
                return
            panel = PanelConfig(
                id=self.config.next_id_for("panel"),
                mac=mac,
                name=friendly,
                model=data.get("model", "sonoff"),
                room_id=self.config.rooms[0].id,
                version=data.get("version", "UNKNOWN"),
            )
            self.config.panels.append(panel)
            await self.async_save()
            _LOGGER.info("New panel registered as awaiting accept: %s (%s)", friendly, mac)

        await self._publish_panel_status(panel, "awaiting_accept")

        # Store registration metadata (same fields the C++ bridge kept)
        panel.name = data.get("friendly_name") or panel.name
        panel.model = data.get("model", "sonoff")
        if data.get("md5_firmware"):
            panel.firmware_md5 = data["md5_firmware"]
        if data.get("md5_tft_file"):
            panel.tft_md5 = data["md5_tft_file"]
        if data.get("md5_data_file"):
            panel.littlefs_md5 = data["md5_data_file"]

        reply = self._register_accept_reply(panel)
        if panel.accepted and not panel.denied:
            # Accepted panels get the accept reply on both topics + config,
            # exactly like the C++ bridge.
            await self._publish(
                panel_topic(data.get("friendly_name") or mac, "command"), reply
            )
            await self._publish(panel_topic(mac, "command"), reply)
            await self._send_panel_config(panel)
            await self._publish_panel_status(panel, "online")

        if panel.id == self.config.panels[-1].id and not panel.accepted:
            # New registration: notify the UI (original event chain)
            if self.stomp is not None:
                self.stomp.update_topic(
                    "mqttmanager/events",
                    json.dumps({"event_type": "register_request", "nspanel_id": panel.id}),
                )
        await self.async_save()

    async def _send_panel_config(self, panel: PanelConfig) -> None:
        """Build and send the NSPanelConfig protobuf for a panel."""
        rooms = self.config.rooms
        room_ids = panel.rooms or [r.id for r in rooms]
        global_scene_page_ids = [
            p.id for p in self.config.pages if p.room_id is None and p.is_scenes_page
        ]

        config_payload: dict[str, Any] = {
            "name": panel.name,
            "default_room": panel.room_id,
            "default_page": panel.default_page,
            "screensaver_activation_timeout": panel.screensaver_activation_timeout,
            "min_button_push_time": panel.min_button_push_time,
            "button_long_press_time": panel.button_long_press_time,
            "special_mode_trigger_time": panel.special_mode_trigger_time,
            "special_mode_release_time": panel.special_mode_release_time,
            "screen_dim_level": panel.screen_dim_level,
            "screensaver_dim_level": panel.screensaver_dim_level,
            "screensaver_mode": panel.screensaver_mode,
            "show_screensaver_inside_temperature": True,
            "show_screensaver_outside_temperature": bool(
                self.config.settings.outside_temp_sensor_entity
            ),
            "clock_us_style": panel.clock_us_style,
            "use_fahrenheit": panel.use_fahrenheit,
            "is_us_panel": panel.is_us_panel,
            "reverse_relays": panel.reverse_relays,
            "relay1_default_mode": panel.relay1_default_mode,
            "relay2_default_mode": panel.relay2_default_mode,
            "temperature_calibration": panel.temperature_calibration,
            "button1_mode": panel.button1_mode,
            "button2_mode": panel.button2_mode,
            "optimistic_mode": panel.optimistic_mode,
            "raise_light_level_to_100_above": panel.raise_to_100_light_level,
            "nspanel_id": panel.id,
            "default_light_brightess": panel.default_light_brightness,
            "locked_to_default_room": False,
            "inside_temperature_sensor_mqtt_topic": panel.inside_temperature_sensor_topic,
            "room_infos": [],
            "global_scene_entity_page_ids": global_scene_page_ids,
        }
        for rid in room_ids:
            info = {"room_id": rid, "entity_page_ids": [], "scene_page_ids": []}
            for p in self.config.pages:
                if p.room_id == rid:
                    if p.is_scenes_page:
                        info["scene_page_ids"].append(p.id)
                    else:
                        info["entity_page_ids"].append(p.id)
            config_payload["room_infos"].append(info)

        cfg = pbw.build_nspanel_config(config_payload)
        await self._publish_protobuf(panel_topic(panel.mac, "config"), cfg, True)
        _LOGGER.info("Sent NSPanelConfig to panel %s (%s)", panel.name, panel.mac)
        await self._publish_panel_status(panel, "online")

    async def _on_panel_status_report(self, msg) -> None:
        mac = mac_from_topic(msg.topic, "status_report")
        panel = self._panel_by_mac(mac)
        if not panel:
            return
        try:
            report = pbw.parse_nspanel_status_report(msg.payload)
        except Exception:  # noqa: BLE001
            return
        was_online = panel.online
        panel.online = report.get("nspanel_state", 0) == 0
        panel.firmware_md5 = report.get("md5_firmware", "")
        panel.tft_md5 = report.get("md5_tft_gui", "")
        panel.littlefs_md5 = report.get("md5_littlefs", "")
        await self.async_save()
        if panel.online != was_online:
            for listener in self._new_panel_listeners:
                listener()
        for listener in self._report_listeners:
            listener(mac, report)
        if self.stomp is not None and panel.accepted:
            state_map = {0: "online", 1: "offline", 2: "updating_tft", 3: "updating_fw", 4: "updating_fs"}
            await self._publish_panel_status(
                panel,
                state_map.get(report.get("nspanel_state", 1), "offline"),
                report.get("update_progress", 0),
            )
            # Firmware/data OTA: trigger an update when the panel's reported
            # checksums differ from the manager's (mirrors the C++ has_*_update).
            await self._maybe_trigger_firmware_ota(panel, report)

    def _panel_by_mac(self, mac: str) -> PanelConfig | None:
        for panel in self.config.panels:
            if panel.mac == mac:
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
        import hashlib, os

        firmware_dir = os.path.join(os.path.dirname(__file__), "firmware")
        model = "sonoff"  # default; could be extended to panel.model

        def md5_file(path: str) -> str:
            h = hashlib.md5()
            try:
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
            except FileNotFoundError:
                return ""
            return h.hexdigest()

        fw_md5 = md5_file(os.path.join(firmware_dir, model, "firmware.bin"))
        data_md5 = md5_file(os.path.join(firmware_dir, model, "data_file.bin"))

        if fw_md5 and report.get("md5_firmware") and report["md5_firmware"] != fw_md5:
            _LOGGER.info("Firmware update available for panel %s — triggering OTA", panel.name)
            await self._publish(panel_topic(panel.mac, "command"), json.dumps({"command": "firmware_update"}))

        if data_md5 and report.get("md5_littlefs") and report["md5_littlefs"] != data_md5:
            _LOGGER.info("Data file update available for panel %s — triggering OTA", panel.name)
            await self._publish(panel_topic(panel.mac, "command"), json.dumps({"command": "data_file_update"}))

        import hashlib, os
        tft_dir = os.path.join(os.path.dirname(__file__), "tft")
        tft_filename = "gui_us.tft" if panel.is_us_panel else "gui.tft"
        tft_path = os.path.join(tft_dir, tft_filename)
        def md5_file(p):
            h = hashlib.md5()
            try:
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
            except FileNotFoundError:
                return ""
            return h.hexdigest()
        tft_md5 = md5_file(tft_path)
        if tft_md5 and report.get("md5_tft_gui") and report["md5_tft_gui"] != tft_md5:
            _LOGGER.info("TFT update available for panel %s — triggering OTA", panel.name)
            await self._publish(panel_topic(panel.mac, "command"), json.dumps({"command": "tft_update"}))

    def relay_state(self, topic: str) -> bool:
        return self._relay_state.get(topic, False)

    async def set_relay(self, mac: str, relay: int, state: bool) -> None:
        await self._publish(panel_topic(mac, f"relay{relay}_cmd"), "1" if state else "0")

    async def set_relay_group(self, group_id: int, state: bool) -> None:
        group = next((g for g in self.config.relay_groups if g.id == group_id), None)
        if group is None:
            return
        for binding in group.bindings:
            mac = binding.get("panel_mac", "")
            relay = binding.get("relay_num", 1)
            if mac:
                await self.set_relay(mac, relay, state)

    def add_new_panel_listener(self, listener) -> None:
        self._new_panel_listeners.append(listener)

    def add_report_listener(self, listener) -> None:
        self._report_listeners.append(listener)

    def add_relay_listener(self, mac: str, relay: int, listener):
        topic = f"nspanel/{mac}/relay{relay}_state"
        self._relay_listeners.setdefault(topic, []).append(listener)

        def _unsubscribe() -> None:
            self._relay_listeners.get(topic, []).remove(listener)

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
        for panel in self.config.panels:
            panel.rooms = [rid for rid in panel.rooms if rid != room_id]
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
        await self._publish_entity_page(page_id)
        await self._publish_room_state(room_id)

    async def remove_light(self, light_id: int) -> None:
        light = self._light_by_id(light_id)
        self.config.lights = [l for l in self.config.lights if l.id != light_id]
        await self.async_save()
        if light:
            await self._publish_entity_page(light.page_id)
            await self._publish_room_state(light.room_id)

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
            reply = self._register_accept_reply(panel)
            await self._publish(panel_topic(panel.mac, "command"), reply)
            await self._send_panel_config(panel)
            await self._publish_panel_status(panel, "online")

    async def remove_panel(self, panel_id: int) -> None:
        self.config.panels = [p for p in self.config.panels if p.id != panel_id]
        await self.async_save()

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
                # Publish thermostat state to panels
                await self._publish_thermostat_state(th)

    async def _publish_thermostat_state(self, th: ThermostatConfig) -> None:
        settings = self.config.settings
        from .const import thermostat_state_topic
        payload = pbw.build_nspanel_entity_state_thermostat({
            "thermostat": {
                "thermostat_id": th.id,
                "name": th.name,
                "has_current_temperature": True,
                "current_temperature": th.current_temperature,
                "set_temperature": th.set_temperature,
                "step_size": th.step_size,
                "options": th.options,
            }
        })
        await self._publish_protobuf(thermostat_state_topic(settings.manager_address, th.id), payload, True)

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

        await self.async_save()
        if changed:
            await self._publish_light_state(light)
            await self._publish_room_state(light.room_id)

    async def _publish_light_state(self, light: LightConfig) -> None:
        settings = self.config.settings
        denom = settings.color_temp_max - settings.color_temp_min
        if denom == 0:
            kelvin_pct = 50.0
        else:
            kelvin_pct = (
                (light.color_temp - settings.color_temp_min)
                / denom
                * 100
            )
        if settings.reverse_color_temp:
            kelvin_pct = 100 - kelvin_pct
        payload = pbw.build_nspanel_entity_state_light({
            "light": {
                "light_id": light.id,
                "name": light.name,
                "state": light.state,
                "can_color_temp": light.can_color_temperature,
                "can_color": light.can_rgb,
                "brightness": light.brightness,
                "color_temp": int(kelvin_pct),
                "hue": light.hue,
                "saturation": light.saturation,
                "current_light_mode": 1 if light.mode == "rgb" else 0,
            }
        })
        await self._publish_protobuf(
            light_state_topic(settings.manager_address, light.id), payload, True
        )

    async def _publish_room_state(self, room_id: int) -> None:
        room = self._room_by_id(room_id)
        if room is None:
            return
        settings = self.config.settings
        lights = [l for l in self.config.lights if l.room_id == room_id]

        def avg(values: list[int]) -> int:
            return int(sum(values) / len(values)) if values else 0

        ceiling = [l for l in lights if l.light_type == "ceiling"]
        table = [l for l in lights if l.light_type == "table"]
        on_lights = [l for l in lights if l.state]
        page_ids = [p.id for p in self.config.pages if p.room_id == room_id and not p.is_scenes_page]

        status = pbw.build_nspanel_room_status({
            "id": room_id,
            "name": room.name,
            "average_dim_level": avg([l.brightness for l in on_lights]),
            "ceiling_lights_dim_level": avg([l.brightness for l in ceiling if l.state]),
            "table_lights_dim_level": avg([l.brightness for l in table if l.state]),
            "average_color_temperature": avg([l.color_temp for l in on_lights]),
            "ceiling_lights_color_temperature_value": avg([l.color_temp for l in ceiling if l.state]),
            "table_lights_color_temperature_value": avg([l.color_temp for l in table if l.state]),
            "num_ceiling_lights": len(ceiling),
            "num_table_lights": len(table),
            "num_ceiling_lights_on": sum(1 for l in ceiling if l.state),
            "num_table_lights_on": sum(1 for l in table if l.state),
            "entity_page_ids": page_ids,
        })
        await self._publish_protobuf(room_state_topic(settings.manager_address, room_id), status, True)

    async def _publish_entity_page(self, page_id: int) -> None:
        page = next((p for p in self.config.pages if p.id == page_id), None)
        if page is None:
            return
        settings = self.config.settings
        members = (
            [sc for sc in self.config.scenes if sc.page_id == page.id]
            if page.is_scenes_page
            else [l for l in self.config.lights if l.page_id == page.id]
        )
        members.sort(key=lambda m: m.page_slot)
        entities = []
        for member in members:
            entities.append({
                "room_view_position": member.page_slot,
                "name": member.name,
                "pco": 11 if page.is_scenes_page else 3,
                "pco2": 0 if page.is_scenes_page else 7,
                "can_save_scene": not page.is_scenes_page,
                "mqtt_state_topic": ""
                if page.is_scenes_page
                else light_state_topic(settings.manager_address, member.id),
            })
        payload = pbw.build_nspanel_room_entities_page({
            "id": page.id,
            "page_type": page.page_type,
            "header_text": "Scenes" if page.is_scenes_page else "",
            "entities": entities,
        })
        await self._publish_protobuf(
            entity_page_state_topic(settings.manager_address, page.id), payload, True
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _on_panel_command(self, msg) -> None:
        mac = mac_from_topic(msg.topic, "command")
        panel = self._panel_by_mac(mac)
        if panel is None or not panel.accepted:
            return
        try:
            command = pbw.parse_nspanel_mqttmanager_command(msg.payload)
        except Exception:  # noqa: BLE001
            return
        await self._dispatch_command(panel, command)

    async def _on_manager_command(self, msg) -> None:
        """Panels (and the web preview) register via JSON on this topic."""
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if data.get("command") == "register_request":
            mac = data.get("mac_origin") or data.get("mac_address") or data.get("mac") or ""
            if mac:
                await self._handle_register_request(mac, data)

    async def _on_relay_state(self, msg) -> None:
        state = str(msg.payload).strip().lower() in ("1", "true", "on")
        self._relay_state[msg.topic] = state
        for listener in self._relay_listeners.get(msg.topic, []):
            listener(state)

    def _register_accept_reply(self, panel: PanelConfig) -> str:
        return json.dumps({
            "command": "register_accept",
            "address": self.config.settings.manager_address,
            "port": self.config.settings.manager_port,
            "config_topic": f"nspanel/{panel.mac}/config",
        })

    async def _dispatch_command(self, panel: PanelConfig, command: dict) -> None:
        kind = command.get("kind")

        if kind == "light_command":
            for light_id in command.get("light_ids", []):
                light = self._light_by_id(light_id)
                if light is None:
                    continue
                await self._apply_light_command(
                    light,
                    {
                        "has_brightness": bool(command.get("has_brightness")),
                        "brightness": command.get("brightness", 0),
                        "has_color_temperature": bool(command.get("has_color_temperature")),
                        "color_temperature": command.get("color_temperature", 0),
                        "has_hue": bool(command.get("has_hue")),
                        "hue": command.get("hue", 0),
                        "has_saturation": bool(command.get("has_saturation")),
                        "saturation": command.get("saturation", 0),
                    },
                )
        elif kind == "toggle_entity_from_entities_page":
            page_id = command.get("entity_page_id")
            slot = command.get("entity_slot")
            # Scene activation (NSPM or HA scene)
            scene = next(
                (sc for sc in self.config.scenes if sc.page_id == page_id and sc.page_slot == slot),
                None,
            )
            if scene is not None:
                await self._activate_scene(scene, panel.room_id)
                return
            # Light toggle
            light = next(
                (
                    l
                    for l in self.config.lights
                    if l.page_id == page_id
                    and l.page_slot == slot
                ),
                None,
            )
            if light:
                await self._apply_light_command(light, None, toggle_on=not light.state)
        elif kind == "first_page_turn_on":
            await self._first_page_turn(
                panel,
                command.get("first_page_turn_on_affect_lights", 0),
                command.get("brightness_slider_value", 0),
                command.get("kelvin_slider_value", 0),
                True,
            )
        elif kind == "first_page_turn_off":
            await self._first_page_turn(
                panel,
                command.get("first_page_turn_off_affect_lights", 0),
                None,
                None,
                False,
            )
        elif kind == "save_scene_command":
            await self._save_scene(command.get("entity_page_id"), command.get("entity_slot"))
        elif kind == "thermostat_temperature_command":
            tid = command.get("thermostat_id")
            temp = command.get("temperature")
            th = next((t for t in self.config.thermostats if t.id == tid), None)
            if th is not None and th.ha_entity:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": th.ha_entity, "temperature": temp},
                )
                th.set_temperature = float(temp or 0)
                await self.async_save()
        elif kind == "thermostat_command":
            tid = command.get("thermostat_id")
            option = command.get("option", "")
            new_value = command.get("new_value", "")
            th = next((t for t in self.config.thermostats if t.id == tid), None)
            if th is not None and th.ha_entity:
                if option == "mode" or option == "hvac_mode":
                    await self.hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": th.ha_entity, "hvac_mode": new_value},
                    )
                elif option == "fan_mode":
                    await self.hass.services.async_call(
                        "climate", "set_fan_mode",
                        {"entity_id": th.ha_entity, "fan_mode": new_value},
                    )
        elif kind == "button_pressed":
            pass

        await self._publish(config_reload_topic(), "1", False)

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
        await self._publish_room_state(light.room_id)

    async def _first_page_turn(
        self, panel: PanelConfig, affect: int, brightness: int, kelvin: int, turn_on: bool
    ) -> None:
        # affect: 0=ALL 1=TABLE 2=CEILING (protobuf AffectLightsOptions)
        lights = [l for l in self.config.lights if l.room_id == panel.room_id]
        if affect == 1:
            lights = [l for l in lights if l.light_type == "table"]
        elif affect == 2:
            lights = [l for l in lights if l.light_type == "ceiling"]
        for light in lights:
            if turn_on:
                await self._apply_light_command(light, None, toggle_on=True)
                if brightness:
                    light.brightness = brightness
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {"entity_id": light.ha_entity, "brightness_pct": brightness},
                    )
            else:
                await self._apply_light_command(light, None, toggle_on=False)

    async def _save_scene(self, page_id: int, slot: int) -> None:
        scene = next(
            (s for s in self.config.scenes if s.page_id == page_id and s.page_slot == slot), None
        )
        if scene is None or scene.ha_entity:
            return
        light_states = []
        page = next((p for p in self.config.pages if p.id == page_id), None)
        room_id = page.room_id if page and page.room_id else None
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

    async def _poll_weather(self, now) -> None:
        s = self.config.settings
        if not s.location_latitude or not s.location_longitude:
            return
        try:
            lat = s.location_latitude
            lon = s.location_longitude
            temp_unit = "fahrenheit" if s.use_fahrenheit else "celsius"
            precip_unit = "inch" if s.precipitation_format == "inch" else "mm"
            wind_unit = {"kmh": "kmh", "ms": "ms", "mph": "mph", "kn": "kn"}.get(s.wind_speed_format, "kmh")
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max"
                f"&timeformat=unixtime&temperature_unit={temp_unit}&precipitation_unit={precip_unit}&wind_speed_unit={wind_unit}&timezone=auto"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("Weather fetch failed: HTTP %s", resp.status)
                        return
                    data = await resp.json()
            ICONS = {0: "sunny", 1: "partlytuner weather_day", 2: "cloudy_weather_day", 3: "overcast",
                     45: "fog", 48: "fog", 51: "rainy", 53: "rainy", 55: "rainy", 56: "sleet", 57: "sleet",
                     61: "rainy", 63: "rainy", 65: "rainy", 66: "sleet", 67: "sleet", 71: "snowy", 73: "snowy",
                     75: "snowy", 77: "snowy", 80: "rainy", 81: "rainy", 82: "rainy", 85: "snowy", 86: "snowy",
                     95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm"}
            def icon(code):
                return ICONS.get(int(code), "cloudy_weather_day")
            def fmt_temp(v):
                if s.use_fahrenheit:
                    return f"{int(round(v))}°F"
                return f"{int(round(v))}°C"
            def fmt_wind(v):
                if s.wind_speed_format == "ms":
                    return f"{v:.1f} m/s"
                if s.wind_speed_format == "mph":
                    return f"{int(round(v))} mph"
                if s.wind_speed_format == "kn":
                    return f"{int(round(v))} kn"
                return f"{int(round(v))} km/h"
            cur = data.get("current", {})
            daily = data.get("daily", {})
            from datetime import datetime, timezone
            def fmt_time(ts):
                try:
                    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M")
                except Exception:
                    return ""
            forecast_items = []
            for i in range(min(4, len(daily.get("weather_code", [])))):
                forecast_items.append({
                    "weather_icon": icon(daily["weather_code"][i]),
                    "precipitation_string": f"{precip_unit} {int(daily.get('precipitation_probability_max', [0])[i] if i < len(daily.get('precipitation_probability_max', [])) else 0)}%",
                    "temperature_maxmin_string": f"{fmt_temp(daily['temperature_2m_max'][i])}/{fmt_temp(daily['temperature_2m_min'][i])}",
                    "wind_string": fmt_wind(daily.get("wind_speed_10m_max", [0])[i] if i < len(daily.get("wind_speed_10m_max", [])) else 0),
                    "display_string": "",
                })
            payload = {
                "forecast_items": forecast_items,
                "current_weather_icon": icon(cur.get("weather_code", 0)),
                "current_temperature_string": fmt_temp(cur.get("temperature_2m", 0)),
                "current_maxmin_temperature": f"{fmt_temp((daily.get('temperature_2m_max') or [0])[0])}/{fmt_temp((daily.get('temperature_2m_min') or [0])[0])}",
                "current_wind_string": fmt_wind(cur.get("wind_speed_10m", 0)),
                "sunrise_string": fmt_time((daily.get("sunrise") or [0])[0]),
                "sunset_string": fmt_time((daily.get("sunset") or [0])[0]),
                "current_precipitation_string": f"{cur.get('precipitation', 0)} {precip_unit}",
            }
            encoded = pbw.build_nspanel_weather_update(payload)
            await self._publish(weather_topic(s.manager_address), encoded, True)
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
                elif ls.get("color_mode") == "color" and light.can_rgb:
                    light.mode = "rgb"
                    light.hue = ls.get("hue", 0)
                    light.saturation = ls.get("saturation", 0)
                    svc_data["hs_color"] = (light.hue, light.saturation)
                await self.hass.services.async_call("light", "turn_on", svc_data)
            await self._publish_light_state(light)
        page = next((p for p in self.config.pages if p.id == scene.page_id), None)
        if page and page.room_id:
            await self._publish_room_state(page.room_id)

    async def _republish_all_state(self) -> None:
        """Republish room states, entity pages, light states for all rooms."""
        for room in self.config.rooms:
            await self._publish_room_state(room.id)
        for page in self.config.pages:
            await self._publish_entity_page(page.id)
        for light in self.config.lights:
            await self._publish_light_state(light)
        for th in self.config.thermostats:
            await self._publish_thermostat_state(th)
        await self._publish_time(None)

    # ------------------------------------------------------------------
    # Time publishing
    # ------------------------------------------------------------------


    async def _publish_time(self, now) -> None:
        settings = self.config.settings
        from datetime import datetime

        current = now or datetime.now()
        time_str = (
            current.strftime("%I:%M") if settings.clock_us_style else current.strftime("%H:%M")
        )
        ampm = current.strftime("%p") if settings.clock_us_style else ""
        date_str = current.strftime(settings.date_format or "%d/%m")
        await self._publish(time_topic(settings.manager_address), time_str, True)
        await self._publish(ampm_topic(settings.manager_address), ampm, True)
        await self._publish(date_topic(settings.manager_address), date_str, True)
