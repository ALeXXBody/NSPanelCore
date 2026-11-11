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
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from google.protobuf.message import Message

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
from .protobuf import protobuf_nspanel_pb2 as pb_nspanel
from .protobuf import protobuf_nspanel_entity_pb2 as pb_entity

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

    async def _publish_protobuf(self, topic: str, message: Message, retain: bool = False) -> None:
        await self._publish(topic, message.SerializeToString(), retain)

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

        cfg = pb_nspanel.NSPanelConfig()
        cfg.name = panel.name
        cfg.default_room = panel.room_id
        cfg.default_page = panel.default_page
        cfg.screensaver_activation_timeout = panel.screensaver_activation_timeout
        cfg.min_button_push_time = panel.min_button_push_time
        cfg.button_long_press_time = panel.button_long_press_time
        cfg.special_mode_trigger_time = panel.special_mode_trigger_time
        cfg.special_mode_release_time = panel.special_mode_release_time
        cfg.screen_dim_level = panel.screen_dim_level
        cfg.screensaver_dim_level = panel.screensaver_dim_level
        cfg.screensaver_mode = panel.screensaver_mode
        cfg.show_screensaver_inside_temperature = True
        cfg.show_screensaver_outside_temperature = bool(
            self.config.settings.outside_temp_sensor_entity
        )
        cfg.clock_us_style = panel.clock_us_style
        cfg.use_fahrenheit = panel.use_fahrenheit
        cfg.is_us_panel = panel.is_us_panel
        cfg.reverse_relays = panel.reverse_relays
        cfg.relay1_default_mode = panel.relay1_default_mode
        cfg.relay2_default_mode = panel.relay2_default_mode
        cfg.temperature_calibration = panel.temperature_calibration
        cfg.button1_mode = panel.button1_mode
        cfg.button2_mode = panel.button2_mode
        cfg.optimistic_mode = panel.optimistic_mode
        cfg.raise_light_level_to_100_above = panel.raise_to_100_light_level
        cfg.nspanel_id = panel.id
        cfg.default_light_brightess = panel.default_light_brightness
        cfg.locked_to_default_room = False
        cfg.inside_temperature_sensor_mqtt_topic = panel.inside_temperature_sensor_topic

        for rid in room_ids:
            info = cfg.room_infos.add()
            info.room_id = rid
            for p in pages:
                if p.room_id == rid:
                    if p.is_scenes_page:
                        info.scene_page_ids.append(p.id)
                    else:
                        info.entity_page_ids.append(p.id)

        for page in global_scene_page_ids:
            cfg.global_scene_entity_page_ids.append(page)

        await self._publish_protobuf(panel_topic(panel.mac, "command"), cfg, True)
        _LOGGER.info("Sent NSPanelConfig to panel %s (%s)", panel.name, panel.mac)

    async def _on_panel_status_report(self, msg) -> None:
        mac = mac_from_topic(msg.topic, "status_report")
        panel = self._panel_by_mac(mac)
        if not panel:
            return
        try:
            report = pb_nspanel.NSPanelStatusReport()
            report.ParseFromString(msg.payload)
        except Exception:  # noqa: BLE001
            return
        was_online = panel.online
        panel.online = report.nspanel_state == 0
        panel.firmware_md5 = report.md5_firmware
        panel.tft_md5 = report.md5_tft_gui
        panel.littlefs_md5 = report.md5_littlefs
        await self.async_save()
        if panel.online != was_online:
            for listener in self._new_panel_listeners:
                listener()
        for listener in self._report_listeners:
            listener(panel.mac, report)

    def add_new_panel_listener(self, listener) -> None:
        """Register a callback fired when a panel's presence changes."""
        self._new_panel_listeners.append(listener)

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
        state = pb_entity.NSPanelEntityState(
            light=pb_entity.NSPanelEntityState.Light(
                light_id=light.id,
                name=light.name,
                state=light.state,
                can_color_temp=light.can_color_temperature,
                can_color=light.can_rgb,
                brightness=light.brightness,
                hue=light.hue,
                saturation=light.saturation,
                current_light_mode=pb_entity.NSPanelEntityState.Light.RGB
                if light.mode == "rgb"
                else pb_entity.NSPanelEntityState.Light.COLOR_TEMP,
            )
        )
        settings = self.config.settings
        kelvin_pct = (
            (light.color_temp - settings.color_temp_min)
            / (settings.color_temp_max - settings.color_temp_min)
            * 100
        )
        if settings.reverse_color_temp:
            kelvin_pct = 100 - kelvin_pct
        state.light.color_temp = int(kelvin_pct)
        await self._publish_protobuf(
            light_state_topic(settings.manager_address, light.id), state, True
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

        status = pb_nspanel.NSPanelRoomStatus(
            id=room_id,
            name=room.name,
            average_dim_level=avg([l.brightness for l in on_lights]),
            ceiling_lights_dim_level=avg([l.brightness for l in ceiling if l.state]),
            table_lights_dim_level=avg([l.brightness for l in table if l.state]),
            average_color_temperature=avg([l.color_temp for l in on_lights]),
            ceiling_lights_color_temperature_value=avg([l.color_temp for l in ceiling if l.state]),
            table_lights_color_temperature_value=avg([l.color_temp for l in table if l.state]),
            num_ceiling_lights=len(ceiling),
            num_table_lights=len(table),
            num_ceiling_lights_on=sum(1 for l in ceiling if l.state),
            num_table_lights_on=sum(1 for l in table if l.state),
        )
        page_ids = [p.id for p in self.config.pages if p.room_id == room_id and not p.is_scenes_page]
        status.entity_page_ids.extend(page_ids)

        await self._publish_protobuf(room_state_topic(settings.manager_address, room_id), status, True)

    async def _publish_entity_page(self, page_id: int) -> None:
        page = next((p for p in self.config.pages if p.id == page_id), None)
        if page is None:
            return
        settings = self.config.settings
        page_msg = pb_nspanel.NSPanelRoomEntitiesPage(
            id=page.id,
            page_type=page.page_type,
            header_text="Scenes" if page.is_scenes_page else "",
        )
        members = (
            [s for s in self.config.scenes if s.page_id == page.id]
            if page.is_scenes_page
            else [l for l in self.config.lights if l.page_id == page.id]
        )
        members.sort(key=lambda m: m.page_slot)
        for member in members:
            slot = page_msg.entities.add()
            slot.room_view_position = member.page_slot
            if page.is_scenes_page:
                slot.name = member.name  # type: ignore[union-attr]
                slot.pco = 11  # scenes slot PCO (panel requests activate)
            else:
                slot.name = member.name
                slot.pco = 3  # light toggle slot
                slot.pco2 = 7  # brightness slider
                slot.can_save_scene = True
                slot.mqtt_state_topic = light_state_topic(
                    settings.manager_address, member.id  # type: ignore[union-attr]
                )
        await self._publish_protobuf(
            entity_page_state_topic(settings.manager_address, page.id), page_msg, True
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _on_panel_command(self, msg) -> None:
        mac = mac_from_topic(msg.topic, "command")
        panel = self._panel_by_mac(mac)
        if panel is None or not panel.accepted:
            return
        command = pb_nspanel.NSPanelMQTTManagerCommand()
        try:
            command.ParseFromString(msg.payload)
        except Exception:  # noqa: BLE001
            return
        await self._dispatch_command(panel, command)

    async def _on_manager_command(self, msg) -> None:
        # Browser/register requests arrive as JSON on this topic (web UI flow).
        return

    async def _dispatch_command(self, panel: PanelConfig, command) -> None:
        kind = command.WhichOneof("CommandData")

        if kind == "light_command":
            lc = command.light_command
            for light_id in lc.light_ids:
                light = self._light_by_id(light_id)
                if light is None:
                    continue
                await self._apply_light_command(light, lc)
        elif kind == "toggle_entity_from_entities_page":
            toggle = command.toggle_entity_from_entities_page
            light = next(
                (
                    l
                    for l in self.config.lights
                    if l.page_id == toggle.entity_page_id and l.page_slot == toggle.entity_slot
                ),
                None,
            )
            if light:
                await self._apply_light_command(
                    light, None, toggle_on=not light.state
                )
        elif kind == "first_page_turn_on":
            req = command.first_page_turn_on
            await self._first_page_turn(panel, req.affect_lights, req.brightness_slider_value, req.kelvin_slider_value, True)
        elif kind == "first_page_turn_off":
            req = command.first_page_turn_off
            await self._first_page_turn(panel, req.affect_lights, None, None, False)
        elif kind == "save_scene_command":
            save = command.save_scene_command
            await self._save_scene(save.entity_page_id, save.entity_slot)
        elif kind == "button_pressed":
            # FOLLOW-mode buttons are handled by HA entities created by the
            # switch platform; NOTIFY handled in that platform too.
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
