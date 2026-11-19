"""P298 — real-JS tests for the photo preview, page names and photo gallery.

The photo bug was CSS, not data: renderPreview() set a correct src, but the
only rule sizing the image targeted `.studio-screen img.bg` while the image
actually lives in `.pv-screen-inner`. The gallery tests execute the real
extracted functions rather than a reimplementation.
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


# --------------------------------------------------------- the photo preview

def test_preview_image_has_a_real_covering_css_rule():
    assert "#pv_bg.bg {" in HTML
    assert "position:absolute; inset:0; width:100%; height:100%; object-fit:cover" in HTML
    # the dead selector that caused the bug must not style the image any more
    assert not re.search(r"\.studio-screen\s+img\.bg\s*\{", HTML)
    # the server already darkens the dash variant — no double CSS filter
    assert not re.search(r"#pv_bg[^\{]*\{[^}]*filter:", HTML)


def test_render_preview_points_the_live_image_at_the_pages_photo():
    script = _js("photoAuth", "renderPreview", "esc") + """
var design = {mac: 'AA', pages: [{name: 'dash_kitchen', title: 'Kitchen',
  background_image: 'gal_aa_111.jpg'}], items: [], screensaver_page: ''};
var entities = [], selectedPage = 'dash_kitchen', selectedItemId = null;
var targetSlot = null, view = 'dash', SLOTS = [];
var els = {};
function _el(id) {
  if (!els[id]) els[id] = {style: {}, dataset: {}, innerHTML: '',
    clientWidth: 480, clientHeight: 320, getAttribute: function () { return this.src; }};
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
function scaleScreen() {}
function tickClock() {}
renderPreview();
var bg = _el('pv_bg');
console.log(JSON.stringify({src: bg.src, display: bg.style.display,
  className: bg.className, tiles: _el('pv_tiles').innerHTML}));
"""
    out = _node_run(script)
    assert "variant=dash" in out["src"]
    assert "page=dash_kitchen" in out["src"]
    assert out["display"] == "block" and out["className"] == "bg dash"


# ------------------------------------------------------------- page naming

def test_page_names_come_from_the_editable_title():
    script = _js("pageSlug", "uniquePageName", "addPage", "renamePage") + """
var design = {mac: 'AA', pages: [{name: 'dash_room1', title: 'Page 1',
  background_image: ''}], items: [{id: 'i1', page: 'dash_room1',
  widget: 'light', entity_id: 'light.x', label: 'X', slot: 0}],
  screensaver_page: 'dash_room1'};
var selectedPage = 'dash_room1';
var calls = [];
function renderPages() { calls.push('pages'); }
function renderItems() { calls.push('items'); }
function renderPreview() { calls.push('preview'); }
function renderGallery() { calls.push('gallery'); }
function saveDesign() { calls.push('save'); }
function setStatus() {}
var document = {querySelectorAll: function () { return [{focus: function () {}}]; }};
var out = {};
out.slug = pageSlug('Living Room 2!');
addPage();
out.added = JSON.parse(JSON.stringify(design.pages[1]));
out.selectedAfterAdd = selectedPage;      // P308: the new page becomes the edit target
renamePage(0, 'Kitchen');
out.renamed = JSON.parse(JSON.stringify(design.pages[0]));
out.itemPage = design.items[0].page;
out.screensaver = design.screensaver_page;
out.selectedPage = selectedPage;out.unique = uniquePageName(pageSlug('Kitchen'), 1);  // page 0 already has it
out.calls = calls;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert out["slug"] == "livingroo"   # firmware-safe: dash_ + max 9 chars
    assert out["added"]["name"] == "dash_newpage"
    assert out["selectedAfterAdd"] == "dash_newpage"   # P308: new page selected
    assert out["renamed"] == {"name": "dash_kitchen", "title": "Kitchen",
                              "background_image": ""}
    assert out["itemPage"] == "dash_kitchen"      # items rebound atomically
    assert out["screensaver"] == "dash_kitchen"
    assert out["selectedPage"] == "dash_newpage"  # still on the page addPage chose
    assert out["unique"] == "dash_kitchen_2"
    assert "save" in out["calls"]


# --------------------------------------------------------------- the gallery

def test_gallery_renders_thumbnails_and_applies_a_photo():
    script = _js("photoAuth", "renderGallery", "applyGalleryPhoto", "esc") + """
var galleryPhotos = [{name: 'gal_aa_111.jpg'}, {name: 'gal_aa_222.png'}];
var design = {mac: 'AA', pages: [{name: 'dash_kitchen', title: 'Kitchen',
  background_image: 'gal_aa_111.jpg'}]};
var selectedPage = 'dash_kitchen';
var calls = [];
function currentMac() { return 'AA'; }
function renderPages() { calls.push('pages'); }
function renderPreview() { calls.push('preview'); }
function saveDesign() { calls.push('save'); }
function setStatus(t) { calls.push(t); }
var galleryEl = {innerHTML: ''};
var document = {getElementById: function (id) {
  return id === 'photo_gallery' ? galleryEl : null;
}};
renderGallery();
var before = galleryEl.innerHTML;
applyGalleryPhoto('gal_aa_222.png');
console.log(JSON.stringify({before: before, after: galleryEl.innerHTML,
  background: design.pages[0].background_image, calls: calls}));
"""
    out = _node_run(script)
    assert out["before"].count("studio-gallery-item") == 2
    assert out["before"].count("selected") == 1
    assert "dashboard_gallery_image?panel=AA&photo=gal_aa_111.jpg" in out["before"]
    assert "applyGalleryPhoto('gal_aa_222.png')" in out["before"]
    assert out["background"] == "gal_aa_222.png"
    assert out["after"].count("selected") == 1          # selection moved
    assert "save" in out["calls"] and "preview" in out["calls"]
