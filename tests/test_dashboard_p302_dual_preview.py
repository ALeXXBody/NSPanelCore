"""P302 — two live preview panels, a wide stacked editor, and page dots.

The user's request: "1. In NSPanel Core — live preview, add 2 panels and widen
the card they sit in: 1 panel for screensaver and 1 for dashboard. 2.Design/
Panel settings card will sit under the preview card. same widen style. 3. When
there are multiple pages in Dashboard, it will show dots under the items stack,
the number to pages = the number of dots."

The tests execute the REAL inline functions extracted from dashboard.html.
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


def _body(start: str, end: str) -> str:
    begin = HTML.index(start)
    return HTML[begin:HTML.index(end, begin)]


RENDER = _FNS["renderPreview"]
TICK = _body("function tickClock()", "setInterval(")
SCALE = _body("function scaleScreen()", "new ResizeObserver")


def _node_run(script: str):
    if not _NODE:
        import pytest
        pytest.skip("node not available for inline-JS behavior tests")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------- the markup

def test_both_preview_devices_share_one_wide_card():
    assert 'class="studio-preview-grid"' in HTML
    assert 'id="pvs_device"' in HTML      # screensaver
    assert 'id="pv_device"' in HTML       # dashboard (interactive)
    assert 'id="pvs_bg"' in HTML and 'id="pvs_clock"' in HTML
    assert 'id="pv_dots"' in HTML
    grid = _body('class="studio-preview-grid"', "</div>\n    <p class=\"studio-preview-hint\"")
    assert "Screensaver" in grid and "Dashboard" in grid
    # the old single-device toggle is gone
    assert "setView(" not in HTML
    assert 'id="view_dash"' not in HTML and 'id="view_scr"' not in HTML
    # the card is genuinely wider than the old 540px one
    assert "width: 100%; max-width: 1100px" in HTML
    assert "#pvs_bg.bg {" in HTML
    assert ".pv-device[data-dev=\"eu\"] .pv-bz-left" in HTML


def test_editor_card_is_a_same_style_full_width_card_below_the_preview():
    assert HTML.index('id="pv_frame"') < HTML.index('id="editor_card"')
    assert 'class="studio-panel-frame" id="editor_card"' in HTML
    assert '<div class="flex flex-col gap-6 mt-4">' in HTML
    assert "flex flex-wrap gap-8 mt-4 items-start" not in HTML


def test_dots_markup_and_css_live_under_the_tile_stack():
    assert HTML.index('id="pv_tiles"') < HTML.index('id="pv_dots"')
    assert ".pv-dots {" in HTML and ".pv-dot.active {" in HTML
    assert "design.pages.length > 1" in RENDER
    assert "onclick=\"selectRoom(design.pages[' + i + '].name)\"" in RENDER


# -------------------------------------------------------------- the behavior

_PREVIEW_STUB = """
var els = {};
function _el(id) {
  if (!els[id]) els[id] = {style: {}, dataset: {}, innerHTML: '', textContent: '',
    clientWidth: 480, clientHeight: 320,
    removeAttribute: function () { this.src = null; }};
  return els[id];
}
var document = {
  getElementById: function (id) {
    if (id === 'panel_type' || id === 'button1_mode' || id === 'button2_mode') return null;
    return _el(id);
  },
  querySelectorAll: function () { return []; }
};
function currentMac() { return 'AA'; }
function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
"""


def test_render_preview_paints_both_screens_and_one_dot_per_page():
    script = RENDER + TICK + _PREVIEW_STUB + """
function scaleScreen() {}
var design = {mac: 'AA', screensaver_page: 'dash_scr', pages: [
  {name: 'dash_kitchen', title: 'Kitchen', background_image: 'gal_a.jpg'},
  {name: 'dash_hall', title: 'Hall', background_image: ''},
  {name: 'dash_scr', title: 'Screensaver', background_image: 'gal_s.jpg'}
], items: []};
var entities = [], selectedRoom = 'dash_hall', selectedItemId = null;
var targetSlot = null, SLOTS = [[10,60]];
renderPreview();
var out = {
  scrSrc: _el('pvs_bg').src, scrDisplay: _el('pvs_bg').style.display,
  clock: _el('pvs_clock').textContent, date: _el('pvs_date').textContent,
  dashSrc: _el('pv_bg').src, dashClass: _el('pv_bg').className,
  dots: _el('pv_dots').innerHTML,
  zones: [_el('pvs_bz_left').innerHTML, _el('pv_bz_left').innerHTML],
  devices: [_el('pv_device').dataset.dev, _el('pvs_device').dataset.dev]
};
design.pages = [{name: 'dash_kitchen', title: 'Kitchen', background_image: ''}];
selectedRoom = 'dash_kitchen';
renderPreview();
out.singleDots = _el('pv_dots').innerHTML;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert "variant=scr" in out["scrSrc"] and "page=dash_scr" in out["scrSrc"]
    assert out["scrDisplay"] == "block"
    assert re.match(r"^\d\d:\d\d$", out["clock"])
    assert out["date"]
    assert "variant=dash" in out["dashSrc"] and "page=dash_hall" in out["dashSrc"]
    assert out["dashClass"] == "bg dash"
    assert out["dots"].count('class="pv-dot') == 3
    assert out["dots"].count("pv-dot active") == 1
    assert 'onclick="selectRoom(design.pages[1].name)"' in out["dots"]
    assert out["singleDots"] == ""            # one page -> no dots
    assert all("Left button" in z for z in out["zones"])
    assert out["devices"] == ["eu", "eu"]


def test_scale_screen_scales_both_devices():
    script = SCALE + _PREVIEW_STUB + """
var out = {};
scaleScreen();
out.dash = _el('pv_inner').style.transform;
out.scr = _el('pvs_inner').style.transform;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert out["dash"].startswith("scale(") and out["scr"].startswith("scale(")
