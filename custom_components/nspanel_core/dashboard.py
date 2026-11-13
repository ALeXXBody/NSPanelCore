"""Serves the ORIGINAL manager UI (converted templates) over HA's HTTP server.

- /nspanel_core          — the NSPanels page (original markup, live via STOMP)
- /nspanel_core/htmx/*   — htmx partials + panel actions (accept/deny/delete)
- /nspanel_core/static/* — the original static assets
- /nspanel_core/ws       — the STOMP WebSocket endpoint
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib

from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)



class _RoomView:
    """Template-friendly room object (Django model replacement)."""
    def __init__(self, room, nspanels=None, entities=None):
        self.id = room.id if hasattr(room, "id") else room["id"]
        self.friendly_name = room.name if hasattr(room, "name") else room.get("name", "")
        self.name = self.friendly_name
        self._nspanels = nspanels or []
        self._entities = entities or []

    class _QS:
        def __init__(self, items):
            self._items = items
            self.all = items  # Django template calls .all (as attribute, not method)

    @property
    def nspanel_set(self):
        return self._QS(self._nspanels)

    @property
    def entity_set(self):
        return self._QS(self._entities)


URL_BASE = "/nspanel_core"
# The UI lives on its own path so /nspanel_core stays reserved for HA's SPA
# (panel_custom owns that route). Serving the UI at /nspanel_core shadowed the
# SPA, so a browser refresh loaded the UI top-level and the old redirect
# script bounced it to "/" — the panel then appeared missing/blank.
UI_PATH = f"{URL_BASE}/ui"

_TEMPLATE_CACHE = {}

# Set by the manager from manifest.json (read in the executor) at startup.
_DASHBOARD_VERSION = "v0.0.0"

UI_DIR = pathlib.Path(__file__).parent / "ui"
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"


def _jinja_env():
    """Module-level Jinja environment (built once, reused every render)."""
    import jinja2

    import json as _json
    import base64 as _b64
    import json as _json2

    def _RC(component_name, **props):
        # Convert undefined/None values to empty strings for JSON serialization
        clean = {}
        for k, v in props.items():
            if v is None or (hasattr(v, "_undefined_name") or hasattr(v, "__class__") and "Undefined" in type(v).__name__):
                clean[k] = ""
            else:
                try:
                    _json.dumps(v)
                    clean[k] = v
                except (TypeError, ValueError):
                    clean[k] = str(v)
        props_json = _json.dumps(clean)
        unique_id = f"react-{component_name}-{id(props)}"
        return f"<div id='{unique_id}' data-react-component='{component_name}' data-react-props='{props_json}'></div>"

    def _jsonify(value):
        try:
            return _json2.dumps(value)
        except Exception:
            return str(value)

    def _base64_encode(value):
        return _b64.b64encode(str(value).encode()).decode()

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    env.globals["RC"] = _RC
    env.filters["jsonify"] = _jsonify
    env.filters["base64_encode"] = _base64_encode
    return env


_JINJA_ENV = None


def _get_env():
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = _jinja_env()
    return _JINJA_ENV


def _warm_template_cache() -> None:
    """Pre-compile every template (runs in the executor at startup).

    First render of each template does disk I/O; doing it here keeps all
    file reads off the event loop.
    """
    env = _get_env()
    for path in TEMPLATES_DIR.rglob("*.html"):
        name = str(path.relative_to(TEMPLATES_DIR))
        try:
            _TEMPLATE_CACHE[name] = env.get_template(name)
        except Exception:  # noqa: BLE001 — a single bad template must not block startup
            _LOGGER.exception("Failed to pre-compile template %s", name)


def _render(template_name: str, **context) -> str:
    env = _get_env()
    # Cache templates to avoid blocking I/O in the event loop
    if template_name not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[template_name] = env.get_template(template_name)
    template = _TEMPLATE_CACHE[template_name]
    context.setdefault("notifications", [])
    context.setdefault("version", _DASHBOARD_VERSION)
    context.setdefault("has_unread_messages", False)
    context.setdefault("mqtt_password", "")
    context.setdefault("home_assistant_token", "")
    context.setdefault("mqtt_server", "")
    context.setdefault("mqtt_port", 1883)
    context.setdefault("mqtt_username", "")
    context.setdefault("room", None)
    context.setdefault("enabled_themes", {"nspmwip": "NSPanel Core (dark)"} )
    context.setdefault("theme", "nspmwip")
    context.setdefault("current_theme", "nspmwip")
    context.setdefault("theme_mode", "dark")
    context.setdefault("ingress_path", "")
    context.setdefault("request", type("R", (), {"path": context.get("current_path", "/")})())
    return template.render(**context)


def _manager(request) -> Any:
    hass: HomeAssistant = request.app["hass"]
    entry_id = hass.data.get(f"{DOMAIN}_entry_id")
    if entry_id is None and DOMAIN in hass.data and hass.data[DOMAIN]:
        entry_id = next(iter(hass.data[DOMAIN]))
    if entry_id is None:
        raise RuntimeError("NSPanel Core not initialized")
    return hass.data[DOMAIN][entry_id]


def _panels_context(manager) -> list[dict]:
    out = []
    for panel in manager.panels():
        out.append({
            "data": {
                "id": panel.id,
                "mac_address": panel.mac,
                "friendly_name": panel.name,
                "accepted": panel.accepted,
                "denied": panel.denied,
                "ip_address": "",
                "fw_version": panel.version,
            },
        })
    return out


class MainPageView(HomeAssistantView):
    """The NSPanels page — original templates, live via STOMP."""

    url = UI_PATH
    name = "nspanel_core:page"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        html = _render(
            "index_htmx.html",
            nspanels=_panels_context(manager),
            manager_address=manager.config.settings.manager_address,
            temperature_unit="celsius",
            has_unread_messages=any(not m.read for m in manager.config.messages),
        )
        return web.Response(text=html, content_type="text/html")


class HtmxNspanelsSectionView(HomeAssistantView):
    url = f"{URL_BASE}/htmx/nspanels"
    name = "nspanel_core:htmx:nspanels"
    requires_auth = True

    async def get(self, request, **kwargs):
        manager = _manager(request)
        html = _render(
            "index_htmx_nspanels_section.html",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class PanelActionView(HomeAssistantView):
    """Accept/deny/delete a panel — returns the refreshed section (htmx)."""

    url = "/nspanel_core/api/panel/{panel_id}/{action}"
    name = "nspanel_core:api:panel_action"
    requires_auth = True

    async def post(self, request, **kwargs):
        return await self._act(request)

    async def delete(self, request, **kwargs):
        return await self._act(request)

    async def _act(self, request):
        manager = _manager(request)
        try:
            panel_id = int(request.match_info["panel_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(text="Bad panel id", status=400)
        action = request.match_info.get("action", "")
        if action not in ("accept", "deny", "delete", "update_firmware", "update_tft"):
            return web.Response(text="Unknown action", status=400)
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(text="Panel not found", status=404)
        if panel is not None:
            if action == "accept":
                panel.accepted = True
                panel.denied = False
                await manager.async_save()
                await manager._send_panel_config(panel)
                await manager._publish_panel_status(panel, "online")
                manager.notify_panels_changed()
            elif action == "deny":
                panel.denied = True
                panel.accepted = False
                await manager.async_save()
                await manager._publish_panel_status(panel, "offline")
                manager.notify_panels_changed()
            elif action == "delete":
                manager.config.panels.remove(panel)
                await manager.async_save()
                await manager._publish_panel_status(panel, "offline")
                manager.notify_panels_changed()
            elif action in ("update_firmware", "update_tft"):
                if not panel.accepted or panel.denied:
                    return web.Response(text="Panel not accepted", status=409)
                from .const import panel_mqtt_topic

                command = "firmware_update" if action == "update_firmware" else "tft_update"
                # Same OTA path the auto-trigger uses: MQTT command, panel
                # downloads over HTTP and flashes itself.
                manager._last_ota_trigger.pop(panel.mac, None)
                await manager._publish(
                    panel_mqtt_topic(panel.wifi_hostname or panel.name, "command"),
                    json.dumps({"command": command}),
                )
        referer = request.headers.get("Referer", "") or ""
        if "denied" in referer and action == "accept":
            # Denied page swaps the row itself: empty body removes it.
            return web.Response(text="", content_type="text/html")
        # Index page buttons target the section wrapper: full grid replaces grid.
        html = _render(
            "index_htmx_nspanels_section.html",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class PlaceholderPageView(HomeAssistantView):
    """Pages still being ported — served with the original shell so the app
    never falls back to the HA frontend (which caused the 'doubled page')."""

    url = f"{URL_BASE}/coming-soon"
    name = "nspanel_core:placeholder"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        page = request.path.rsplit("/", 1)[-1]
        titles = {
            "rooms": "Rooms",
            "relay_groups": "Relay/Light groups",
            "global_scenes": "Global scenes",
            "weather_and_time": "Weather & Time",
            "denied_nspanels": "Denied NSPanels",
            "settings": "Settings",
            "manager_settings": "Manager settings",
        }
        html = _render(
            "index_shell.html",
            page_title=titles.get(page, page),
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class EditPanelView(HomeAssistantView):
    """The ORIGINAL panel settings page (edit_nspanel template)."""

    url = f"{URL_BASE}/edit/{{panel_id}}"
    name = "nspanel_core:edit"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        panel_id = int(request.match_info["panel_id"])
        panel = next((p for p in manager.panels() if p.id == panel_id), None)
        if panel is None:
            html = _render("index_shell.html", page_title="Panel not found", nspanels=[])
            return web.Response(text=html, content_type="text/html")
        # Context shaped like the Django view: panel_info wrapper + settings
        from dataclasses import asdict

        panel_dict = asdict(panel)
        panel_dict["ip_address"] = ""
        panel_dict["friendly_name"] = panel.name  # Django model used friendly_name
        panel_dict["mac_address"] = panel.mac  # MAC shown in settings header
        panel_dict["room"] = {"id": panel.room_id}  # Django model used panel.room (FK)
        # Django FKs not used in integration; provide stubs so template attribute access is safe.
        class _Stub:
            room = None
        panel_dict["button1_detached_mode_entity"] = _Stub()
        panel_dict["button2_detached_mode_entity"] = _Stub()
        # Detached-mode room selects: pre-select the room of the stored light.
        _light_room = {l.id: l.room_id for l in manager.config.lights}
        panel_dict["button1_detached_room"] = _light_room.get(
            panel.button1_detached_light, panel.room_id)
        panel_dict["button2_detached_room"] = _light_room.get(
            panel.button2_detached_light, panel.room_id)
        panel_info = {"data": panel_dict}
        nspanel = {"data": panel_dict}
        room_views = []
        for r in manager.config.rooms:
            r_nspanels = [p for p in manager.config.panels if p.room_id == r.id]
            r_entities = [l for l in manager.config.lights if l.room_id == r.id]
            rv = _RoomView(r, nspanels=r_nspanels, entities=r_entities)
            # make nspanels template-friendly (friendly_name)
            rv._nspanels = [type("P", (), {"friendly_name": p.name}) for p in r_nspanels]
            rv._entities = [type("E", (), {"friendly_name": e.name}) for e in r_entities]
            room_views.append(rv)
        rooms = room_views
        lights = [
            {"id": l.id, "name": l.name, "ha_entity": l.ha_entity, "room_id": l.room_id}
            for l in manager.config.lights
        ]
        settings_ctx = dict(panel_dict)
        settings_ctx["selected_tft"] = ""
        settings_ctx["us_panel_orientation"] = panel.us_panel_orientation or ""
        html = _render(
            "edit_nspanel.html",
            panel_info=panel_info,
            nspanel=nspanel,
            settings=settings_ctx,
            rooms=rooms,
            lights=lights,
            page_title=f"{panel.name} — settings",
            temperature_unit="celsius",
            current_temperature=0,
            current_humidity=0,
            current_pressure=0,
            current_wifi_signal_strength=0,
            current_ram_usage=0,
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class SavePanelSettingsView(HomeAssistantView):
    url = f"{URL_BASE}/api/panel_save/{{panel_id}}"
    name = "nspanel_core:api:panel_save"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        try:
            panel_id = int(request.match_info["panel_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(text="Bad panel id", status=400)
        form = await request.post()
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(text="Panel not found", status=404)
        field_map = {
            "friendly_name": ("name", str),
            "name": ("name", str),
            "button1_mode": ("button1_mode", int),
            "button2_mode": ("button2_mode", int),
            "button1_custom_mqtt_topic": ("button1_mqtt_topic", str),
            "button1_custom_mqtt_payload": ("button1_mqtt_payload", str),
            "button2_custom_mqtt_topic": ("button2_mqtt_topic", str),
            "button2_custom_mqtt_payload": ("button2_mqtt_payload", str),
            "screensaver_mode": ("screensaver_mode", int),
            "screensaver_activation_timeout": ("screensaver_activation_timeout", int),
            "min_button_push_time": ("min_button_push_time", int),
            "button_long_press_time": ("button_long_press_time", int),
            "special_mode_trigger_time": ("special_mode_trigger_time", int),
            "special_mode_release_time": ("special_mode_release_time", int),
            "screen_dim_level": ("screen_dim_level", int),
            "screensaver_dim_level": ("screensaver_dim_level", int),
            "temperature_calibration": ("temperature_calibration", float),
            "default_page": ("default_page", int),
            "default_light_brightness": ("default_light_brightness", int),
        }
        _SCREENSAVER_MODES = (
            "with_background", "without_background",
            "datetime_with_background", "datetime_without_background",
            "no_screensaver", "global",
        )
        for form_key, (attr, typ) in field_map.items():
            if form_key in form:
                try:
                    setattr(panel, attr, typ(form[form_key]))
                except (ValueError, TypeError):
                    pass
        for mode_attr in ("button1_mode", "button2_mode"):
            try:
                v = int(getattr(panel, mode_attr, 0))
            except (ValueError, TypeError):
                v = 0
            setattr(panel, mode_attr, min(max(v, 0), 3))
        def _parse_bool_strict(raw) -> bool | None:
            if isinstance(raw, bool):
                return raw
            s = str(raw).strip().lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off"):
                return False
            return None
        # Radio groups post "True"/"False" strings (one option always checked):
        # presence-check would force True. Parse the value instead.
        for radio_bool in ("reverse_relays", "relay1_default_mode", "relay2_default_mode",
                           "lock_to_default_room", "relay1_is_light", "relay2_is_light"):
            if radio_bool in form:
                b = _parse_bool_strict(form[radio_bool])
                if b is not None:
                    setattr(panel, radio_bool, b)
        # Checkboxes: presence = checked. (clock_us_style/use_fahrenheit/
        # optimistic_mode have no controls on this form — never touch them
        # here, or every save would wipe a True back to False.)
        for flag in ("show_home_scenes", "show_home_ceiling",
                     "show_home_table", "show_home_kelvin"):
            panel.__setattr__(flag, flag in form)
        if "screensaver_mode" in form:
            sm = str(form["screensaver_mode"]).strip()
            if sm in _SCREENSAVER_MODES:
                panel.screensaver_mode = sm
            else:
                return web.Response(text="Bad screensaver_mode", status=422)
        # Panel type select maps to the is_us_panel model flag + orientation.
        if "panel_type" in form:
            pt = str(form["panel_type"]).strip().lower()
            if pt == "eu":
                panel.is_us_panel = False
                panel.us_panel_orientation = ""
            elif pt in ("us_vertical", "us_horizontal", "us_horizontal_mirrored"):
                panel.is_us_panel = True
                panel.us_panel_orientation = pt[3:]
            else:
                return web.Response(text="Bad panel_type", status=422)
        if "rooms" in form:
            try:
                selected = [int(v) for v in form.getall("rooms")]
            except (ValueError, TypeError):
                return web.Response(text="Bad rooms: must be room ids", status=400)
            valid_ids = {r.id for r in manager.config.rooms}
            if any(v not in valid_ids for v in selected):
                return web.Response(text="Unknown room id", status=400)
            # Empty selection = show every room (matches the config builder
            # fallback); storing it keeps the panel on "all rooms".
            panel.rooms = sorted(set(selected))
        # Detached-mode light: the firmware toggles a panel light by its
        # LightConfig.id (button1_detached_light in the panel JSON). The form
        # posts the select value; anything that is not 0 or a known light
        # id is rejected instead of silently stored.
        light_ids = {l.id for l in manager.config.lights}
        for key in ("button1_detached_light", "button2_detached_light"):
            form_key = "button1_detached_mode_light" if key == "button1_detached_light" else "button2_detached_mode_light"
            if form_key in form:
                try:
                    lid = int(form[form_key])
                except (ValueError, TypeError):
                    return web.Response(text=f"Bad {form_key}: must be a light id", status=422)
                if lid != 0 and lid not in light_ids:
                    return web.Response(text=f"Unknown light id: {lid}", status=404)
                setattr(panel, key, lid)
        if "room_id" in form:
            try:
                room_id = int(form["room_id"])
            except (ValueError, TypeError):
                return web.Response(text="Bad room id", status=400)
            if manager._room_by_id(room_id) is None:
                return web.Response(text="Unknown room", status=404)
            panel.room_id = room_id
        await manager.async_save()
        await manager._send_panel_config(panel)
        manager.notify_panels_changed()
        return _redirect(request, UI_PATH)


class GlobalScenesView(HomeAssistantView):
    url = f"{URL_BASE}/global_scenes"
    name = "nspanel_core:global_scenes"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        scenes_ctx = [
            {"id": s.id, "name": s.name, "ha_entity": s.ha_entity, "page_id": s.page_id}
            for s in manager.config.scenes
        ]
        html = _render(
            "global_scenes.html",
            scenes=scenes_ctx,
            page_title="Global scenes",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class RelayGroupsView(HomeAssistantView):
    url = f"{URL_BASE}/relay_groups"
    name = "nspanel_core:relay_groups"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        panels_by_mac = {p.mac: p for p in manager.config.panels}
        groups = []
        for g in manager.config.relay_groups:
            members = []
            for b in g.bindings or []:
                p = panels_by_mac.get(b.get("panel_mac", ""))
                members.append({
                    "panel_name": p.name if p else b.get("panel_mac", "?"),
                    "relay_num": b.get("relay_num", 1),
                })
            groups.append({"id": g.id, "name": g.name, "members": members})
        html = _render(
            "relay_groups.html",
            relay_groups=groups,
            page_title="Relay/Light groups",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class WeatherTimeView(HomeAssistantView):
    url = f"{URL_BASE}/weather_and_time"
    name = "nspanel_core:weather_time"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        s = manager.config.settings
        html = _render(
            "weather_and_time.html",
            location_latitude=s.location_latitude,
            location_longitude=s.location_longitude,
            weather_update_interval=s.weather_update_interval,
            clock_us_style=s.clock_us_style,
            date_format=s.date_format,
            use_fahrenheit=s.use_fahrenheit,
            precipitation_format=s.precipitation_format,
            wind_speed_format=s.wind_speed_format,
            outside_temp_provider=s.outside_temp_provider,
            outside_temp_sensor=s.outside_temp_sensor_entity,
            page_title="Weather & Time",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        data = {
            "location_latitude": form.get("location_latitude", ""),
            "location_longitude": form.get("location_longitude", ""),
            "weather_update_interval": form.get("weather_update_interval", ""),
            "clock_us_style": form.get("clock_us_style", ""),
            "date_format": form.get("date_format", ""),
            "use_fahrenheit": form.get("use_fahrenheit", ""),
            "precipitation_format": form.get("precipitation_format", ""),
            "wind_speed_format": form.get("wind_speed_format", ""),
            "outside_temp_provider": form.get("outside_temp_provider", ""),
            "outside_temp_sensor_entity": form.get("outside_temp_sensor", ""),
        }
        if data["outside_temp_sensor_entity"]:
            import re as _re

            if not _re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", data["outside_temp_sensor_entity"]):
                return web.Response(text="Bad outside temperature sensor entity id", status=422)
        if data["outside_temp_provider"] not in ("", "homeassistant", "openhab", "manual"):
            return web.Response(text="Bad outside temperature provider", status=422)
        errors = await manager.apply_settings(data)
        if errors:
            return web.Response(
                text="Weather errors: " + "; ".join(f"{k}: {v}" for k, v in errors.items()),
                status=422,
            )
        return _redirect(request, f"{URL_BASE}/weather_and_time")


class DeniedPanelsView(HomeAssistantView):
    url = f"{URL_BASE}/denied_nspanels"
    name = "nspanel_core:denied"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        denied = [asdict(p) for p in manager.config.panels if p.denied]
        html = _render(
            "denied_nspanels.html",
            nspanels=denied,
            page_title="Denied NSPanels",
        )
        return web.Response(text=html, content_type="text/html")


class SettingsView(HomeAssistantView):
    url = f"{URL_BASE}/settings"
    name = "nspanel_core:settings"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        s = manager.config.settings
        themes = {"nspmwip": "NSPanel Core (dark)"}
        html = _render(
            "settings.html",
            manager_address=s.manager_address,
            manager_port=s.manager_port,
            mqtt_server=getattr(s, "mqtt_server", ""),
            mqtt_port=getattr(s, "mqtt_port", 1883),
            mqtt_username=getattr(s, "mqtt_username", ""),
            mqtt_password=getattr(s, "mqtt_password", ""),
            mqttmanager_log_level=getattr(s, "mqttmanager_log_level", "info"),
            color_temp_min=s.color_temp_min,
            color_temp_max=s.color_temp_max,
            reverse_color_temp=s.reverse_color_temp,
            optimistic_mode=s.optimistic_mode,
            turn_on_behaviour=s.turn_on_behaviour,
            turn_on_behavior=s.turn_on_behaviour,
            turn_on_light_behaviour=s.turn_on_behaviour,
            home_assistant_address="",
            home_assistant_token="",
            raise_to_100_light_level=0,
            min_button_push_time=50,
            button_long_press_time=400,
            special_mode_trigger_time=350,
            special_mode_release_time=600,
            screensaver_activation_timeout=s.screensaver_activation_timeout if hasattr(s, "screensaver_activation_timeout") else 15,
            screen_dim_level=100,
            screensaver_dim_level=20,
            screensaver_mode=getattr(s, "screensaver_mode", "with_background"),
            show_screensaver_inside_temperature=True,
            show_screensaver_outside_temperature=True,
            light_turn_on_brightness=s.light_turn_on_brightness,
            room_status_backoff_time=0,
            all_rooms_status_backoff_time=0,
            max_live_log_messages=100,
            max_log_buffer_size=1000,
            is_home_assistant_addon=True,
            default_nspanel_type="sonoff",
            auto_tft_updates=getattr(s, "auto_tft_updates", True),
            rooms=[
                {
                    "id": r.id,
                    "name": r.name,
                    "panels": sum(1 for p in manager.config.panels if p.room_id == r.id),
                }
                for r in manager.config.rooms
            ],
            themes=themes,
            theme=s.theme,
            page_title="Settings",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class SaveSettingsView(HomeAssistantView):
    """Persist the global settings form (POST /nspanel_core/save_settings).

    Only GlobalSettings fields are stored; legacy add-on fields in the form
    (mqtt_*, home_assistant_*, backoff times, log levels) are ignored.
    Panel timing defaults in the form are pushed down to every panel.
    """

    url = f"{URL_BASE}/save_settings"
    name = "nspanel_core:save_settings"
    requires_auth = True

    _PANEL_DEFAULTS = {
        "min_button_push_time": (0, 10000),
        "button_long_press_time": (0, 10000),
        "special_mode_trigger_time": (0, 10000),
        "special_mode_release_time": (0, 10000),
        "screen_dim_level": (1, 100),
        "screensaver_dim_level": (0, 100),
        "screensaver_activation_timeout": (0, 86400),
    }
    _PANEL_SCREENSAVER_MODES = (
        "with_background", "without_background",
        "datetime_with_background", "datetime_without_background",
        "no_screensaver",
    )

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        data = dict(form)
        # The form uses turn_on_behavior (or); the model uses our spelling.
        if "turn_on_behavior" in data and "turn_on_behaviour" not in data:
            data["turn_on_behaviour"] = data["turn_on_behavior"]
        errors = await manager.apply_settings(data)
        if errors:
            return web.Response(
                text="Settings errors: " + "; ".join(f"{k}: {v}" for k, v in errors.items()),
                status=422,
            )
        pushed = []
        for key, (lo, hi) in self._PANEL_DEFAULTS.items():
            if key in form:
                try:
                    n = int(str(form[key]).strip())
                except (ValueError, TypeError):
                    return web.Response(text=f"Bad {key}: must be a number", status=422)
                if not (lo <= n <= hi):
                    return web.Response(text=f"Bad {key}: must be {lo}..{hi}", status=422)
                for panel in manager.config.panels:
                    setattr(panel, key, n)
                pushed.append(key)
        if "screensaver_mode" in form:
            sm = str(form["screensaver_mode"]).strip()
            if sm not in self._PANEL_SCREENSAVER_MODES:
                return web.Response(text="Bad screensaver_mode", status=422)
            for panel in manager.config.panels:
                panel.screensaver_mode = sm
            pushed.append("screensaver_mode")
        if pushed:
            await manager.async_save()
        return _redirect(request, f"{URL_BASE}/settings")


class ManagerSettingsView(HomeAssistantView):
    url = f"{URL_BASE}/manager_settings"
    name = "nspanel_core:manager_settings"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        room_views = []
        for r in manager.config.rooms:
            r_nspanels = [type("P", (), {"friendly_name": p.name}) for p in manager.config.panels if p.room_id == r.id]
            room_views.append(_RoomView(r, nspanels=r_nspanels))
        html = _render(
            "manager_settings.html",
            page_title="Manager settings",
            nspanels=_panels_context(manager),
            rooms=room_views,
        )
        return web.Response(text=html, content_type="text/html")



import hashlib as _hashlib
import os as _os


def _firmware_dir():
    return _os.path.join(_os.path.dirname(__file__), "firmware")


def _firmware_file(model: str, filename: str) -> str | None:
    """Resolve a firmware-binary path under a strict allowlist.

    Only sonoff/custom models and fixed filenames — no user-controlled path
    segments, so directory traversal is impossible.
    """
    if model not in ("sonoff", "custom"):
        return None
    if filename not in ("firmware.bin", "data_file.bin"):
        return None
    path = _os.path.join(_firmware_dir(), model, filename)
    return path if _os.path.exists(path) else None


def _tft_file(region: str) -> str | None:
    if region not in ("eu", "us"):
        return None
    filename = "gui_us.tft" if region == "us" else "gui.tft"
    path = _os.path.join(_os.path.dirname(__file__), "tft", filename)
    return path if _os.path.exists(path) else None


def _ota_checksum(request, kind: str, name: str, path: str) -> str:
    """MD5 for an OTA file: startup cache first, disk fallback."""
    try:
        digest = _manager(request).ota_md5(kind, name)
    except Exception:  # noqa: BLE001 — manager not ready
        digest = ""
    return digest or _md5(path)


class OtaFileView(HomeAssistantView):
    """Base for panel OTA endpoints (firmware/TFT).

    Panels download over plain HTTP with no bearer token, so these stay
    requires_auth=False. Safety comes from fixed allowlists: only known
    filenames under the integration's own firmware/tft directories.
    """

    requires_auth = False

    _kind = ""
    _filename = ""

    async def get(self, request, **kwargs):
        manager = _manager(request)
        model = request.query.get("model", "sonoff")
        if self._filename in ("eu", "us"):
            kind, name = "tft", ("gui_us.tft" if self._filename == "us" else "gui.tft")
            path = manager.servable_path(kind, name) or _tft_file(self._filename)
        else:
            kind, name, path = "firmware", f"{model}/{self._filename}", None
            if model in ("sonoff", "custom"):
                path = manager.servable_path(kind, f"{model}/{self._filename}") or _firmware_file(
                    model, self._filename
                )
        if path is None:
            if model not in ("sonoff", "custom") and self._filename not in ("eu", "us"):
                return web.Response(status=400, text="Unknown model")
            return web.Response(status=404, text="Not found")
        if self._kind == "checksum":
            # Serve the startup-computed hash (no disk I/O per request).
            return web.Response(text=_ota_checksum(request, kind, name, path))
        return web.FileResponse(path)


class DownloadFirmwareView(OtaFileView):
    url = "/download_firmware"
    name = "nspanel_core:ota:download_firmware"
    _kind = "file"
    _filename = "firmware.bin"


class DownloadDataFileView(OtaFileView):
    url = "/download_data_file"
    name = "nspanel_core:ota:download_data_file"
    _kind = "file"
    _filename = "data_file.bin"


class ChecksumFirmwareView(OtaFileView):
    url = "/checksum_firmware"
    name = "nspanel_core:ota:checksum_firmware"
    _kind = "checksum"
    _filename = "firmware.bin"


class ChecksumDataFileView(OtaFileView):
    url = "/checksum_data_file"
    name = "nspanel_core:ota:checksum_data_file"
    _kind = "checksum"
    _filename = "data_file.bin"


class DownloadTftEuView(OtaFileView):
    url = "/download_tft_eu"
    name = "nspanel_core:ota:download_tft_eu"
    _kind = "file"
    _filename = "eu"


class DownloadTftUsView(OtaFileView):
    url = "/download_tft_us"
    name = "nspanel_core:ota:download_tft_us"
    _kind = "file"
    _filename = "us"


class ChecksumTftEuView(OtaFileView):
    url = "/checksum_tft_file_eu"
    name = "nspanel_core:ota:checksum_tft_eu"
    _kind = "checksum"
    _filename = "eu"


class ChecksumTftUsView(OtaFileView):
    url = "/checksum_tft_file_us"
    name = "nspanel_core:ota:checksum_tft_us"
    _kind = "checksum"
    _filename = "us"


def _md5(path: str) -> str:
    h = _hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()




class DownloadTftView(HomeAssistantView):
    url = f"{URL_BASE}/download_tft/{{panel_id}}"
    name = "nspanel_core:download_tft"
    requires_auth = True

    async def get(self, request, **kwargs):
        manager = _manager(request)
        try:
            panel_id = int(request.match_info["panel_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(status=400, text="Bad panel id")
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(status=404, text="Panel not found")
        region = "us" if panel.is_us_panel else "eu"
        path = _tft_file(region)
        if path is None:
            return web.Response(status=404, text="TFT not found")
        return web.FileResponse(path)


class ChecksumTftView(HomeAssistantView):
    url = f"{URL_BASE}/checksum_tft_file/{{panel_id}}"
    name = "nspanel_core:checksum_tft"
    requires_auth = True

    async def get(self, request, **kwargs):
        manager = _manager(request)
        try:
            panel_id = int(request.match_info["panel_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(status=400, text="Bad panel id")
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(status=404, text="Panel not found")
        region = "us" if panel.is_us_panel else "eu"
        filename = "gui_us.tft" if panel.is_us_panel else "gui.tft"
        path = _tft_file(region)
        if path is None:
            return web.Response(status=404, text="TFT not found")
        return web.Response(text=_ota_checksum(request, "tft", filename, path))


class OtaUploadView(HomeAssistantView):
    """Base for panel firmware/TFT uploads (multipart POST, admin only).

    Files land in the integration's own firmware/<model>/ and tft/
    directories under fixed names — no user-controlled paths. After a
    successful write the OTA hash cache is refreshed so checksums and
    triggers use the new file immediately.
    """

    requires_auth = True
    _max_bytes = 32 * 1024 * 1024

    async def _save_upload(self, request, field: str, dest_path: str) -> web.Response | None:
        # Single multipart parse: request.post() already consumed the body,
        # so file fields come from it as FileFields (no second read).
        form = await request.post()
        file_field = form.get(field)
        filename = getattr(file_field, "filename", "") or ""
        if not filename:
            return web.Response(text="No file uploaded", status=400)
        stream = getattr(file_field, "file", None)
        if stream is None:
            return web.Response(text="No file uploaded", status=400)

        def _write() -> int | None:
            size = 0
            try:
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self._max_bytes:
                            return None
                        f.write(chunk)
            except OSError:
                return None
            return size if size > 0 else None

        size = await _manager(request).hass.async_add_executor_job(_write)
        if size is None:
            try:
                _os.remove(dest_path)
            except OSError:
                pass
            return web.Response(text="File too large, empty or unwritable", status=413)
        return None


class SaveFirmwareView(OtaUploadView):
    url = f"{URL_BASE}/save_new_firmware"
    name = "nspanel_core:save_firmware"

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        model = str(form.get("model", "sonoff"))
        if model not in ("sonoff", "custom"):
            return web.Response(text="Unknown model", status=400)
        dest = _os.path.join(_firmware_dir(), model, "firmware.bin")
        err = await self._save_upload(request, "firmware", dest)
        if err is not None:
            return err
        await manager.hass.async_add_executor_job(
            manager.invalidate_ota_cache, "firmware", f"{model}/firmware.bin", dest
        )
        return _redirect(request, f"{URL_BASE}/settings")


class SaveDataFileView(OtaUploadView):
    url = f"{URL_BASE}/save_new_data_file"
    name = "nspanel_core:save_data_file"

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        model = str(form.get("model", "sonoff"))
        if model not in ("sonoff", "custom"):
            return web.Response(text="Unknown model", status=400)
        dest = _os.path.join(_firmware_dir(), model, "data_file.bin")
        err = await self._save_upload(request, "data_file", dest)
        if err is not None:
            return err
        await manager.hass.async_add_executor_job(
            manager.invalidate_ota_cache, "firmware", f"{model}/data_file.bin", dest
        )
        return _redirect(request, f"{URL_BASE}/settings")


class SaveTftFileView(OtaUploadView):
    url = f"{URL_BASE}/save_new_tft_file"
    name = "nspanel_core:save_tft_file"

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        variant = str(form.get("tft_file_type", "") or form.get("file_version", "")).strip()
        if variant.lower().startswith("us"):
            filename = "gui_us.tft"
        elif variant.lower().startswith(("eu", "europe")):
            filename = "gui.tft"
        else:
            return web.Response(text="Unknown TFT variant", status=400)
        dest = _os.path.join(_os.path.dirname(__file__), "tft", filename)
        err = await self._save_upload(request, "tft_file", dest)
        if err is not None:
            return err
        await manager.hass.async_add_executor_job(
            manager.invalidate_ota_cache, "tft", filename, dest
        )
        # Pin the exact uploaded bytes: mirror into any overlay copy that
        # would otherwise shadow the upload, and record proof metadata.
        proof = await manager.hass.async_add_executor_job(
            manager.note_custom_tft, filename
        )
        await manager.async_save()
        _LOGGER.info("Custom TFT pinned for serving: %s", proof)
        return _redirect(request, f"{URL_BASE}/settings")


class FirmwareStatusView(HomeAssistantView):
    """JSON: served firmware version vs latest manifest version."""

    url = f"{URL_BASE}/firmware_status"
    name = "nspanel_core:firmware_status"
    requires_auth = True

    async def get(self, request, **kwargs):
        from . import firmware_store as _fs

        manager = _manager(request)
        s = manager.config.settings
        current = manager._ota_active_version or await manager.hass.async_add_executor_job(
            _fs.bundled_version, _os.path.dirname(__file__)
        )
        status = dict(manager._firmware_status)
        status.update(
            {
                "current": current,
                "latest": s.firmware_latest_version or "",
                "last_check": s.firmware_last_check or "",
                "manifest_url": _fs.DEFAULT_MANIFEST_URL,
                "auto_check_hours": 6,
                "served_tft": await manager.hass.async_add_executor_job(
                    manager.served_tft_info
                ),
            }
        )
        return web.json_response(status)


class FirmwareCheckView(HomeAssistantView):
    """POST: fetch the manifest now, report latest (no download)."""

    url = f"{URL_BASE}/firmware_check"
    name = "nspanel_core:firmware_check"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        status = await manager.check_firmware_updates()
        return web.json_response(status)


class FirmwareInstallView(HomeAssistantView):
    """POST: download + activate the latest manifest firmware.

    Panels are pushed the update over the same MQTT OTA path immediately.
    """

    url = f"{URL_BASE}/firmware_install"
    name = "nspanel_core:firmware_install"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        ok, message = await manager.activate_firmware_version()
        return web.json_response({"ok": ok, "message": message})


class ReorderRoomsView(HomeAssistantView):
    """Persist drag-and-drop room order (rooms page sortable).

    Posts htmx_form_save_rooms_order_field = JSON {"rooms": [ids...]}.
    Unknown ids are ignored; missing rooms keep their relative order after.
    """

    url = f"{URL_BASE}/htmx_partial_reorder_rooms"
    name = "nspanel_core:reorder_rooms"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        raw = str(form.get("htmx_form_save_rooms_order_field", "") or "")
        try:
            payload = json.loads(raw)
            ids = [int(v) for v in payload.get("rooms", [])]
        except (ValueError, TypeError, AttributeError):
            return web.Response(text="Bad rooms order payload", status=400)
        by_id = {r.id: r for r in manager.config.rooms}
        ordered = [by_id[v] for v in ids if v in by_id]
        rest = [r for r in manager.config.rooms if r.id not in {r2.id for r2 in ordered}]
        manager.config.rooms = ordered + rest
        for i, r in enumerate(manager.config.rooms):
            r.display_order = i
        await manager.async_save()
        return web.Response(text="", content_type="text/html")


class GetIpByHostnameView(HomeAssistantView):
    """Resolve a hostname to an IP server-side (settings "Load from URL").

    The browser may be unable to resolve LAN names; the HA host can.
    POST JSON {"hostname": ...} → {"ip": ...} or 422.
    """

    url = f"{URL_BASE}/get_ip_by_hostname"
    name = "nspanel_core:get_ip_by_hostname"
    requires_auth = True

    async def post(self, request, **kwargs):
        import socket as _socket

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.Response(text="Bad JSON", status=400)
        hostname = str((payload or {}).get("hostname", "") or "").strip()
        if not hostname:
            return web.Response(text="Missing hostname", status=400)
        loop = asyncio.get_event_loop()
        try:
            ip = await loop.run_in_executor(None, _socket.gethostbyname, hostname)
        except Exception as exc:  # noqa: BLE001
            return web.Response(text=f"Cannot resolve: {exc}", status=422)
        return web.json_response({"ip": ip})


class ComingSoonView(HomeAssistantView):
    """Catch-all under /nspanel_core/* — never leaks the HA frontend into the
    iframe (this caused the 'doubled page' when clicking unported links)."""

    url = f"{URL_BASE}/{{tail:.*}}"
    name = "nspanel_core:catchall"
    requires_auth = False

    async def get(self, request, **kwargs):
        html = _render(
            "index_shell.html",
            page_title="This page is being ported",
            nspanels=[],
        )
        return web.Response(text=html, content_type="text/html", status=404)


_PANEL_SCREENSAVER_MODES = (
    "with_background", "without_background",
    "datetime_with_background", "datetime_without_background",
    "no_screensaver",
)


def _resolve_screensaver_mode(panel, settings) -> str:
    """Resolve the mode string the display understands.

    Per-panel "global" (and any legacy/invalid value) falls back to the
    global settings default; anything still invalid falls back to
    with_background so the panel never receives a mode it rejects.
    """
    sm = getattr(panel, "screensaver_mode", "")
    if not isinstance(sm, str):
        sm = str(sm)
    if sm == "global" or sm not in _PANEL_SCREENSAVER_MODES:
        sm = getattr(settings, "screensaver_mode", "")
    if not isinstance(sm, str) or sm not in _PANEL_SCREENSAVER_MODES:
        sm = "with_background"
    return sm


def _panel_json_config(manager, panel) -> dict:
    """Build the JSON the firmware downloads (exact key/shape contract).

    Booleans that ArduinoJson compares with .equals("True") are emitted
    capitalized; light/scene capability flags compared with .equals("true")
    are lowercase; room light "ceiling" is a real JSON boolean.
    """
    s = manager.config.settings
    rooms = manager.config.rooms
    room_ids = panel.rooms or [r.id for r in rooms]
    global_scene_pages = [
        p.id for p in manager.config.pages if p.room_id is None and p.is_scenes_page
    ]
    scenes = {}
    for sc in manager.config.scenes:
        page = next((p for p in manager.config.pages if p.id == sc.page_id), None)
        if page is None:
            continue
        if page.room_id is None and page.id in global_scene_pages:
            scenes[str(sc.id)] = {"name": sc.name, "can_save": "false" if sc.ha_entity else "true"}
    cfg = {
        "home": panel.room_id,
        "default_page": panel.default_page,
        "color_temp_min": s.color_temp_min,
        "color_temp_max": s.color_temp_max,
        "reverse_color_temp": "True" if s.reverse_color_temp else "False",
        "raise_to_100_light_level": panel.raise_to_100_light_level,
        "min_button_push_time": panel.min_button_push_time,
        "button_long_press_time": panel.button_long_press_time,
        "special_mode_trigger_time": panel.special_mode_trigger_time,
        "special_mode_release_time": panel.special_mode_release_time,
        "mqtt_ignore_time": 5000,
        "screen_dim_level": panel.screen_dim_level,
        "screensaver_dim_level": panel.screensaver_dim_level,
        "screensaver_activation_timeout": panel.screensaver_activation_timeout,
        "screensaver_mode": _resolve_screensaver_mode(panel, s),
        "clock_us_style": "True" if panel.clock_us_style else "False",
        "lock_to_default_room": "True" if panel.lock_to_default_room else "False",
        "is_us_panel": "True" if panel.is_us_panel else "False",
        "button1_mode": panel.button1_mode,
        "button2_mode": panel.button2_mode,
        "use_fahrenheit": "True" if panel.use_fahrenheit else "False",
        "temperature_calibration": panel.temperature_calibration,
        "reverse_relays": "True" if panel.reverse_relays else "False",
        "button1_mqtt_topic": panel.button1_mqtt_topic,
        "button1_mqtt_payload": panel.button1_mqtt_payload,
        "show_home_scenes": "True" if panel.show_home_scenes else "False",
        "show_home_ceiling": "True" if panel.show_home_ceiling else "False",
        "show_home_table": "True" if panel.show_home_table else "False",
        "show_home_kelvin": "True" if panel.show_home_kelvin else "False",
        "button2_mqtt_topic": panel.button2_mqtt_topic,
        "button2_mqtt_payload": panel.button2_mqtt_payload,
        "relay1_default_mode": "True" if panel.relay1_default_mode else "False",
        "relay2_default_mode": "True" if panel.relay2_default_mode else "False",
        "name": panel.name,
        "rooms": room_ids,
        "scenes": scenes,
        "button1_detached_light": panel.button1_detached_light,
        "button2_detached_light": panel.button2_detached_light,
    }
    return cfg


def _room_json_config(manager, room_id: int) -> dict | None:
    """Build the per-room JSON the firmware downloads."""
    room = manager._room_by_id(room_id)
    if room is None:
        return None
    lights = {}
    for light in manager.config.lights:
        if light.room_id != room_id:
            continue
        lights[str(light.id)] = {
            "name": light.name,
            "can_dim": "true" if light.can_dim else "false",
            "can_temperature": "true" if light.can_color_temperature else "false",
            "can_rgb": "true" if light.can_rgb else "false",
            "view_position": str(light.page_slot),
            "ceiling": light.light_type == "ceiling",
        }
    scenes = {}
    for sc in manager.config.scenes:
        page = next((p for p in manager.config.pages if p.id == sc.page_id), None)
        if page is not None and page.room_id == room_id:
            scenes[str(sc.id)] = {"name": sc.name, "can_save": "false" if sc.ha_entity else "true"}
    return {"name": room.name, "lights": lights, "scenes": scenes}


class EntitiesListView(HomeAssistantView):
    """JSON entity list for the in-UI entity pickers (XHR, authed).

    Shape matches what modal-select-entity.js expects:
    {errors: [], home_assistant_entities: [{entity_id, label}], ...}.
    """

    url = "/api/get_all_available_entities"
    name = "nspanel_core:api:entities"
    requires_auth = True

    async def get(self, request, **kwargs):
        domains = request.query.get("domain", "")
        wanted = {d.strip() for d in domains.split(",") if d.strip()} if domains else None
        entities = []
        for state in self._states_sorted(request):
            if wanted and state.domain not in wanted:
                continue
            entities.append({
                "entity_id": state.entity_id,
                "label": state.attributes.get("friendly_name") or state.entity_id,
            })

        return web.json_response({
            "errors": [],
            "home_assistant_entities": entities,
            "openhab_entities": [],
            "manual_entities": [],
        })

    @staticmethod
    def _states_sorted(request):
        hass = request.app["hass"]
        return sorted(hass.states.async_all(), key=lambda s: s.entity_id)


class EntityPickerModalView(HomeAssistantView):
    """Serve the existing entity-picker modal partials (XHR, authed)."""

    requires_auth = True
    url = ""
    name = ""
    template = ""

    async def get(self, request, **kwargs):
        manager = _manager(request)
        entities = [
            {"type": "homeassistant", "label": s.attributes.get("friendly_name") or s.entity_id,
             "item_id": s.entity_id}
            for s in sorted(manager.hass.states.async_all(), key=lambda s: s.entity_id)
        ]
        html = _render(self.template, entities=entities)
        return web.Response(text=html, content_type="text/html")


class SelectRoomTempSensorView(EntityPickerModalView):
    url = f"{URL_BASE}/htmx_partial_select_room_temperature_sensor"
    name = "nspanel_core:picker:room_temp_sensor"
    template = "partial/select_room_temperature_sensor.html"


class SelectRoomTempSensorProviderView(EntityPickerModalView):
    url = f"{URL_BASE}/htmx_partial_select_room_temperature_sensor_provider"
    name = "nspanel_core:picker:room_temp_provider"
    template = "partial/select_room_temperature_sensor_provider.html"


class SelectWeatherOutsideTempSensorView(EntityPickerModalView):
    url = f"{URL_BASE}/htmx_partial_select_weather_outside_temperature_sensor"
    name = "nspanel_core:picker:weather_outside_temp"
    template = "partial/select_weather_outside_temperature_sensor.html"


class SelectWeatherOutsideTempProviderView(EntityPickerModalView):
    url = f"{URL_BASE}/htmx_partial_select_weather_outside_temperature_sensor_provider"
    name = "nspanel_core:picker:weather_outside_temp_provider"
    template = "partial/select_weather_outside_temperature_sensor_provider.html"


class SelectWeatherLocationView(EntityPickerModalView):
    url = f"{URL_BASE}/htmx_partial_select_weather_location"
    name = "nspanel_core:picker:weather_location"
    template = "partial/select_weather_location.html"


class EntitiesListNamespacedView(EntitiesListView):
    url = f"{URL_BASE}/api/get_all_available_entities"
    name = "nspanel_core:api:entities_ns"


class PanelConfigByMacView(HomeAssistantView):
    """Panel firmware config download: GET /api/get_nspanel_config?mac=<mac>.

    Panels cannot send bearer tokens, so this is gated on the MAC belonging
    to a registered panel. The payload contains no secrets (rooms, lights,
    scenes, display settings only).
    """

    url = "/api/get_nspanel_config"
    name = "nspanel_core:api:panel_config"
    requires_auth = False

    async def get(self, request, **kwargs):
        from .const import topic_safe

        manager = _manager(request)
        mac = topic_safe(request.query.get("mac", ""))
        panel = next(
            (p for p in manager.config.panels if topic_safe(p.mac) == mac), None
        ) if mac else None
        if panel is None:
            return web.Response(status=404, text="Unknown panel")
        return web.json_response(_panel_json_config(manager, panel))


class RoomConfigView(HomeAssistantView):
    """Per-room firmware config download: GET /api/get_nspanel_config/room/<id>.

    Same device-only gating as the panel config (no secrets in payload).
    """

    url = "/api/get_nspanel_config/room/{room_id}"
    name = "nspanel_core:api:room_config"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        try:
            room_id = int(request.match_info["room_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(status=400, text="Bad room id")
        cfg = _room_json_config(manager, room_id)
        if cfg is None:
            return web.Response(status=404, text="Unknown room")
        return web.json_response(cfg)


class RoomsPageView(HomeAssistantView):
    url = f"{URL_BASE}/rooms"
    name = "nspanel_core:rooms"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        rooms_ctx = []
        for room in manager.config.rooms:
            panels_in_room = [
                {"id": p.id, "status": "online" if p.online else "offline"}
                for p in manager.config.panels if p.room_id == room.id
            ]
            rooms_ctx.append({"room": {"id": room.id, "friendly_name": room.name}, "nspanels": panels_in_room})
        html = _render(
            "rooms.html",
            rooms=rooms_ctx,
            page_title="Rooms",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class EditRoomView(HomeAssistantView):
    url = f"{URL_BASE}/rooms/{{room_id}}"
    name = "nspanel_core:edit_room"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        room_id = int(request.match_info["room_id"])
        room = next((r for r in manager.config.rooms if r.id == room_id), None)
        if room is None:
            raise web.HTTPFound(f"{URL_BASE}/settings")
        room_obj = type("Room", (), {
            "id": room.id,
            "friendly_name": room.name,
            "name": room.name,
            "nspanel_set": type("QS", (), {"all": [type("P", (), {"friendly_name": p.name, "id": p.id}) for p in manager.config.panels if p.room_id == room_id]})(),
            "entity_set": type("QS", (), {"all": [type("E", (), {"friendly_name": e.name, "id": e.id}) for e in manager.config.lights if e.room_id == room_id]})(),
        })()
        html = _render(
            "edit_room.html",
            room=room_obj,
            rooms=[type("R", (), {"id": r.id, "friendly_name": r.name}) for r in manager.config.rooms],
            nspanels=[],
            total_num_rooms=len(manager.config.rooms),
            entity_pages=[],
            page_title=f"Room: {room.name}",
            nspanels_list=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


def _redirect(request, location: str) -> web.Response:
    """Redirect that works for full-page loads, fetch and htmx alike."""
    if request.headers.get("HX-Request"):
        return web.Response(status=204, headers={"HX-Redirect": location})
    raise web.HTTPFound(location)


def _redirect_back(request, fallback: str) -> web.Response:
    """Rooms/settings forms live on several pages: go back to the same-origin
    page that invoked them instead of always landing on the fallback."""
    try:
        ref = str(request.headers.get("Referer", "") or "")
    except Exception:  # noqa: BLE001
        ref = ""
    if ref.startswith("/") and ref.startswith(URL_BASE):
        return _redirect(request, ref)
    for prefix in ("http://", "https://"):
        if ref.startswith(prefix):
            try:
                from urllib.parse import urlparse

                path = urlparse(ref).path or ""
            except Exception:  # noqa: BLE001
                path = ""
            if path.startswith(URL_BASE):
                return _redirect(request, path)
            break
    return _redirect(request, fallback)


class SaveNewRoomView(HomeAssistantView):
    url = f"{URL_BASE}/save_new_room"
    name = "nspanel_core:save_new_room"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        name = str(form.get("friendly_name", "")).strip()
        if not name:
            return web.Response(text="Room name must not be empty", status=400)
        if len(name) > 64:
            return web.Response(text="Room name too long (max 64)", status=400)
        await manager.add_room(name)
        return _redirect_back(request, f"{URL_BASE}/settings")


class UpdateRoomView(HomeAssistantView):
    url = f"{URL_BASE}/update_room_form"
    name = "nspanel_core:update_room"
    requires_auth = True

    _ENTITY_RE = None

    async def post(self, request, **kwargs):
        import re

        manager = _manager(request)
        form = await request.post()
        try:
            room_id = int(form.get("room_id", 0))
        except (ValueError, TypeError):
            return web.Response(text="Bad room id", status=400)
        room = manager._room_by_id(room_id)
        if room is None:
            # edit_room.html posts without room_id (legacy form): fall back to
            # the single-room case is ambiguous -> require explicit id.
            return web.Response(text="Unknown room", status=404)
        name = str(form.get("friendly_name", "")).strip()
        if name:
            if len(name) > 64:
                return web.Response(text="Room name too long (max 64)", status=400)
            room.name = name
        provider = str(form.get("room_temp_provider", "") or "").strip()
        sensor = str(form.get("room_temp_sensor", "") or "").strip()
        if sensor and not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", sensor):
            return web.Response(text="Bad temperature sensor entity id", status=422)
        if provider and provider not in ("homeassistant", "openhab", "manual", ""):
            return web.Response(text="Bad temperature provider", status=400)
        room.temp_sensor_entity = sensor
        await manager.async_save()
        return _redirect_back(request, f"{URL_BASE}/settings")


class DeleteRoomView(HomeAssistantView):
    url = f"{URL_BASE}/api/rooms/{{room_id}}/delete"
    name = "nspanel_core:api:room_delete2"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        try:
            room_id = int(request.match_info["room_id"])
        except (KeyError, ValueError, TypeError):
            return web.Response(text="Bad room id", status=400)
        if manager._room_by_id(room_id) is None:
            return web.Response(text="Unknown room", status=404)
        if len(manager.config.rooms) <= 1:
            return web.Response(text="Cannot delete the last room", status=400)
        await manager.remove_room(room_id)
        return _redirect_back(request, f"{URL_BASE}/settings")


class RestartView(HomeAssistantView):
    url = f"{URL_BASE}/api/restart"
    name = "nspanel_core:api:restart"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        await manager.async_stop()
        await manager.async_start()
        return web.Response(text="", status=200)


class ThemeView(HomeAssistantView):
    url = f"{URL_BASE}/api/theme"
    name = "nspanel_core:api:theme"
    requires_auth = True

    async def post(self, request, **kwargs):
        manager = _manager(request)
        form = await request.post()
        # htmx posts the radio value as theme-controller; be liberal.
        theme = (
            form.get("theme")
            or form.get("theme-controller")
            or form.get("value")
            or ""
        )
        theme = str(theme).strip()
        if theme not in ("nspmwip",):
            return web.Response(text="Unknown theme", status=400)
        manager.config.settings.theme = theme
        await manager.async_save()
        return web.Response(text="", status=200)


class MessagesView(HomeAssistantView):
    url = f"{URL_BASE}/api/messages"
    name = "nspanel_core:api:messages"
    requires_auth = True

    async def get(self, request, **kwargs):
        manager = _manager(request)
        messages = manager.get_messages()
        html = _render(
            "partial/show_messages.html",
            messages=messages,
        )
        manager.mark_messages_read()
        return web.Response(text=html, content_type="text/html")


class StompView(HomeAssistantView):
    """The STOMP WebSocket endpoint (the UI's live data connection)."""

    url = f"{URL_BASE}/ws"
    name = "nspanel_core:ws"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        return await manager.stomp.handle_ws(request)


class WebappStompView(HomeAssistantView):
    """STOMP WebSocket at the original /websocket/stomp path (for the web app)."""

    url = "/websocket/stomp"
    name = "nspanel_core:webapp_ws"
    requires_auth = False

    async def get(self, request, **kwargs):
        manager = _manager(request)
        return await manager.stomp.handle_ws(request)


class WebappIndexView(HomeAssistantView):
    """Serve the web app's index.html at /webapp."""

    url = "/webapp"
    name = "nspanel_core:webapp_index"
    requires_auth = False

    async def get(self, request, **kwargs):
        webapp_dir = pathlib.Path(__file__).parent / "ui" / "webapp"
        index_path = webapp_dir / "index.html"
        if not index_path.exists():
            return web.Response(status=404, text="Web app not found")
        return web.FileResponse(index_path)


class WebappAssetView(HomeAssistantView):
    """Serve web app static assets (js, css, fonts, etc.)."""

    url = "/webapp/{tail:.*}"
    name = "nspanel_core:webapp_asset"
    requires_auth = False

    async def get(self, request, **kwargs):
        webapp_dir = pathlib.Path(__file__).parent / "ui" / "webapp"
        tail = request.match_info.get("tail", "")
        if not tail:
            tail = "index.html"
        file_path = (webapp_dir / tail).resolve()
        # Prevent path traversal
        if not str(file_path).startswith(str(webapp_dir.resolve())):
            return web.Response(status=403, text="Forbidden")
        if not file_path.exists() or not file_path.is_file():
            # SPA fallback: serve index.html for client-side routing
            index_path = webapp_dir / "index.html"
            if index_path.exists():
                return web.FileResponse(index_path)
            return web.Response(status=404, text="Not found")
        return web.FileResponse(file_path)


import re  # noqa: E402


def async_register_ui(hass: HomeAssistant, entry_id: str) -> None:
    """Register the original-UI views, static assets and the sidebar panel."""
    hass.http.app["hass"] = hass

    from homeassistant.components.http import StaticPathConfig

    hass.loop.create_task(
        hass.http.async_register_static_paths(
            [StaticPathConfig(f"{URL_BASE}/static", str(STATIC_DIR), cache_headers=True)]
        )
    )

    # Webapp is served via views below (not via static path, because HA's
    # static path handler returns 403 for the root directory).

    # Pre-compile templates off the event loop (first render does disk I/O).
    async def _warm_templates() -> None:
        await hass.async_add_executor_job(_warm_template_cache)

    hass.async_create_task(_warm_templates())


    # Register via HA (enforces requires_auth + auth middleware). The old
    # direct add_route bypassed auth entirely even with requires_auth=True.
    views = [
        MainPageView,
        HtmxNspanelsSectionView,
        PanelActionView,
        EditPanelView,
        SavePanelSettingsView,
        RoomsPageView,
        EditRoomView,
        SaveNewRoomView,
        DeleteRoomView,
        GlobalScenesView,
        RelayGroupsView,
        WeatherTimeView,
        DeniedPanelsView,
        SettingsView,
        ManagerSettingsView,
        PlaceholderPageView,
        RestartView,
        ThemeView,
        ReorderRoomsView,
        GetIpByHostnameView,
        MessagesView,
        StompView,
        WebappStompView,
        WebappIndexView,
        WebappAssetView,
        PanelConfigByMacView,
        RoomConfigView,
        SaveSettingsView,
        UpdateRoomView,
        SaveFirmwareView,
        SaveDataFileView,
        SaveTftFileView,
        EntitiesListView,
        EntitiesListNamespacedView,
        SelectRoomTempSensorView,
        SelectRoomTempSensorProviderView,
        SelectWeatherOutsideTempSensorView,
        SelectWeatherOutsideTempProviderView,
        SelectWeatherLocationView,
        DownloadFirmwareView,
        DownloadDataFileView,
        ChecksumFirmwareView,
        ChecksumDataFileView,
        DownloadTftEuView,
        DownloadTftUsView,
        ChecksumTftEuView,
        ChecksumTftUsView,
        DownloadTftView,
        ChecksumTftView,
        FirmwareStatusView,
        FirmwareCheckView,
        FirmwareInstallView,
        ComingSoonView,
    ]
    for view_cls in views:
        try:
            hass.http.register_view(view_cls())
        except RuntimeError:
            # Route already registered (e.g. reload) — skip
            pass

    # Sidebar panel via panel_custom(embed_iframe=True): renders a bare iframe
    # filling the content area — no hass-subpage title bar above the UI.
    async def _register_sidebar_panel() -> None:
        from homeassistant.components.frontend import async_remove_panel
        from homeassistant.components.panel_custom import async_register_panel

        try:
            async_remove_panel(hass, "nspanel_core", warn_if_unknown=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            await async_register_panel(
                hass,
                frontend_url_path="nspanel_core",
                webcomponent_name="nspanel-core-panel",
                sidebar_title="NSPanel Core",
                sidebar_icon="mdi:tablet-dashboard",
                # Cache-buster: /static/* is served with max-age=31 days, so the
                # module URL must change with every release. Without it a browser
                # that cached an older panel.js keeps running it forever (the
                # v1.3.2 file pointed the iframe at /nspanel_core and rendered a
                # blank panel even after the server was fixed).
                module_url=f"{URL_BASE}/static/panel.js?v={_DASHBOARD_VERSION}",
                embed_iframe=True,
                config={"url": UI_PATH},
                require_admin=True,
            )
            _LOGGER.info("NSPanel Core sidebar panel registered at %s", URL_BASE)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to register NSPanel Core sidebar panel")

    hass.async_create_task(_register_sidebar_panel())

    hass.data[f"{DOMAIN}_entry_id"] = entry_id
    _LOGGER.info("NSPanel Core UI registered at %s", URL_BASE)
