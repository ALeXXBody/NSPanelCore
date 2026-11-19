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
        'for="page_sel">Editing page',
        "Steps 2 and 3 apply to this page.",
        '<span class="studio-step-title">Pages</span>',
        "Each page is one screen on the panel.",
        "<th>Page name</th>",
        "+ Add page",
        "put it on the page selected above",
        "add it to this page",
        "Add a Home Assistant entity to this page",
        "No pages yet — add one in step 1",
        'placeholder="Page name"',
        "Choose a page in the selector above first",
        "No items on this page",
    ):
        assert copy in HTML, copy


def test_page_identifiers_are_renamed_everywhere():
    for ident in ("page_sel", "selectPage", "selectedPage", "renderPagePicker",
                  "studio-pagebar", "scrPage"):
        assert ident in HTML, ident
    assert 'id="page_sel" onchange="selectPage(this.value)"' in HTML
    assert "onclick=\"selectPage(design.pages[' + i + '].name)\"" in HTML


def test_new_page_defaults_and_empty_picker_say_pages():
    script = (_FNS["pageSlug"] + _FNS["uniquePageName"] + _FNS["addPage"] +
              _FNS["renderPagePicker"] + """
var design = {pages: []}, selectedPage = null, status = '';
function renderPages() {}
function renderPreview() {}
function setStatus(t) { status = t; }
var picked = {innerHTML: '', value: ''};
var document = {
  getElementById: function (id) { return id === 'page_sel' ? picked : null; },
  querySelectorAll: function () { return [{focus: function () {}}]; }
};
var out = {};
renderPagePicker();
out.empty = picked.innerHTML;
out.slugEmpty = pageSlug('');
addPage();
out.title = design.pages[0].title;
out.name = design.pages[0].name;
out.status = status;
console.log(JSON.stringify(out));
""")
    out = _node_run(script)
    assert out["empty"] == '<option value="">No pages yet — add one in step 1</option>'
    assert out["slugEmpty"] == "page"
    assert out["title"] == "New page"
    assert out["name"] == "dash_newpage"
    assert out["status"] == "Type a page name — the internal name is created from it."
