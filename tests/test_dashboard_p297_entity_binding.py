"""P297 — an item IS a Home Assistant entity, and Panel sub-tabs always work.

The user's report was blunt: "where is the linkage between 'Items (what sits
on the photo)' and 'Home Assistant entities'??? ... those 'items' will be just
some empty, useless, static icons there! SUB-TABS STILL NOT WORKING!!!"

Real-DOM investigation (jsdom, loading the actual inline <script>, the actual
server-rendered partial and the real jQuery/panel_settings.js) proved two
distinct defects:

* addItem() and slotClick() fabricated {entity_id: '', label: ''} items which
  the preview drew as "?" tiles; onWidgetChange() cleared entity_id on a
  domain switch. The entity library's addEntityItem() DID bind an entity, so
  the two add paths disagreed.
* The Panel sub-tab bar was visible before any panel was selected, with an
  empty #panel_settings_box behind it — clicking a tab produced no visible
  fields.

These tests execute the REAL function bodies extracted from dashboard.html
(no reimplementation) and assert the fixed behavior.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html").read_text()
_NODE = shutil.which("node")

_TOP_FN = re.compile(r"^function (\w+)\s*\(", re.M)


def _functions() -> dict[str, str]:
    spans = [(m.group(1), m.start()) for m in _TOP_FN.finditer(HTML)]
    return {name: HTML[start:(spans[i + 1][1] if i + 1 < len(spans) else len(HTML))]
            for i, (name, start) in enumerate(spans)}


_FNS = _functions()


def _js(*names: str) -> str:
    return "\n".join(_FNS[n] for n in names) + "\n"


def _node_run(script: str):
    if not _NODE:
        import pytest
        pytest.skip("node not available for inline-JS behavior tests")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- the items

def test_add_paths_bind_real_entities_and_never_fabricate_a_blank_tile():
    """P301: the Entity-cell search IS the add surface — + Add item binds the
    first matching HA entity; a preview click targets its slot. No path may
    create an entity-less tile."""
    script = _js("addItem", "slotClick", "addEntityItem", "entityLabel",
                 "widgetFromEntity", "entityMatches") + """
var design = {pages: [{name: 'p1'}], items: []};
var entities = [
  {entity_id: 'light.x', name: 'X Light', domain: 'light'},
  {entity_id: 'switch.fan', name: 'Fan', domain: 'switch'}
];
var entityQuery = '';
var selectedPage = 'p1', selectedItemId = null, targetSlot = null;
var SLOTS = [[0,0],[1,1],[2,2],[3,3],[4,4],[5,5]];
var statusText = '';
function setStatus(t) { statusText = t; }
function renderItems() {}
function renderPreview() {}
var document = { getElementById: function () {
  return { focus: function () {}, scrollIntoView: function () {} };
} };
var out = {};
addItem();   // empty search: first unused HA entity
out.afterAddButton = {count: design.items.length, target: targetSlot, status: statusText,
  item: JSON.parse(JSON.stringify(design.items[0]))};
slotClick(4);
out.afterSlotClick = {count: design.items.length, target: targetSlot, status: statusText};
entityQuery = 'fan';
addItem();   // search picks the fan, preview click picks its spot
out.afterSearchAdd = {count: design.items.length, target: targetSlot,
  item: JSON.parse(JSON.stringify(design.items[1])), status: statusText};
addEntityItem('');
out.afterEmptyAdd = {count: design.items.length, status: statusText};
entityQuery = 'nothing-matches-this';
addItem();
out.afterNoMatch = {count: design.items.length, status: statusText};
out.blankCount = design.items.filter(function (it) { return !it.entity_id; }).length;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert out["afterAddButton"]["count"] == 1
    assert out["afterAddButton"]["item"]["entity_id"] == "light.x"
    assert out["afterAddButton"]["item"]["slot"] == 0
    assert out["afterSlotClick"]["count"] == 1 and out["afterSlotClick"]["target"] == 4
    assert "search" in out["afterSlotClick"]["status"].lower()
    assert out["afterSearchAdd"]["count"] == 2
    assert out["afterSearchAdd"]["item"]["entity_id"] == "switch.fan"
    assert out["afterSearchAdd"]["item"]["slot"] == 4       # honored the target
    assert out["afterSearchAdd"]["target"] is None          # consumed
    assert out["afterEmptyAdd"]["count"] == 2               # empty refused
    assert out["afterNoMatch"]["count"] == 2                # no fake fallback
    assert "No Home Assistant entities match" in out["afterNoMatch"]["status"]
    assert out["blankCount"] == 0


def test_widget_switch_rebinds_and_entity_picker_refuses_empty():
    script = _js("onWidgetChange", "setItemEntity", "widgetDomain",
                 "widgetFromEntity", "entityLabel") + """
var design = {items: [{id: 'i1', page: 'p1', widget: 'switch',
  entity_id: 'switch.fan', label: 'Ceiling Fan', slot: 0}]};
var entities = [
  {entity_id: 'switch.fan', name: 'Ceiling Fan', domain: 'switch'},
  {entity_id: 'climate.living', name: 'Living Climate', domain: 'climate'}
];
var statusText = '';
function setStatus(t) { statusText = t; }
function renderItems() {}
function renderPreview() {}
onWidgetChange(0, 'climate');
var afterSwitch = JSON.parse(JSON.stringify(design.items[0]));
setItemEntity(0, '');
console.log(JSON.stringify({afterSwitch: afterSwitch,
  afterEmpty: JSON.parse(JSON.stringify(design.items[0])), status: statusText}));
"""
    out = _node_run(script)
    assert out["afterSwitch"]["entity_id"] == "climate.living"   # rebound, not cleared
    assert out["afterSwitch"]["widget"] == "climate"
    assert out["afterSwitch"]["label"] == "Living Climate"
    assert out["afterEmpty"] == out["afterSwitch"]              # empty choice refused
    assert "real Home Assistant entity" in out["status"]


