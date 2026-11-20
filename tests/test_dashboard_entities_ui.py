"""P292 — the dashboard studio's entity visibility and save-error fixes.

Two user-reported symptoms, both regressions of earlier ledger fixes:

1. "I can not see HA entities on Dashboard page" — the entity picker was
   loaded only inside loadDesign()'s Promise.all (so a design failure hid it),
   had no text filter, showed raw entity ids, AND the per-item dropdown was
   called with the entity id where a widget type was expected — widgetDomain()
   then returned e.g. "light.kitchen", which matches no domain, so the dropdown
   was permanently empty.

2. "Save failed: SyntaxError: JSON.parse: unexpected non-whitespace character
   after JSON data ... column 4" — P282 proved column 4 is the plain text
   "401: Unauthorized". saveDesign()/sendPanel() were still raw fetch() +
   r.json(), regressing P237. They now use nspanelFetch() + a defensive
   text-first parser that names the HTTP status.

The inline JS is structural-tested here and behaviorally exercised through
Node (available in the dev toolchain) by extracting the real function bodies
from dashboard.html — no reimplementation of the logic under test.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys
from unittest.mock import MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html").read_text()

from nspanel_core.dashboard import DashboardEntitiesView, SESSION_COOKIE  # noqa: E402
from nspanel_core.models import GlobalSettings  # noqa: E402

_NODE = shutil.which("node")


def _between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


_TOP_FN = re.compile(r"^function (\w+)\s*\(", re.M)


def _functions() -> dict[str, str]:
    """Map every top-level inline function name to its real source body."""
    spans = [(m.group(1), m.start()) for m in _TOP_FN.finditer(HTML)]
    out = {}
    for idx, (name, start) in enumerate(spans):
        end = spans[idx + 1][1] if idx + 1 < len(spans) else len(HTML)
        out[name] = HTML[start:end]
    return out


_FNS = _functions()


def _node_run(script: str):
    if not _NODE:
        import pytest
        pytest.skip("node not available for inline-JS behavior tests")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------- the save

def test_studio_writes_are_authenticated_with_a_defensive_parser():
    """No raw fetch()/r.json() may remain in the studio's write path."""
    save = _FNS["saveDesign"]
    send = _FNS["sendPanel"]
    for fn in (save, send):
        assert "nspanelFetch(" in fn
        assert ".then(studioJson)" in fn
        assert "fetch('/nspanel_core/" not in fn   # no raw fetch
        assert ".json()" not in fn                # no r.json()
    assert "return true;" in save and "return false;" in save  # boolean contract
    assert "saveDesign().then(" in send
    assert "currentMac() || design.mac" in send  # send keeps the P291b fallback


def test_studio_json_parses_text_first_and_names_the_http_status():
    fn = _FNS["studioJson"]
    assert "r.text()" in fn
    assert "JSON.parse(t)" in fn
    assert "'HTTP ' + r.status" in fn
    assert "j.error" in fn


def test_studio_json_behavior_through_node():
    script = """
%s
(async function () {
  var out = {};
  out.ok = await studioJson({status: 200, text: () => Promise.resolve('{"ok":true}')});
  try {
    await studioJson({status: 401, text: () => Promise.resolve('401: Unauthorized')});
    out.plain = 'NO THROW';
  } catch (e) { out.plain = e.message; }
  try {
    await studioJson({status: 400, text: () => Promise.resolve('{"error":"bad mac"}')});
    out.err = 'NO THROW';
  } catch (e) { out.err = e.message; }
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
""" % _FNS["studioJson"]
    out = _node_run(script)
    assert out["ok"] == {"ok": True}
    assert "HTTP 401" in out["plain"] and "Unauthorized" in out["plain"]
    assert out["err"] == "bad mac"


# ------------------------------------------------------------ the entities

def test_entities_load_on_page_init_independent_of_the_design():
    # P312: the boot waits (bounded) for the established session before the
    # first pulls — the pre-auth 401s emptied the studio (pictures, panel
    # list, first saves).
    assert "function studioBoot()" in HTML
    assert "autoSelectPanelStart();" in HTML
    assert "loadEntities();  // P292" in HTML
    assert "_nspanelBootstrapDone" in HTML
    load = _FNS["loadEntities"]
    assert "nspanelFetch('/nspanel_core/dashboard_entities'" in load
    assert ".then(studioJson)" in load
    assert "entities = j.entities || []" in load
    assert "renderItems(); renderPreview();" in load
    assert "renderEntityLibrary" not in load
    assert "Failed to load entities" in load
    design = _FNS["loadDesign"]
    assert "Promise.all" not in design
    assert "dashboard_entities" not in design   # decoupled
    assert "renderEntityLibrary" not in design  # no orphaned library call


