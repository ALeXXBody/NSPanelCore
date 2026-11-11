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

    for view in (
        MainPageView(),
        HtmxNspanelsSectionView(),
        PanelActionView(),
        RestartView(),
        ThemeView(),
        MessagesView(),
        StompView(),
    ):
        hass.http.register_view(view)

    from homeassistant.components.http import StaticPathConfig

    hass.loop.call_soon_threadsafe(
        asyncio.create_task,
        hass.http.async_register_static_paths(
            [StaticPathConfig(f"{URL_BASE}/static", str(STATIC_DIR), cache_headers=True)]
        ),
    )

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
