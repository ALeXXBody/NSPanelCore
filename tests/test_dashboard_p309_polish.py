"""P309 — studio polish: photo auth for <img>, uniform page-row buttons,
tab-ordered step numbers, HA-entity labels on the detached buttons, and the
deleted panel drawing.

The user's report: a photo that loaded for every fetch but not for the <img>
("The photo on \"Page\" could not be loaded"), a cyan + next to a bigger gray ✕,
the screensaver step still numbered 5 while being the first tab, the detached
Entity select not visibly pointing at HA entities, and a dead panel drawing in
Panel type & orientation.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.models import IntegrationConfig, LightConfig, PanelConfig, RoomConfig  # noqa: E402

HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html").read_text()
_FIELDS = (REPO / "custom_components" / "nspanel_core" / "ui" /
           "templates" / "_panel_settings_fields.html").read_text()
_NODE = shutil.which("node")
_TOP_FN = re.compile(r"^function (\w+)\s*\(", re.M)


def _functions():
    spans = [(m.group(1), m.start()) for m in _TOP_FN.finditer(HTML)]
    return {name: HTML[start:(spans[i + 1][1] if i + 1 < len(spans) else len(HTML))]
            for i, (name, start) in enumerate(spans)}


_FNS = _functions()


def _js(*names):
    return "\n".join(_FNS[n] for n in names) + "\n"


def _node_run(script):
    if not _NODE:
        import pytest
        pytest.skip("node not available for inline-JS behavior tests")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ------------------------------------------------------- step numbering

def test_steps_are_numbered_in_tab_order():
    steps = re.findall(
        r'<span class="studio-step-num">(\d+)</span><span class="studio-step-title">([^<]+)</span>',
        HTML)
    titles = [s[1] for s in steps]
    assert titles == ["Build the screensaver", "Pages", "Photos",
                      "Items (what sits on the photo)", "Panel hardware"]
    assert [int(s[0]) for s in steps] == [1, 2, 3, 4, 5]
    # the numbered steps live in the tab order the user asked for
    assert HTML.index("Build the screensaver</div>") < HTML.index(">Build the dashboard</div>")
    assert HTML.index(">Build the dashboard</div>") < HTML.index(">Panel hardware</div>")


# ------------------------------------------------------ page-row buttons

def test_the_add_and_delete_row_buttons_look_the_same():
    render = _FNS["renderPages"]
    plus = re.search(r'<button class="([^"]*)" style="([^"]*)" onclick="addPage', render)
    cross = re.search(r'<button class="([^"]*)" style="([^"]*)" onclick="deletePage', render)
    assert plus and cross, "both row buttons must carry class + style"
    assert plus.group(1) == cross.group(1)          # same size classes
    assert plus.group(2) == cross.group(2)          # same inline sizing/color
    # the old mismatched styling is gone
    assert 'style="color:#39c8e8" onclick="addPage' not in render
    assert 'is-danger" onclick="deletePage' not in render


# ------------------------------------------------------- photo auth token

def test_img_urls_carry_the_live_ha_token():
    assert "function photoAuth(" in HTML
    for builder in ('&variant=dash&r=' + "' + Date.now() + photoAuth()",
                    '&variant=scr&r=' + "' + Date.now() + photoAuth()",
                    "'&photo=' + encodeURIComponent(p.name) + photoAuth()"):
        assert builder in HTML, builder


def test_photo_auth_appends_the_token_only_when_one_exists():
    script = _js("photoAuth") + """
var nspanelGetToken = function () { return 'live-token-abc'; };
var withToken = photoAuth();
nspanelGetToken = function () { return ''; };
var withoutToken = photoAuth();
nspanelGetToken = function () { throw new Error('boom'); };
var onThrow = photoAuth();
console.log(JSON.stringify({ withToken: withToken, withoutToken: withoutToken, onThrow: onThrow }));
"""
    out = _node_run(script)
    assert out["withToken"] == "&ha_token=live-token-abc"
    assert out["withoutToken"] == ""
    assert out["onThrow"] == ""


# ------------------------------------------- detached Entity points at HA

def _render_panel_settings(manager, panel_id=7):
    class Req:
        def __init__(self):
            self.app = {"hass": SimpleNamespace(
                data={f"{DOMAIN}_entry_id": "entry", DOMAIN: {"entry": manager}})}
            self.query = {"panel_id": str(panel_id)}
            self.headers = {"Cookie": "nspanel_session=sess"}
            self.match_info = {}

    resp = _run(D.DashboardPanelSettingsView().get(Req()))
    assert resp.status == 200
    return resp.text


def test_detached_entity_options_name_the_ha_entity():
    """P312 REWORK: the detached binding is a Home Assistant entity selected
    DIRECTLY from the live entity list — the lights-in-rooms detour (room
    select + manager-light options) is gone, replaced by the direct entity
    dropdown the JS loader fills from /api/get_all_available_entities."""
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    room = RoomConfig(id=1, name="Living")
    cfg.rooms.append(room)
    cfg.lights.append(LightConfig(id=5, name="Ceiling Light",
                                  ha_entity="light.ceiling_light",
                                  room_id=1, page_id=0, page_slot=0))
    cfg.panels.append(PanelConfig(id=7, mac="aabbcc", name="Kitchen",
                                  room_id=1, accepted=True,
                                  button1_detached_entity="switch.coffee"))
    manager = MagicMock()
    manager.config = cfg
    manager.panels.return_value = list(cfg.panels)
    manager.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda: []))
    html = _render_panel_settings(manager)
    # the DIRECT entity binding renders as data-current for the loader
    assert 'data-current="switch.coffee"' in html
    # the lights-in-rooms detour is GONE
    assert 'button1_detached_mode_room' not in html
    assert 'button1_detached_mode_light' not in html
    assert "No lights are registered yet" not in html


def test_detached_binding_carries_the_ha_entity():
    """The stored binding is the HA entity_id itself (P312) — and legacy
    light-id bindings still render/round-trip untouched."""
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    cfg.panels.append(PanelConfig(id=7, mac="aabbcc", name="Kitchen",
                                  room_id=1, accepted=True,
                                  button1_detached_light=5))
    manager = MagicMock()
    manager.config = cfg
    manager.panels.return_value = list(cfg.panels)
    manager.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda: []))
    html = _render_panel_settings(manager)
    assert 'data-current=""' in html  # no entity binding — the dropdown shows none
    assert "button1_detached_light" not in html  # legacy ids are not UI anymore


def test_the_panel_drawing_and_background_selector_are_deleted():
    assert "eu-panel-example" not in _FIELDS
    assert "openBackgroundSelector" not in _FIELDS
    assert "selected_tft" not in _FIELDS
    assert "update_nspanel_example_view" not in HTML
    js = (REPO / "custom_components" / "nspanel_core" / "ui" /
          "static" / "panel_settings.js").read_text()
    assert "update_nspanel_example_view" not in js
    assert not (REPO / "custom_components" / "nspanel_core" / "ui" /
                "templates" / "_background_selector_modal.html").exists()