def test_entity_search_lives_in_the_items_step_with_no_library_block():
    """P301: the Entity cells ARE the searchable surface — there is no
    separate 'Home Assistant entities / Imported automatically…' block."""
    assert 'id="entity_filter"' in HTML
    assert 'id="entity_library"' not in HTML
    assert "renderEntityLibrary" not in HTML
    assert "Imported automatically from Home Assistant" not in HTML
    assert "Items (what sits on the photo)" in HTML
    assert "<th>Entity</th>" in HTML
    assert 'oninput="entityQuery=this.value;renderItems()"' in HTML
    assert "addItem();return false;" in HTML  # Enter adds the first match
    assert "var entityQuery = \"\";" in HTML
    # the user-visible copy must not narrate the migration/history
    copy = _between(HTML, "Items (what sits on the photo)", "</section>")
    for word in ("P291", "P292", "401", "Unauthorized", "regression",
                 "Imported automatically"):
        assert word not in copy


def test_entity_filter_matches_friendly_name_id_and_domain_case_insensitively():
    script = """
%s
%s
var entities = [
  {entity_id: 'light.kitchen', name: 'Kitchen Light', domain: 'light'},
  {entity_id: 'switch.fan', name: 'Ceiling Fan', domain: 'switch'},
  {entity_id: 'sensor.temp', name: 'Living Page Temp', domain: 'sensor'}
];
console.log(JSON.stringify(entities.map(function (e) {
  return {
    label: entityLabel(e),
    kitchen: entityMatches(e, 'KITCHEN'),
    fan: entityMatches(e, 'ceiling'),
    domain: entityMatches(e, 'sensor'),
    blank: entityMatches(e, '   ')
  };
})));
""" % (_FNS["entityLabel"], _FNS["entityMatches"])
    out = _node_run(script)
    assert out[0] == {"label": "Kitchen Light", "kitchen": True, "fan": False,
                      "domain": False, "blank": True}
    assert out[1] == {"label": "Ceiling Fan", "kitchen": False, "fan": True,
                      "domain": False, "blank": True}
    assert out[2]["label"] == "Living Page Temp"
    assert out[2]["kitchen"] is False and out[2]["domain"] is True


def test_entity_cells_search_every_domain_and_show_name_and_id():
    script = """
%s
%s
%s
%s
%s
%s
%s
%s
var rendered = {};
var document = { querySelector: function () {
  return {
    get innerHTML() { return rendered.items || ''; },
    set innerHTML(v) { rendered.items = v; }
  };
} };
var entities = [
  {entity_id: 'light.kitchen', name: 'Kitchen Light', domain: 'light'},
  {entity_id: 'switch.fan', name: 'Ceiling Fan', domain: 'switch'}
];
var entityQuery = 'kitchen';
var design = {pages: [], items: [
  {id: 'i1', page: 'p1', widget: 'light', entity_id: 'light.kitchen',
   label: 'Kitchen', slot: 0}
]};
var selectedPage = 'p1', selectedItemId = null;
renderItems();
console.log(JSON.stringify({html: rendered.items}));
""" % (_FNS["esc"], _FNS["opt"], _FNS["widgetDomain"], _FNS["widgetLabel"],
       _FNS["entityLabel"], _FNS["entityMatches"], _FNS["renderItems"],
       _FNS["widgetFromEntity"])
    html = _node_run(script)["html"]
    assert "Kitchen Light" in html and "light.kitchen" in html  # name · id
    assert 'value="light.kitchen" selected' in html
    assert "Ceiling Fan" not in html  # filtered out of the cell
    assert "No Home Assistant entities" not in html


