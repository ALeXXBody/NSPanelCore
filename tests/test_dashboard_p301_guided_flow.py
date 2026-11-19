"""P301 — the Dashboard studio reads as a guided flow, not a control dump.

The user's report: "what is that dashboard page? you throw everything there
and that's it ... Nobody can understand anything from what you did there!" and
"just make: 'Items (what sits on the photo) Entity' cells to show/search HA
entities."

The studio now has an explicit "Editing room" selector and four numbered
steps, and the entity search lives in the item cells themselves — there is no
separate entity library block. These tests execute the REAL inline functions
extracted from dashboard.html (no reimplementation).
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


def _node_run(script: str):
    if not _NODE:
        import pytest
        pytest.skip("node not available for inline-JS behavior tests")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _between(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


# ------------------------------------------------------------- the layout

def test_studio_is_a_numbered_guided_flow():
    assert HTML.count('class="studio-step-num"') == 4
    for title in ("Rooms", "Photos", "Items (what sits on the photo)",
                  "Panel hardware"):
        assert f'class="studio-step-title">{title}</span>' in HTML
    assert "Choose a panel, set up its rooms, then send the design" in HTML
    assert ">Build the dashboard</div>" in HTML
    assert ">Panel hardware</div>" in HTML
    # step 4 explains the sub-tabs instead of dropping three dead headings
    step4 = _between(HTML, 'studio-step-title">Panel hardware', "</section>")
    for label in ("Screen &amp; screensaver", "Physical buttons", "General"):
        assert label in step4


def test_no_entity_library_block_or_migration_copy_remains():
    assert 'id="entity_library"' not in HTML
    assert "renderEntityLibrary" not in HTML
    assert "Imported automatically from Home Assistant" not in HTML
    assert "library below" not in HTML
    assert 'id="entity_filter"' in HTML
    assert 'oninput="entityQuery=this.value;renderItems()"' in HTML
    assert "addItem();return false;" in HTML  # Enter in the search adds a match


# ------------------------------------------------------- the room selector

def test_room_selector_is_rendered_with_the_pages():
    assert 'id="room_sel"' in HTML
    assert 'onchange="selectRoom(this.value)"' in HTML
    assert "renderRoomPicker();" in _FNS["renderPages"]
    assert "renderPages();" in _FNS["selectRoom"]  # selection mirrors the picker


def test_room_selector_lists_titles_and_tracks_the_selected_room():
    script = """
%s
%s
var rendered = {};
var document = { getElementById: function () {
  return {
    set innerHTML(v) { rendered.room = v; },
    get innerHTML() { return rendered.room || ''; },
    value: '',
    get options() { return []; }
  };
} };
var design = {pages: []}, selectedRoom = null;
var out = {};
renderRoomPicker();
out.empty = rendered.room;
design.pages = [{name: 'dash_kitchen', title: 'Kitchen'},
                {name: 'dash_hall', title: 'Hall'}];
renderRoomPicker();
out.two = {html: rendered.room, value: rendered.room && document.getElementById().value,
  selectedRoom: selectedRoom};
selectedRoom = 'dash_hall';
renderRoomPicker();
out.kept = {html: rendered.room, selectedRoom: selectedRoom};
console.log(JSON.stringify(out));
""" % (_FNS["esc"], _FNS["renderRoomPicker"])
    out = _node_run(script)
    assert "No rooms yet" in out["empty"]
    assert 'value="dash_kitchen">Kitchen</option>' in out["two"]["html"]
    assert 'value="dash_hall">Hall</option>' in out["two"]["html"]
    assert out["two"]["selectedRoom"] == "dash_kitchen"
    assert out["kept"]["selectedRoom"] == "dash_hall"


def test_empty_slot_click_targets_the_cell_search():
    fn = _FNS["slotClick"]
    assert "targetSlot = slot;" in fn
    assert "entity_library" not in fn
    assert "getElementById('entity_filter')" in fn
    assert "focus()" in fn
    assert "search for a Home Assistant entity above" in fn