def test_saved_designs_drop_legacy_entityless_items():
    """An old saved design may hold blank tiles — they must not survive load."""
    script = _js("loadDesign", "studioJson") + """
var panelId = null, design = {}, selectedPage = null, selectedItemId = null;
var rendered = {calls: []};
function currentMac() { return 'AA:BB'; }
function loadPanelSettings() {}
function setStatus(t) { rendered.status = t; }
function renderPages() { rendered.calls.push('pages'); }
function renderItems() { rendered.calls.push('items'); }
function renderPreview() { rendered.calls.push('preview'); }
var document = { getElementById: function (id) {
  if (id === 'panel_sel') return {options: [{dataset: {}}, {dataset: {id: '7'}}], selectedIndex: 1};
  if (id === 'pane_panel') return {classList: {contains: function () { return false; }}};
  return {style: {}, set innerHTML(v) { rendered[id] = v; }, get innerHTML() { return rendered[id] || ''; }};
} };
var legacy = {mac: '', pages: [{name: 'p1', title: 'P1'}], items: [
  {id: 'real', page: 'p1', widget: 'light', entity_id: 'light.x', label: 'X', slot: 0},
  {id: 'blank', page: 'p1', widget: 'light', entity_id: '', label: '', slot: 1}
], screensaver_page: ''};
function nspanelFetch() {
  return Promise.resolve({ok: true, status: 200, text: function () {
    return Promise.resolve(JSON.stringify({design: JSON.parse(JSON.stringify(legacy))}));
  }});
}
(async function () {
  loadDesign();
  await new Promise(function (r) { setTimeout(r, 0); });
  await new Promise(function (r) { setTimeout(r, 0); });
  console.log(JSON.stringify({panelId: panelId, items: design.items,
    blankCount: design.items.filter(function (it) { return !it.entity_id; }).length}));
})().catch(function (e) { console.error(e); process.exit(1); });
"""
    out = _node_run(script)
    assert out["panelId"] == "7"
    assert len(out["items"]) == 1 and out["items"][0]["entity_id"] == "light.x"
    assert out["blankCount"] == 0


# --------------------------------------------------------------- the tabs

def test_subtabs_load_settings_on_demand_when_no_form_is_present():
    assert "if (panelId) loadPanelSettings();" in _FNS["setPanelSubTab"]
    assert "autoSelectPanel" in HTML
    assert "sel.value = sel.options[1].value" in HTML  # first real panel

    script = _js("setPanelSubTab") + """
var panelId = '1', panelSubTab = 'screen';
var loadCalls = [];
function loadPanelSettings() { loadCalls.push(panelSubTab); }
var box = {innerHTML: '', querySelector: function () { return null; }};
var tabs = [
  {dataset: {sec: 'screen'}, classList: {toggle: function () {}}},
  {dataset: {sec: 'buttons'}, classList: {toggle: function () {}}}
];
var document = {
  querySelectorAll: function () { return tabs; },
  getElementById: function () { return box; }
};
setPanelSubTab('buttons');
console.log(JSON.stringify({loadCalls: loadCalls, activeTab: panelSubTab,
  box: box.innerHTML}));
"""
    out = _node_run(script)
    assert out["loadCalls"] == ["buttons"]     # clicked tab loads its fields
    assert out["activeTab"] == "buttons"
    assert "Choose a panel" not in out["box"]  # no dead "no panel" message

    # With the form present, exactly the clicked section is visible.
    script = _js("setPanelSubTab") + """
var panelId = '1', panelSubTab = 'screen', updateCalls = 0;
function loadPanelSettings() { throw new Error('should not reload a loaded form'); }
function update_shown_elements() { updateCalls++; }
var sections = {};
['general', 'buttons', 'screen'].forEach(function (s) {
  sections[s] = {style: {display: ''}};
});
var form = {querySelector: function (sel) {
  var m = /data-section="(\\w+)"/.exec(sel);
  return m ? sections[m[1]] : null;
}};
var box = {querySelector: function () { return form; }};
var document = {querySelectorAll: function () { return []; },
  getElementById: function () { return box; }};
var out = {};
['screen', 'buttons', 'general'].forEach(function (sec) {
  setPanelSubTab(sec);
  out[sec] = {
    shown: ['general', 'buttons', 'screen'].filter(function (s) {
      return sections[s].style.display !== 'none';
    }),
    active: panelSubTab
  };
});
console.log(JSON.stringify({out: out, updateCalls: updateCalls}));
"""
    out = _node_run(script)["out"]
    assert out == {
        "screen": {"shown": ["screen"], "active": "screen"},
        "buttons": {"shown": ["buttons"], "active": "buttons"},
        "general": {"shown": ["general"], "active": "general"},
    }
