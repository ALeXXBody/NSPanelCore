"""NSPanel Core management dashboard.

A web UI served by the integration itself (aiohttp views registered on HA's
HTTP server) and pinned to the HA sidebar. This is the in-integration
replacement for the old add-on's management pages.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = "/nspanel_core"


class DashboardView(HomeAssistantView):
    """The management dashboard page."""

    url = URL_BASE
    name = "nspanel_core:dashboard"
    requires_auth = True

    async def get(self, request):
        html = _dashboard_html()
        return web.Response(text=html, content_type="text/html")


class ApiStateView(HomeAssistantView):
    url = f"{URL_BASE}/api/state"
    name = "nspanel_core:api:state"
    requires_auth = True

    async def get(self, request):
        manager = request.app["hass"].data[DOMAIN][request.query["entry"]]
        return web.json_response(manager.export_state())


class ApiHALightsView(HomeAssistantView):
    url = f"{URL_BASE}/api/ha_lights"
    name = "nspanel_core:api:ha_lights"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        lights = [
            {"entity_id": s.entity_id, "name": s.attributes.get("friendly_name", s.entity_id)}
            for s in hass.states.async_all("light")
        ]
        lights.sort(key=lambda x: x["name"])
        return web.json_response(lights)


class ApiRoomsView(HomeAssistantView):
    url = f"{URL_BASE}/api/rooms"
    name = "nspanel_core:api:rooms"
    requires_auth = True

    async def post(self, request):
        manager = _manager(request)
        body = await request.json()
        await manager.add_room(body.get("name", "New room"))
        return web.json_response({"ok": True})


class ApiRoomDeleteView(HomeAssistantView):
    url = f"{URL_BASE}/api/rooms/{{room_id}}"
    name = "nspanel_core:api:room_delete"
    requires_auth = True

    async def delete(self, request):
        manager = _manager(request)
        await manager.remove_room(int(request.match_info["room_id"]))
        return web.json_response({"ok": True})


class ApiLightsView(HomeAssistantView):
    url = f"{URL_BASE}/api/lights"
    name = "nspanel_core:api:lights"
    requires_auth = True

    async def post(self, request):
        manager = _manager(request)
        body = await request.json()
        await manager.add_light(
            name=body.get("name", ""),
            ha_entity=body.get("ha_entity", ""),
            room_id=int(body.get("room_id", 0)),
            page_id=int(body.get("page_id", 0)),
            page_slot=int(body.get("page_slot", 0)),
            light_type=body.get("light_type", "table"),
            can_dim=bool(body.get("can_dim")),
            can_color_temperature=bool(body.get("can_color_temperature")),
            can_rgb=bool(body.get("can_rgb")),
        )
        return web.json_response({"ok": True})


class ApiLightDeleteView(HomeAssistantView):
    url = f"{URL_BASE}/api/lights/{{light_id}}"
    name = "nspanel_core:api:light_delete"
    requires_auth = True

    async def delete(self, request):
        manager = _manager(request)
        await manager.remove_light(int(request.match_info["light_id"]))
        return web.json_response({"ok": True})


class ApiPanelsView(HomeAssistantView):
    url = f"{URL_BASE}/api/panels/{{panel_id}}"
    name = "nspanel_core:api:panels"
    requires_auth = True

    async def post(self, request):
        manager = _manager(request)
        body = await request.json()
        await manager.update_panel(int(request.match_info["panel_id"]), body)
        return web.json_response({"ok": True})

    async def delete(self, request):
        manager = _manager(request)
        await manager.remove_panel(int(request.match_info["panel_id"]))
        return web.json_response({"ok": True})


class ApiSettingsView(HomeAssistantView):
    url = f"{URL_BASE}/api/settings"
    name = "nspanel_core:api:settings"
    requires_auth = True

    async def post(self, request):
        manager = _manager(request)
        body = await request.json()
        await manager.apply_settings(body)
        return web.json_response({"ok": True})


def _manager(request) -> Any:
    hass: HomeAssistant = request.app["hass"]
    entry_id = request.query.get("entry") or next(iter(hass.data[DOMAIN]))
    return hass.data[DOMAIN][entry_id]


from typing import Any  # noqa: E402  (used above)


def async_register_views(hass: HomeAssistant, entry_id: str) -> None:
    """Register the dashboard + API views and the sidebar panel."""
    hass.http.app["hass"] = hass  # aiohttp app reference for views
    for view in (
        DashboardView,
        ApiStateView,
        ApiHALightsView,
        ApiRoomsView,
        ApiRoomDeleteView,
        ApiLightsView,
        ApiLightDeleteView,
        ApiPanelsView,
        ApiSettingsView,
    ):
        hass.http.register_view(view())

    from homeassistant.components.frontend import async_register_built_in_panel

    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="NSPanel Core",
        sidebar_icon="mdi:tablet-dashboard",
        frontend_url_path="nspanel_core",
        config={"url": URL_BASE},
        require_admin=True,
    )
    # Expose the entry id to the frontend via the state endpoint query default.
    hass.data[f"{DOMAIN}_entry_id"] = entry_id
    _LOGGER.info("NSPanel Core dashboard registered at %s", URL_BASE)


def _dashboard_html() -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8">
<title>NSPanel Core</title>
<style>
:root{--bg:#0d1016;--surface:#141922;--accent:#39c8e8;--text:#e8edf2;--muted:#8c96a0}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;padding:20px;max-width:1000px;margin:auto}
h1{font-size:22px;margin-bottom:4px}h1 span{color:var(--accent)}
h2{font-size:15px;color:var(--muted);margin:26px 0 10px;text-transform:uppercase;letter-spacing:1px}
.card{background:var(--surface);border:1px solid #ffffff14;border-radius:12px;padding:14px;margin-bottom:10px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input,select{background:#0b0e13;border:1px solid #ffffff22;color:var(--text);border-radius:8px;padding:8px 10px;min-width:140px}
button{background:var(--accent);color:#04222b;border:none;border-radius:8px;padding:8px 14px;font-weight:600;cursor:pointer}
button.danger{background:#e05555;color:#fff}
button.ghost{background:transparent;color:var(--muted);border:1px solid #ffffff22}
table{width:100%;border-collapse:collapse}
td,th{padding:7px 8px;border-bottom:1px solid #ffffff10;text-align:left}
.tag{background:#39c8e822;color:var(--accent);border-radius:6px;padding:2px 8px;font-size:12px}
.muted{color:var(--muted);font-size:13px}
#msg{position:fixed;bottom:16px;right:16px;background:var(--accent);color:#04222b;padding:10px 16px;border-radius:10px;display:none;font-weight:600}
</style></head>
<body>
<h1>NSPanel <span>Core</span></h1>
<div class="muted">Native Home Assistant integration — panels register automatically on MQTT.</div>

<h2>Panels</h2>
<div id="panels"></div>

<h2>Rooms</h2>
<div class="card row">
<input id="room-name" placeholder="Room name">
<button onclick="addRoom()">Add room</button>
</div>
<div id="rooms"></div>

<h2>Light mapping</h2>
<div class="card">
<div class="row">
<input id="light-name" placeholder="Panel name">
<select id="light-entity"></select>
<select id="light-room"></select>
<select id="light-page"></select>
<input id="light-slot" type="number" min="1" max="12" placeholder="Slot">
<select id="light-type"><option value="table">Table</option><option value="ceiling">Ceiling</option></select>
<label><input type="checkbox" id="light-dim"> Dim</label>
<label><input type="checkbox" id="light-ct"> Color temp</label>
<label><input type="checkbox" id="light-rgb"> RGB</label>
<button onclick="addLight()">Map light</button>
</div>
</div>
<div id="lights"></div>

<h2>Global settings</h2>
<div class="card row">
<input id="set-manager" placeholder="Manager address">
<input id="set-ctmin" type="number" placeholder="CT min (K)">
<input id="set-ctmax" type="number" placeholder="CT max (K)">
<input id="set-lat" placeholder="Latitude">
<input id="set-lon" placeholder="Longitude">
<button onclick="saveSettings()">Save</button>
</div>

<div id="msg"></div>
<script>
const E = id => document.getElementById(id);
async function api() {
  const r = await fetch(window.location.pathname + '/api/state');
  return r.json();
}
function msg(t){const m=E('msg');m.textContent=t;m.style.display='block';setTimeout(()=>m.style.display='none',2500);}
async function post(url, body, method='POST'){
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  if (!r.ok) { msg('Error ' + r.status); throw new Error(await r.text()); }
  return r.json();
}
async function refresh(){
  const s = await api();
  const st = s.settings;
  E('set-manager').value = st.manager_address || '';
  E('set-ctmin').value = st.color_temp_min || 2700;
  E('set-ctmax').value = st.color_temp_max || 6500;
  E('set-lat').value = st.location_latitude || '';
  E('set-lon').value = st.location_longitude || '';

  // panels
  E('panels').innerHTML = (s.panels||[]).map(p =>
    `<div class="card row"><b>${p.name}</b>
     <span class="tag">${p.online ? 'online' : 'offline'}</span>
     <span class="muted">${p.mac}</span>
     <span class="muted">room: ${p.room_id || '—'}</span>
     <label>accepted <input type="checkbox" ${p.accepted?'checked':''} onchange="post(`/api/nspanel_core/api/panels/${p.id}`,{accepted:this.checked}).then(refresh)"></label>
     <button class="danger" onclick="post(`/api/nspanel_core/api/panels/${p.id}`,{},'DELETE').then(refresh)">Remove</button>
     </div>`).join('') || '<div class="muted">No panels yet — power-cycle a panel to register it.</div>';

  // rooms
  E('rooms').innerHTML = (s.rooms||[]).map(r =>
    `<div class="card row"><b>#${r.id}</b> ${r.name}
     <button class="ghost" onclick="post(`/api/nspanel_core/api/rooms/${r.id}`,{},'DELETE').then(refresh)">Delete</button>
     </div>`).join('') || '<div class="muted">No rooms yet.</div>';
  E('light-room').innerHTML = (s.rooms||[]).map(r => `<option value="${r.id}">${r.name}</option>`).join('');
  E('light-page').innerHTML = (s.pages||[]).filter(p=>!p.is_scenes_page).map(p => `<option value="${p.id}">#${p.id}</option>`).join('');

  // lights
  E('lights').innerHTML = '<table><tr><th>Name</th><th>HA entity</th><th>Room</th><th>Page/Slot</th><th></th></tr>' +
    (s.lights||[]).map(l => `<tr><td>${l.name}</td><td class="muted">${l.ha_entity}</td>
     <td>${(s.rooms||[]).find(r=>r.id===l.room_id)?.name||'—'}</td>
     <td class="muted">#${l.page_id}/${l.page_slot}</td>
     <td><button class="danger" onclick="post(`/api/nspanel_core/api/lights/${l.id}`,{},'DELETE').then(refresh)">✕</button></td></tr>`).join('') + '</table>'
    || '<div class="muted">No lights mapped.</div>';
}
async function addRoom(){ await post('/api/nspanel_core/api/rooms', {name: E('room-name').value}); E('room-name').value=''; refresh(); }
async function addLight(){
  await post('/api/nspanel_core/api/lights', {
    name: E('light-name').value, ha_entity: E('light-entity').value,
    room_id: E('light-room').value, page_id: E('light-page').value, page_slot: E('light-slot').value,
    light_type: E('light-type').value, can_dim: E('light-dim').checked,
    can_color_temperature: E('light-ct').checked, can_rgb: E('light-rgb').checked,
  });
  E('light-name').value=''; refresh();
}
async function saveSettings(){
  await post('/api/nspanel_core/api/settings', {
    manager_address: E('set-manager').value, color_temp_min: +E('set-ctmin').value,
    color_temp_max: +E('set-ctmax').value, location_latitude: E('set-lat').value,
    location_longitude: E('set-lon').value,
  });
  msg('Saved');
}
(async () => {
  const lights = await (await fetch('/nspanel_core/api/ha_lights')).json();
  E('light-entity').innerHTML = lights.map(l => `<option value="${l.entity_id}">${l.name} (${l.entity_id})</option>`).join('');
  await refresh();
})();
</script>
</body></html>"""
