"""NSPanel Core manager — the integration's core.

Ports the external behavior of the C++ MQTT bridge onto HA's event bus:
- Panel registration (JSON status -> register_accept -> NSPanelConfig protobuf)
- Light state machines driven by HA state events (no WebSocket client needed)
- HA service calls for light commands (same semantics incl. optimistic mode)
- Room aggregation and NSPanelRoomStatus protobuf publication
- Command routing for NSPanelMQTTManagerCommand
- Minute-aligned time/date publishing
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from dataclasses import asdict
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
    all_rooms_status_topic,
    time_topic,
    date_topic,
    ampm_topic,
    status_topic,
    config_reload_topic,
)
from .models import IntegrationConfig, LightConfig, PanelConfig
from .panel_pb import messages as pbw

_LOGGER = logging.getLogger(__name__)


def mac_from_topic(topic: str, suffix: str) -> str:
    """Extract the MAC part from 'nspanel/<mac>/<suffix>'."""
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
        self._time_listener = None
        self._new_panel_listeners: list = []
        self._report_listeners: list = []
        self._relay_listeners: dict[str, list] = {}
        self._relay_state: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        data = await self._store.async_load()
        self.config = IntegrationConfig.from_dict(data or {})

        # Register the management dashboard + API and the sidebar panel.
        from .dashboard import async_register_views

        async_register_views(self.hass, self.entry.entry_id)

        await mqtt.async_subscribe(self.hass, TOPIC_PANEL_STATUS, self._on_panel_status)
        await mqtt.async_subscribe(self.hass, TOPIC_PANEL_COMMAND, self._on_panel_command)
        await mqtt.async_subscribe(self.hass, TOPIC_PANEL_STATUS_REPORT, self._on_panel_status_report)
        await mqtt.async_subscribe(self.hass, TOPIC_MANAGER_COMMAND, self._on_manager_command)
        await mqtt.async_subscribe(self.hass, "nspanel/+/relay1_state", self._on_relay_state)
        await mqtt.async_subscribe(self.hass, "nspanel/+/relay2_state", self._on_relay_state)

        # Track HA state for every mapped light entity.
        entity_ids = [l.ha_entity for l in self.config.lights if l.ha_entity]
        if entity_ids:
            self._unsub.append(
                async_track_state_change_event(self.hass, entity_ids, self._on_light_state_event)
            )

        # Minute-aligned time publishing.
        self._unsub.append(async_track_time_interval(self.hass, self._publish_time, timedelta(seconds=60)))

        # Publish retained "manager online" status.
        await self._publish_manager_status()

    async def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub = []

    async def apply_settings(self, user_input: dict) -> None:
        s = self.config.settings
        for key, value in user_input.items():
            if hasattr(s, key):
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

    async def _publish_protobuf(self, topic: str, message: bytes, retain: bool = False) -> None:
        await self._publish(topic, message, retain)

    async def _publish_manager_status(self) -> None:
        await self._publish(
            status_topic(self.config.settings.manager_address),
            json.dumps({"state": "online", "version": "core-integration"}),
            True,
        )

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

    async def _handle_register_request(self, mac: str, data: dict) -> None:
        panel = self._panel_by_mac(mac)
        if panel is None:
            friendly = data.get("friendly_name", f"NSPanel {mac[-4:].upper()}")
            panel = PanelConfig(
                id=self.config.next_id_for("panel"),
                mac=mac,
                name=friendly,
                model=data.get("model", "eu"),
            )
            self.config.panels.append(panel)
            await self.async_save()
            _LOGGER.info("New panel registered: %s (%s)", friendly, mac)

        if panel.denied:
            return
        panel.accepted = True

        accept = {
            "address": self.config.settings.manager_address,
            "config_topic": f"nspanel/{mac}/command",
            "accepted": True,
        }
        await self._publish(
            panel_topic(mac, "command"),
            base64.b64encode(json.dumps(accept).encode()).decode(),
            True,
        )
        await self._send_panel_config(panel)

    async def _send_panel_config(self, panel: PanelConfig) -> None:
        """Build and send the NSPanelConfig protobuf for a panel."""
        rooms = self.config.rooms
        room_ids = panel.rooms or [r.id for r in rooms]
        pages = [p for p in self.config.pages if p.room_id == panel.room_id]
        global_scene_page_ids = [
            p.id for p in self.config.pages if p.room_id is None and p.is_scenes_page
        ]

        pages = [p for p in self.config.pages if p.room_id == panel.room_id]
        global_scene_page_ids = [
            p.id for p in self.config.pages if p.room_id is None and p.is_scenes_page
        ]
        room_ids = panel.rooms or [r.id for r in rooms]

        config_payload = {
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
            for p in pages:
                if p.room_id == rid:
                    if p.is_scenes_page:
                        info["scene_page_ids"].append(p.id)
                    else:
                        info["entity_page_ids"].append(p.id)
            config_payload["room_infos"].append(info)

        cfg = pbw.build_nspanel_config(config_payload)
        await self._publish_protobuf(panel_topic(panel.mac, "command"), cfg, True)
        _LOGGER.info("Sent NSPanelConfig to panel %s (%s)", panel.name, panel.mac)

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

    def add_new_panel_listener(self, listener) -> None:
        """Register a callback fired when a panel's presence changes."""
        self._new_panel_listeners.append(listener)


