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

URL_BASE = "/nspanel_core"

UI_DIR = pathlib.Path(__file__).parent / "ui"
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"


def _render(template_name: str, **context) -> str:
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template(template_name)
    context.setdefault("notifications", [])
    context.setdefault("version", "1.0.0")
    context.setdefault("enabled_themes", {"nspmwip": "NSPanel Core (dark)"} )
    context.setdefault("theme", "nspmwip")
    context.setdefault("current_theme", "nspmwip")
    context.setdefault("theme_mode", "dark")
    context.setdefault("ingress_path", "")
    context.setdefault("request", type("R", (), {"path": context.get("current_path", "/")})())
    return template.render(**context)


def _manager(request) -> Any:
    hass: HomeAssistant = request.app["hass"]
    entry_id = hass.data.get(f"{DOMAIN}_entry_id") or next(iter(hass.data[DOMAIN]))
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
        panel_info = {"data": panel_dict}
        nspanel = {"data": panel_dict}
        rooms = [{"id": r.id, "name": r.name} for r in manager.config.rooms]
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
            settings={
                "manager_address": s.manager_address,
                "manager_port": s.manager_port,
                "mqtt_server": s.mqtt_server,
                "mqtt_port": s.mqtt_port,
                "mqtt_username": s.mqtt_username,
                "mqtt_password": s.mqtt_password,
                "mqttmanager_log_level": s.mqttmanager_log_level,
                "color_temp_min": s.color_temp_min,
                "color_temp_max": s.color_temp_max,
                "reverse_color_temp": s.reverse_color_temp,
                "optimistic_mode": s.optimistic_mode,
                "turn_on_light_behaviour": s.turn_on_behaviour,
                "theme": "nspmwip",
            },
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
        html = _render(
            "manager_settings.html",
            page_title="Manager settings",
            nspanels=_panels_context(manager),
        )
        return web.Response(text=html, content_type="text/html")


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

    # Register routes directly via aiohttp (HomeAssistantView.register is
    # fragile across HA versions — it crashed on list-valued urls in 2026.10).
    views = [
        (MainPageView, ["GET"]),
        (HtmxNspanelsSectionView, ["GET"]),
        (PanelActionView, ["POST", "DELETE"]),
        (EditPanelView, ["GET"]),
        (SavePanelSettingsView, ["POST"]),
        (RoomsPageView, ["GET"]),
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
        (ComingSoonView, ["GET"]),
    ]
    for view_cls, methods in views:
        view = view_cls()
        for method in methods:
            handler = getattr(view, method.lower(), None)
            if handler is None:
                continue
            hass.http.app.router.add_route(method, view.url, handler)

    from homeassistant.components.frontend import async_register_built_in_panel

    async_register_built_in_panel(
        hass,
        update=hass.data.get(f"{DOMAIN}_panel_registered", False),
        component_name="iframe",
        sidebar_title="NSPanel Core",
        sidebar_icon="mdi:tablet-dashboard",
        frontend_url_path="nspanel_core",
        config={"url": URL_BASE},
        require_admin=True,
    )
    hass.data[f"{DOMAIN}_entry_id"] = entry_id
    hass.data[f"{DOMAIN}_panel_registered"] = True
    _LOGGER.info("NSPanel Core UI registered at %s", URL_BASE)