def test_add_entity_item_places_in_first_free_slot_with_a_friendly_label():
    script = """
%s
%s
var entities = [{entity_id: 'light.x', name: 'X Light', domain: 'light'}];
var design = {mac: 'm', pages: [{name: 'p1'}], items: [{page: 'p1', slot: 0}]};
var selectedPage = 'p1';
var SLOTS = [[0,0],[1,1],[2,2],[3,3],[4,4],[5,5]];
var called = [];
function setStatus(t, e) { called.push(t); }
function renderItems() { called.push('items'); }
function renderPreview() { called.push('preview'); }
function widgetFromEntity(id) { return id.split('.')[0]; }
addEntityItem('light.x');
console.log(JSON.stringify({items: design.items, called: called}));
""" % (_FNS["entityLabel"], _FNS["addEntityItem"])
    out = _node_run(script)
    added = out["items"][-1]
    assert added["slot"] == 1            # slot 0 was taken
    assert added["widget"] == "light"
    assert added["entity_id"] == "light.x"
    assert added["label"] == "X Light"
    assert "items" in out["called"] and "preview" in out["called"]


def test_item_dropdown_offers_all_entities_and_keeps_the_selection():
    """P301: every HA entity is searchable in the Entity cell, regardless of
    the row's Type; the current selection stays visible even under a filter."""
    assert "entityOpts(it.widget, it.entity_id)" in HTML
    script = """
%s
%s
%s
%s
%s
%s
%s
var rendered = {};
var document = { querySelector: function () {
  return {
    get innerHTML() { return rendered.items || ''; },
    set innerHTML(v) { rendered.items = v; }
  };
} };
var entities = [
  {entity_id: 'light.kitchen', name: 'Kitchen Light', domain: 'light'},
  {entity_id: 'light.hall', name: 'Hall Light', domain: 'light'},
  {entity_id: 'switch.fan', name: 'Ceiling Fan', domain: 'switch'}
];
var entityQuery = '';
var design = {mac: 'm', pages: [], items: [
  {id: 'i1', page: 'p1', widget: 'light', entity_id: 'light.hall',
   label: 'Hall', slot: 0}
]};
var selectedPage = 'p1';
var selectedItemId = null;
renderItems();
var allHtml = rendered.items;
var entityQuery = 'fan';   // the saved light must not vanish from its own cell
renderItems();
console.log(JSON.stringify({all: allHtml, filtered: rendered.items}));
""" % (_FNS["esc"], _FNS["opt"], _FNS["widgetDomain"], _FNS["widgetLabel"],
       _FNS["entityLabel"], _FNS["entityMatches"], _FNS["renderItems"])
    result = _node_run(script)
    html = result["all"]
    assert 'value="light.hall" selected' in html
    assert "Hall Light" in html          # friendly label, not raw id
    assert "Kitchen Light" in html
    assert "Ceiling Fan" in html         # every domain, not widget-filtered
    filtered = result["filtered"]
    assert 'value="light.hall" selected' in filtered  # current choice retained
    assert "Hall Light" in filtered
    assert "Kitchen Light" not in filtered


# -------------------------------------------------------------- the backend

def test_entity_endpoint_returns_importable_controllable_domains():
    """The studio's library is fed by /dashboard_entities — assert its shape."""
    class _State:
        def __init__(self, entity_id, state="on", **attrs):
            self.entity_id = entity_id
            self.state = state
            self.attributes = attrs

    manager = MagicMock()
    manager.config.settings = GlobalSettings()
    manager.config.settings.nspanel_sessions = {"sess": 9e18}
    manager.hass.states.async_all.return_value = [
        _State("light.kitchen", friendly_name="Kitchen Light", brightness=128),
        _State("switch.fan", friendly_name="Ceiling Fan"),
        _State("scene.movie", friendly_name="Movie"),
        _State("sensor.temp", state="21", unit_of_measurement="°C"),
        _State("climate.living", current_temperature=22.5),
        _State("media_player.tv", friendly_name="TV"),  # not controllable
        _State("person.bob", friendly_name="Bob"),      # not controllable
    ]

    class _Request:
        headers = {"Cookie": f"{SESSION_COOKIE}=sess"}
        query = {}

    with patch("nspanel_core.dashboard._manager", return_value=manager):
        resp = asyncio.new_event_loop().run_until_complete(
            DashboardEntitiesView().get(_Request())
        )
    assert resp.status == 200
    out = json.loads(resp.text)["entities"]
    ids = [e["entity_id"] for e in out]
    assert ids == ["climate.living", "light.kitchen", "scene.movie",
                   "sensor.temp", "switch.fan"]
    kitchen = next(e for e in out if e["entity_id"] == "light.kitchen")
    assert kitchen["name"] == "Kitchen Light"
    assert kitchen["domain"] == "light"
    assert kitchen["brightness"] == 50  # 128/255 rounded
