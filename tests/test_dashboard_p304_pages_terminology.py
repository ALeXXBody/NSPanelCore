"""P304 — the Dashboard studio speaks PAGES, never ROOMS.

Binding rule recorded in LEDGER.md after the user's complaint:
"WHY DID YOU RENAME TO ROOMS?!?!?!?! I ASK TO BE PAGES!!!"

This guard deliberately fails if the word "room" reappears anywhere in the
Dashboard studio template — user-facing copy, ids, functions, locals or
comments. (The shared panel-settings partial keeps "Room" where it means an
HA Area; that is a separate concept and is shared with the settings page.)
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


def test_no_room_term_anywhere_in_the_dashboard_studio():
    # strip nothing: the guard covers copy, ids, callbacks, vars and comments
    found = re.findall(r"\brooms?\b", HTML, flags=re.I)
    assert found == [], "Dashboard studio must say PAGES, found: %r" % found
    for old in ("room_sel", "selectRoom", "selectedRoom", "renderRoomPicker",
                "studio-roombar", "New room", "dash_room"):
        assert old not in HTML, old


def test_every_user_facing_label_says_page():
    for copy in (
        "set up its pages, then send the design",
        "<b>2</b> Build pages",
        "the dots below the tiles are your pages",
        '<label for="scr_sel">Picture shown on the screensaver:</label>',
        'Use the # column below to pick the page you want to edit.',
        '<span class="studio-step-title">Pages</span>',
        "Each page is one screen on the panel.",
        "<th>#</th><th>Page name</th><th>Picture</th>",
        "+ Add page",
        "put it on the page selected above",
        "add it to this page",
        "Add a Home Assistant entity to this page",
        'placeholder="Page name"',
        "Choose a page in the selector above first",
        "No items on this page",
    ):
        assert copy in HTML, copy


def test_page_identifiers_are_renamed_everywhere():
    for ident in ("selectPage", "selectedPage", "studio-pagebar", "scrPage",
                  "scr_sel", "studio-page-pick"):
        assert ident in HTML, ident
    for gone in ("page_sel", "renderPagePicker", "Editing page"):
        assert gone not in HTML, gone
    assert "onclick=\"selectPage(design.pages[' + i + '].name)\"" in HTML
    assert 'id="scr_sel" onchange="design.screensaver_page=this.value;renderPreview()"' in HTML
    assert "onclick=\"event.stopPropagation();selectPage(\\'' + p.name + '\\')\"" in HTML


def test_new_page_defaults_and_numbered_page_pick():
    script = (_FNS["esc"] + _FNS["pageSlug"] + _FNS["uniquePageName"] +
              _FNS["addPage"] + _FNS["renderPages"] + """
var design = {pages: [], items: [], screensaver_page: ''};
var selectedPage = null, status = '';
function renderPreview() {}
function setStatus(t) { status = t; }
var tb = {innerHTML: ''}, ss = {innerHTML: '', value: ''};
var document = {
  querySelector: function (sel) { return sel === '#pages_tbl tbody' ? tb : null; },
  getElementById: function (id) { return id === 'scr_sel' ? ss : null; },
  querySelectorAll: function () { return [{focus: function () {}}]; }
};
var out = {slugEmpty: pageSlug('')};
addPage();
out.title = design.pages[0].title;
out.name = design.pages[0].name;
out.status = status;
out.row = tb.innerHTML;
out.scrOptions = ss.innerHTML;
out.screensaver = design.screensaver_page;
console.log(JSON.stringify(out));
""")
    out = _node_run(script)
    assert out["slugEmpty"] == "page"
    assert out["title"] == "New page"
    assert out["name"] == "dash_newpage"
    assert out["status"] == "Type a page name — the internal name is created from it."
    assert 'class="studio-page-pick active"' in out["row"]
    assert ">1</button>" in out["row"]
    assert 'value="dash_newpage" selected' in out["scrOptions"]
    assert out["screensaver"] == "dash_newpage"
