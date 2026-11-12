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

UI_DIR = pathlib.Path(__file__).parent / "ui"
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"


def _render(template_name: str, **context) -> str:
    import jinja2

    import json as _json

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

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    import base64 as _b64
    import json as _json2

    def _jsonify(value):
        try:
            return _json2.dumps(value)
        except Exception:
            return str(value)

    def _base64_encode(value):
        return _b64.b64encode(str(value).encode()).decode()

    env.globals["RC"] = _RC
    env.filters["jsonify"] = _jsonify
    env.filters["base64_encode"] = _base64_encode
    template = env.get_template(template_name)
    context.setdefault("notifications", [])
    import json as _json
    import pathlib as _pathlib
    _manifest_path = _pathlib.Path(__file__).parent / "manifest.json"
    try:
        _ver = _json.loads(_manifest_path.read_text()).get("version", "1.2.0")
    except Exception:
        _ver = "1.2.0"
    context.setdefault("version", f"v{_ver}")
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
            },
        })
    return out


class MainPageView(HomeAssistantView):
    """The NSPanels page — original templates, live via STOMP."""

    url = URL_BASE
    name = "nspanel_core:page"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        html = _render(
            "index_htmx.html",
            nspanels=_panels_context(manager),
            manager_address=manager.config.settings.manager_address,
            temperature_unit="celsius",
        )
        return web.Response(text=html, content_type="text/html")


class HtmxNspanelsSectionView(HomeAssistantView):
    url = f"{URL_BASE}/htmx/nspanels"
    name = "nspanel_core:htmx:nspanels"
    requires_auth = False

    async def get(self, request):
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
    requires_auth = False

    async def post(self, request):
        return await self._act(request)

    async def delete(self, request):
        return await self._act(request)

    async def _act(self, request):
        manager = _manager(request)
        panel_id = int(request.match_info["panel_id"])
        action = request.match_info["action"]
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is not None:
            if action == "accept":
                panel.accepted = True
                panel.denied = False
                await manager.async_save()
                await manager._send_panel_config(panel)
                await manager._publish_panel_status(panel, "online")
            elif action == "deny":
                panel.denied = True
                panel.accepted = False
                await manager.async_save()
                await manager._publish_panel_status(panel, "offline")
            elif action == "delete":
                manager.config.panels.remove(panel)
                await manager.async_save()
                await manager._publish_panel_status(panel, "offline")
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

    async def get(self, request):
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

    async def get(self, request):
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
        settings_ctx["us_panel_orientation"] = ""
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
    url = f"{URL_BASE}/api/panel/{{panel_id}}/save"
    name = "nspanel_core:api:panel_save"
    requires_auth = False

    async def post(self, request):
        manager = _manager(request)
        panel_id = int(request.match_info["panel_id"])
        form = await request.post()
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(status=404)
        field_map = {
            "friendly_name": ("name", str),
            "screensaver_mode": ("screensaver_mode", int),
            "screensaver_activation_timeout": ("screensaver_activation_timeout", int),
            "min_button_push_time": ("min_button_push_time", int),
            "button_long_press_time": ("button_long_press_time", int),
            "special_mode_trigger_time": ("special_mode_trigger_time", int),
            "special_mode_release_time": ("special_mode_release_time", int),
            "screen_dim_level": ("screen_dim_level", int),
            "screensaver_dim_level": ("screensaver_dim_level", int),
            "temperature_calibration": ("temperature_calibration", int),
            "default_page": ("default_page", int),
            "default_light_brightness": ("default_light_brightness", int),
        }
        for form_key, (attr, typ) in field_map.items():
            if form_key in form:
                try:
                    setattr(panel, attr, typ(form[form_key]))
                except (ValueError, TypeError):
                    pass
        for flag in ("clock_us_style", "use_fahrenheit", "is_us_panel",
                     "reverse_relays", "relay1_default_mode", "relay2_default_mode",
                     "optimistic_mode"):
            panel.__setattr__(flag, flag in form)
        if "room_id" in form:
            try:
                panel.room_id = int(form["room_id"])
            except (ValueError, TypeError):
                pass
        await manager.async_save()
        await manager._send_panel_config(panel)
        raise web.HTTPFound(f"{URL_BASE}")