def asdict_panel(panel):
    from dataclasses import asdict

    return asdict(panel)

    def add_report_listener(self, listener) -> None:
        """Register a callback fired on every NSPanelStatusReport(mac, report)."""
        self._report_listeners.append(listener)

    def add_relay_listener(self, mac: str, relay: int, listener) -> callable:
        """Register a callback fired when a relay state changes. Returns an
        unsubscribe callable (for entry.async_on_unload)."""
        topic = f"nspanel/{mac}/relay{relay}_state"
        self._relay_listeners.setdefault(topic, []).append(listener)

        def _unsubscribe() -> None:
            self._relay_listeners.get(topic, []).remove(listener)

        return _unsubscribe

    def panel_report_listeners(self) -> list:
        return list(self._new_panel_listeners)

    def light_config(self, light_id: int) -> LightConfig | None:
        return self._light_by_id(light_id)

    def panels(self) -> list[PanelConfig]:
        return list(self.config.panels)

    def pages(self) -> list:
        return list(self.config.pages)

    def _panel_by_mac(self, mac: str) -> PanelConfig | None:
        for panel in self.config.panels:
            if panel.mac == mac:
                return panel
        return None

    async def _on_relay_state(self, msg) -> None:
        state = msg.payload in ("1", "true", "True", "on")
        self._relay_state[msg.topic] = state
        for listener in self._relay_listeners.get(msg.topic, []):
            listener(state)

    def relay_state(self, topic: str) -> bool:
        return self._relay_state.get(topic, False)

    # ------------------------------------------------------------------
    # Dashboard CRUD (used by the management UI)
    # ------------------------------------------------------------------

    async def add_room(self, name: str) -> None:
        from .models import RoomConfig

        room = RoomConfig(id=self.config.next_id_for("room"), name=name)
        self.config.rooms.append(room)
        page = next(
            (
                p
                for p in self.config.pages
                if p.room_id == room.id and not p.is_scenes_page
            ),
            None,
        )
        if page is None:
            from .models import EntityPageConfig

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
        # Track the HA entity and push the current state to the panel.
        self._unsub.append(
            async_track_state_change_event(self.hass, [ha_entity], self._on_light_state_event)
        )
        state = self.hass.states.get(ha_entity)
        if state is not None:
            event_data = {
                "entity_id": ha_entity,
                "old_state": None,
                "new_state": state,
            }
            await self._on_light_state_event(
                type("E", (Event,), {"data": event_data})(None)  # minimal event shim
            )
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
        if panel.accepted:
            await self._send_panel_config(panel)

    async def remove_panel(self, panel_id: int) -> None:
        self.config.panels = [p for p in self.config.panels if p.id != panel_id]
        await self.async_save()

    def export_state(self) -> dict:
        return self.config.to_dict() | {
            "panels": [asdict_panel(p) for p in self.config.panels],
        }

    def add_new_panel_listener(self, listener) -> None:
        """Register a callback fired when a panel's presence changes."""
        self._new_panel_listeners.append(listener)

    async def set_relay(self, mac: str, relay: int, state: bool) -> None:
        await self._publish(panel_topic(mac, f"relay{relay}_cmd"), "1" if state else "0")

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
            if hs and (int(hs[0]) != light.hue or int(hs[1]) != light.saturation):
                changed = True
                light.hue = int(hs[0])
                light.saturation = int(hs[1])

        await self.async_save()
        if changed:
            await self._publish_light_state(light)
            await self._publish_room_state(light.room_id)

    async def _publish_light_state(self, light: LightConfig) -> None:
        state = pbw.build_nspanel_entity_state_light({
            "light": {
                "light_id": light.id,
                "name": light.name,
                "state": light.state,
                "can_color_temp": light.can_color_temperature,
                "can_color": light.can_rgb,
                "brightness": light.brightness,
                "hue": light.hue,
                "saturation": light.saturation,
                "current_light_mode": 1 if light.mode == "rgb" else 0,
            }
        })
        settings = self.config.settings
        kelvin_pct = (
            (light.color_temp - settings.color_temp_min)
            / (settings.color_temp_max - settings.color_temp_min)
            * 100
        )
        if settings.reverse_color_temp:
            kelvin_pct = 100 - kelvin_pct
        # color_temp field is a percentage of the kelvin range
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

        ceiling = [l for l in lights if l.light_type == "ceiling"]
        table = [l for l in lights if l.light_type == "table"]
        on_lights = [l for l in lights if l.state]

        def avg(values: list[int]) -> int:
            return int(sum(values) / len(values)) if values else 0

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
        entities = []
        members = (
            [sc for sc in self.config.scenes if sc.page_id == page.id]
            if page.is_scenes_page
            else [l for l in self.config.lights if l.page_id == page.id]
        )
        members.sort(key=lambda m: m.page_slot)
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
        # Browser/register requests arrive as JSON on this topic (web UI flow).
        return

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
            toggle = command
            light = next(
                (
                    l
                    for l in self.config.lights
                    if l.page_id == toggle.get("entity_page_id")
                    and l.page_slot == toggle.get("entity_slot")
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
        elif kind == "button_pressed":
            # FOLLOW/NOTIFY-mode buttons are handled by the switch platform.
            pass

        await self._publish(config_reload_topic(), "1", False)

    async def _apply_light_command(self, light: LightConfig, lc, toggle_on: bool | None = None) -> None:
        """Translate a panel light command into HA service calls — the same
        service-data semantics as the C++ HomeAssistantLight."""
        settings = self.config.settings
        domain = "light"
        service = None
        service_data: dict[str, Any] = {}

        if toggle_on is not None:
            light.state = toggle_on
            if not toggle_on:
                service = "turn_off"
        else:
            if lc.has_brightness:
                light.brightness = min(max(lc.brightness, 0), 100)
            if lc.has_color_temperature:
                light.mode = "default"
                light.color_temp = lc.color_temperature
            if lc.has_hue or lc.has_saturation:
                light.mode = "rgb"
                light.hue = lc.hue
                light.saturation = lc.saturation
            if lc.has_brightness:
                light.state = lc.brightness > 0
                if not light.state:
                    service = "turn_off"
            if light.state or service is None:
                service = "turn_on"

        if service == "turn_on":
            service_data["brightness_pct"] = light.brightness
            if light.mode == "default" and light.can_color_temperature:
                kelvin = light.color_temp or settings.color_temp_min
                service_data["color_temp_kelvin"] = kelvin
            elif light.mode == "rgb" and light.can_rgb:
                service_data["hs_color"] = (light.hue, light.saturation)
        elif service == "turn_off":
            pass

        await self.hass.services.async_call(domain, service, {"entity_id": light.ha_entity, **service_data})
        await self._publish_light_state(light)
        await self._publish_room_state(light.room_id)

    async def _first_page_turn(self, panel: PanelConfig, affect: int, brightness: int, kelvin: int, turn_on: bool) -> None:
        # affect: 0=ALL 1=TABLE 2=CEILING (protobuf AffectLightsOptions)
        lights = [l for l in self.config.lights if l.room_id == panel.room_id]
        if affect == 1:
            lights = [l for l in lights if l.light_type == "table"]
        elif affect == 2:
            lights = [l for l in lights if l.light_type == "ceiling"]
        for light in lights:
            if turn_on:
                brightness = brightness or self.config.settings.light_turn_on_brightness or light.brightness or 100
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
            return  # HA-native scenes cannot be saved from the panel
        light_states = []
        for light in self.config.lights:
            if light.room_id != (self._room_by_id(scene.page_id) and 0):
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

    # ------------------------------------------------------------------
    # Time publishing
    # ------------------------------------------------------------------

    async def _publish_time(self, now) -> None:
        settings = self.config.settings
        current = now + timedelta(0)
        time_str = current.strftime("%I:%M") if settings.clock_us_style else current.strftime("%H:%M")
        ampm = current.strftime("%p") if settings.clock_us_style else ""
        date_str = current.strftime("%d/%m")
        await self._publish(time_topic(settings.manager_address), time_str, True)
        await self._publish(ampm_topic(settings.manager_address), ampm, True)
        await self._publish(date_topic(settings.manager_address), date_str, True)
