"""NSPanel Core — management dashboard (v2).

Serves the panels-management UI at /nspanel_core/ui and registers the
sidebar entry (panel_custom + iframe shim, same pattern as v1).
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = "/nspanel_core"
_DASHBOARD_VERSION = "v0.1.0"

_VIEW_HASS = {"hass": None, "core": None}


def _core():
    return _VIEW_HASS["core"]


_PAGE_HEAD = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>NSPanel Core</title><style>
body{font:14px/1.5 system-ui;max-width:860px;margin:24px auto;padding:0 16px;
background:#0d1016;color:#c8cbce}
h1{font-size:20px}h1 span{color:#39c8e8}
table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #232c3b}
th{color:#8b93a1;font-size:12px;text-transform:uppercase}
.badge{padding:2px 8px;border-radius:10px;font-size:12px}
.on{background:#1b3a2a;color:#5ad48a}.off{background:#3a1b1b;color:#e07a7a}
button{padding:5px 10px;margin:0 2px;background:#2277aa;color:#fff;border:0;
border-radius:6px;font-size:13px;cursor:pointer}
button.warn{background:#7a2222}button.ghost{background:#232c3b;color:#c8cbce}
.note{color:#8b93a1;font-size:13px}</style></head>
<body><h1>NSPanel <span>Core</span> <small class=note>__VERSION__</small></h1>
<p class=note>Panels register automatically. Firmware updates push the
currently-activated verified build (set: Home Assistant → device → configure).</p>
<table><tr><th>Name</th><th>Version</th><th>State</th><th>IP</th><th>Actions</th></tr>
"""


def _render_panels() -> str:
    core = _core()
    if core is None:
        return "<tr><td colspan=5>Core not ready</td></tr>"
    rows = []
    for p in core.config.panels:
        name = html.escape(p.name or p.wifi_hostname or p.mac)
        state = (
            '<span class="badge on">online</span>'
            if p.online
            else '<span class="badge off">offline</span>'
        )
        ver = html.escape(p.version)
        ip = html.escape(p.ip or "—")
        pid = p.id
        actions = []
        if not p.accepted:
            actions.append(f'<button onclick=act("{pid}","accept")>Accept</button>')
            actions.append(f'<button class=warn onclick=act("{pid}","deny")>Deny</button>')
        else:
            actions.append(f'<button onclick=act("{pid}","update_firmware")>FW update</button>')
            actions.append(f'<button class=ghost onclick=act("{pid}","reboot")>Reboot</button>')
            actions.append(f'<button class=warn onclick=act("{pid}","delete")>Delete</button>')
        rows.append(
            f"<tr><td>{name}</td><td>{ver}</td><td>{state}</td><td>{ip}</td>"
            f"<td>{''.join(actions)}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan=5>No panels yet</td></tr>')
    return "\n".join(rows)


_PAGE_SCRIPT = """<script>
async function act(id, action){
  if(action==="delete" && !confirm("Delete this panel? It can re-register later.")) return;
  await fetch("%s/api/panel/"+id+"/"+action, {method:"POST"});
  location.reload();
}
</script>"""


class DashboardPage(HomeAssistantView):
    """The management UI (sidebar iframe target)."""

    url = f"{URL_BASE}/ui"
    name = "nspanel_core:dashboard"
    requires_auth = True

    async def get(self, request, **kwargs):
        page = (
            _PAGE_HEAD.replace("__VERSION__", _DASHBOARD_VERSION)
            + _render_panels()
            + "</table>"
            + (_PAGE_SCRIPT % URL_BASE)
            + "</body></html>"
        )
        return web.Response(text=page, content_type="text/html")


class PanelAction(HomeAssistantView):
    """POST /nspanel_core/api/panel/{panel_id}/{action}."""

    url = f"{URL_BASE}/api/panel/{{panel_id}}/{{action}}"
    name = "nspanel_core:api:panel_action"
    requires_auth = True

    async def post(self, request, **kwargs):
        core = _core()
        if core is None:
            return web.Response(text="Core not ready", status=503)
        panel_id = kwargs.get("panel_id", "")
        action = kwargs.get("action", "")
        panel = next((p for p in core.config.panels if str(p.id) == panel_id), None)
        if panel is None:
            return web.Response(text="Panel not found", status=404)

        if action == "accept":
            panel.accepted, panel.denied = True, False
        elif action == "deny":
            panel.accepted, panel.denied = False, True
        elif action == "delete":
            # In-memory removal; the panel can re-register (it will appear
            # unaccepted again — the persistence layer is a later parity item).
            core.config.panels.remove(panel)
        elif action == "update_firmware":
            core.send_firmware_update(panel)
        elif action == "update_tft":
            core.send_tft_update(panel)
        elif action == "reboot":
            core.send_reboot(panel)
        elif action == "display_restart":
            core.send_command(panel, "display_restart")
        else:
            return web.Response(text="Unknown action", status=400)
        return web.Response(status=200)


def register_dashboard(hass: HomeAssistant) -> None:
    """Register static assets, the UI page, the action endpoint and the sidebar."""
    _VIEW_HASS["hass"] = hass
    _VIEW_HASS["core"] = _get_core(hass)

    async def _register() -> None:
        from homeassistant.components.frontend import async_remove_panel
        from homeassistant.components.panel_custom import async_register_panel

        from homeassistant.components.http import StaticPathConfig

        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(f"{URL_BASE}/static", str(static_dir))]
        )
        hass.http.register_view(DashboardPage())
        hass.http.register_view(PanelAction())
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
                module_url=f"{URL_BASE}/static/panel.js?v={_DASHBOARD_VERSION}",
                embed_iframe=True,
                config={"url": f"{URL_BASE}/ui"},
                require_admin=True,
            )
            _LOGGER.info("NSPanel Core dashboard registered at %s", URL_BASE)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to register NSPanel Core sidebar panel")

    hass.async_create_task(_register())


def _get_core(hass: HomeAssistant):
    data = hass.data.get(DOMAIN) or {}
    if not data:
        return None
    entry_id = next(iter(data))
    return data[entry_id].get("core")