class GlobalScenesView(HomeAssistantView):
    url = f"{URL_BASE}/global_scenes"
    name = "nspanel_core:global_scenes"
    requires_auth = False

    async def get(self, request):
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

    async def get(self, request):
        manager = _manager(request)
        html = _render(
            "relay_groups.html",
            relay_groups=[],
            page_title="Relay/Light groups",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class WeatherTimeView(HomeAssistantView):
    url = f"{URL_BASE}/weather_and_time"
    name = "nspanel_core:weather_time"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        s = manager.config.settings
        html = _render(
            "weather_and_time.html",
            settings={
                "location_latitude": s.location_latitude,
                "location_longitude": s.location_longitude,
                "weather_update_interval": s.weather_update_interval,
                "clock_us_style": s.clock_us_style,
                "date_format": s.date_format,
                "use_fahrenheit": s.use_fahrenheit,
            },
            page_title="Weather & Time",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class DeniedPanelsView(HomeAssistantView):
    url = f"{URL_BASE}/denied_nspanels"
    name = "nspanel_core:denied"
    requires_auth = False

    async def get(self, request):
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

    async def get(self, request):
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
            screen_dim_level=0,
            screensaver_dim_level=20,
            screensaver_mode=0,
            show_screensaver_inside_temperature=True,
            show_screensaver_outside_temperature=True,
            light_turn_on_brightness=s.light_turn_on_brightness,
            room_status_backoff_time=0,
            all_rooms_status_backoff_time=0,
            max_live_log_messages=100,
            max_log_buffer_size=1000,
            is_home_assistant_addon=True,
            default_nspanel_type="sonoff",
            themes=themes,
            theme="nspmwip",
            page_title="Settings",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


class ManagerSettingsView(HomeAssistantView):
    url = f"{URL_BASE}/manager_settings"
    name = "nspanel_core:manager_settings"
    requires_auth = False

    async def get(self, request):
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


class DownloadFirmwareView(HomeAssistantView):
    url = f"{URL_BASE}/download_firmware"
    name = "nspanel_core:download_firmware"
    requires_auth = False

    async def get(self, request):
        model = request.query.get("model", "sonoff")
        if model not in ("sonoff", "custom"):
            return web.Response(status=400, text="Unknown model")
        path = _os.path.join(_firmware_dir(), model, "firmware.bin")
        if not _os.path.exists(path):
            return web.Response(status=404, text="Not found")
        return web.FileResponse(path)


class DownloadDataFileView(HomeAssistantView):
    url = f"{URL_BASE}/download_data_file"
    name = "nspanel_core:download_data_file"
    requires_auth = False

    async def get(self, request):
        model = request.query.get("model", "sonoff")
        if model not in ("sonoff", "custom"):
            return web.Response(status=400, text="Unknown model")
        path = _os.path.join(_firmware_dir(), model, "data_file.bin")
        if not _os.path.exists(path):
            return web.Response(status=404, text="Not found")
        return web.FileResponse(path)


class ChecksumFirmwareView(HomeAssistantView):
    url = f"{URL_BASE}/checksum_firmware"
    name = "nspanel_core:checksum_firmware"
    requires_auth = False

    async def get(self, request):
        model = request.query.get("model", "sonoff")
        if model not in ("sonoff", "custom"):
            return web.Response(status=400, text="Unknown model")
        path = _os.path.join(_firmware_dir(), model, "firmware.bin")
        if not _os.path.exists(path):
            return web.Response(status=404, text="Not found")
        return web.Response(text=_md5(path))


class ChecksumDataFileView(HomeAssistantView):
    url = f"{URL_BASE}/checksum_data_file"
    name = "nspanel_core:checksum_data_file"
    requires_auth = False

    async def get(self, request):
        model = request.query.get("model", "sonoff")
        if model not in ("sonoff", "custom"):
            return web.Response(status=400, text="Unknown model")
        path = _os.path.join(_firmware_dir(), model, "data_file.bin")
        if not _os.path.exists(path):
            return web.Response(status=404, text="Not found")
        return web.Response(text=_md5(path))


def _md5(path: str) -> str:
    h = _hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()




class DownloadTftView(HomeAssistantView):
    url = f"{URL_BASE}/download_tft/{{panel_id}}"
    name = "nspanel_core:download_tft"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        panel_id = int(request.match_info["panel_id"])
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(status=404, text="Panel not found")
        tft_dir = _os.path.join(_os.path.dirname(__file__), "tft")
        # US panels use gui_us.tft
        filename = "gui_us.tft" if panel.is_us_panel else "gui.tft"
        path = _os.path.join(tft_dir, filename)
        if not _os.path.exists(path):
            return web.Response(status=404, text="TFT not found")
        return web.FileResponse(path)


class ChecksumTftView(HomeAssistantView):
    url = f"{URL_BASE}/checksum_tft_file/{{panel_id}}"
    name = "nspanel_core:checksum_tft"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        panel_id = int(request.match_info["panel_id"])
        panel = next((p for p in manager.config.panels if p.id == panel_id), None)
        if panel is None:
            return web.Response(status=404, text="Panel not found")
        tft_dir = _os.path.join(_os.path.dirname(__file__), "tft")
        filename = "gui_us.tft" if panel.is_us_panel else "gui.tft"
        path = _os.path.join(tft_dir, filename)
        if not _os.path.exists(path):
            return web.Response(status=404, text="TFT not found")
        return web.Response(text=_md5(path))


class ComingSoonView(HomeAssistantView):
    """Catch-all under /nspanel_core/* — never leaks the HA frontend into the
    iframe (this caused the 'doubled page' when clicking unported links)."""

    url = f"{URL_BASE}/{{tail:.*}}"
    name = "nspanel_core:catchall"
    requires_auth = False

    async def get(self, request):
        html = _render(
            "index_shell.html",
            page_title="This page is being ported",
            nspanels=[],
        )
        return web.Response(text=html, content_type="text/html")


class RoomsPageView(HomeAssistantView):
    url = f"{URL_BASE}/rooms"
    name = "nspanel_core:rooms"
    requires_auth = False

    async def get(self, request):
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

    async def get(self, request):
        manager = _manager(request)
        room_id = int(request.match_info["room_id"])
        room = next((r for r in manager.config.rooms if r.id == room_id), None)
        if room is None:
            raise web.HTTPFound(f"{URL_BASE}/rooms")
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


class SaveNewRoomView(HomeAssistantView):
    url = f"{URL_BASE}/save_new_room"
    name = "nspanel_core:save_new_room"
    requires_auth = False

    async def post(self, request):
        manager = _manager(request)
        form = await request.post()
        name = str(form.get("friendly_name", "")).strip()
        if name:
            await manager.add_room(name)
        raise web.HTTPFound(f"{URL_BASE}/rooms")


class DeleteRoomView(HomeAssistantView):
    url = f"{URL_BASE}/api/rooms/{{room_id}}/delete"
    name = "nspanel_core:api:room_delete2"
    requires_auth = False

    async def post(self, request):
        manager = _manager(request)
        await manager.remove_room(int(request.match_info["room_id"]))
        raise web.HTTPFound(f"{URL_BASE}/rooms")


class RestartView(HomeAssistantView):
    url = f"{URL_BASE}/api/restart"
    name = "nspanel_core:api:restart"
    requires_auth = False

    async def post(self, request):
        manager = _manager(request)
        await manager.async_stop()
        await manager.async_start()
        return web.Response(text="", status=200)


class ThemeView(HomeAssistantView):
    url = f"{URL_BASE}/api/theme"
    name = "nspanel_core:api:theme"
    requires_auth = False

    async def post(self, request):
        # Theme switching is ported with the settings page.
        return web.Response(text="", status=200)


class MessagesView(HomeAssistantView):
    url = f"{URL_BASE}/api/messages"
    name = "nspanel_core:api:messages"
    requires_auth = False

    async def get(self, request):
        return web.Response(text="", status=200)


class StompView(HomeAssistantView):
    """The STOMP WebSocket endpoint (the UI's live data connection)."""

    url = f"{URL_BASE}/ws"
    name = "nspanel_core:ws"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        return await manager.stomp.handle_ws(request)


class WebappStompView(HomeAssistantView):
    """STOMP WebSocket at the original /websocket/stomp path (for the web app)."""

    url = "/websocket/stomp"
    name = "nspanel_core:webapp_ws"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        return await manager.stomp.handle_ws(request)


class WebappIndexView(HomeAssistantView):
    """Serve the web app's index.html at /webapp."""

    url = "/webapp"
    name = "nspanel_core:webapp_index"
    requires_auth = False

    async def get(self, request):
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

    async def get(self, request):
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


class WebappStompView(HomeAssistantView):
    """STOMP WebSocket at the original /websocket/stomp path (for the web app)."""

    url = "/websocket/stomp"
    name = "nspanel_core:webapp_ws"
    requires_auth = False

    async def get(self, request):
        manager = _manager(request)
        return await manager.stomp.handle_ws(request)


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


    # Register routes directly via aiohttp (HomeAssistantView.register is
    # fragile across HA versions — it crashed on list-valued urls in 2026.10).
    views = [
        (MainPageView, ["GET"]),
        (HtmxNspanelsSectionView, ["GET"]),
        (PanelActionView, ["POST", "DELETE"]),
        (EditPanelView, ["GET"]),
        (SavePanelSettingsView, ["POST"]),
        (RoomsPageView, ["GET"]),
        (EditRoomView, ["GET"]),
        (SaveNewRoomView, ["POST"]),
        (DeleteRoomView, ["POST"]),
        (GlobalScenesView, ["GET"]),
        (RelayGroupsView, ["GET"]),
        (WeatherTimeView, ["GET"]),
        (DeniedPanelsView, ["GET"]),
        (SettingsView, ["GET"]),
        (ManagerSettingsView, ["GET"]),
        (PlaceholderPageView, ["GET"]),
        (RestartView, ["POST"]),
        (ThemeView, ["POST"]),
        (MessagesView, ["GET"]),
        (StompView, ["GET"]),
        (WebappStompView, ["GET"]),
        (WebappIndexView, ["GET"]),
        (WebappAssetView, ["GET"]),
        (ComingSoonView, ["GET"]),
    ]
    for view_cls, methods in views:
        view = view_cls()
        for method in methods:
            handler = getattr(view, method.lower(), None)
            if handler is None:
                continue
            try:
                hass.http.app.router.add_route(method, view.url, handler)
            except RuntimeError:
                # Route already registered (e.g. by static path) — skip
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
                module_url=f"{URL_BASE}/static/panel.js",
                embed_iframe=True,
                config={"url": URL_BASE},
                require_admin=True,
            )
            _LOGGER.info("NSPanel Core sidebar panel registered at %s", URL_BASE)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to register NSPanel Core sidebar panel")

    hass.async_create_task(_register_sidebar_panel())

    hass.data[f"{DOMAIN}_entry_id"] = entry_id
    _LOGGER.info("NSPanel Core UI registered at %s", URL_BASE)
