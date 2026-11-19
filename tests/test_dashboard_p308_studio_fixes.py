"""P308 — the studio usability fixes and the screensaver save regression.

The user's report: the screensaver picture picker belongs in the screensaver
tab; pages are added from a + on each page row (no separate button); photo
upload failures were swallowed silently; a useless weather paragraph; the
weather sensors need type-to-filter boxes; and saving the screensaver died
with 400 {"error": "malformed body"} because the form carried data-authed, so
base.js's global submit handler raced the studio's JSON fetch with a FormData
post the save view could not parse.

The JS tests execute the REAL functions extracted from dashboard.html and the
REAL rendered partial; the backend tests drive the REAL save view.
"""
from __future__ import annotations

import asyncio
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402

HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html").read_text()
PARTIAL = (REPO / "custom_components" / "nspanel_core" / "ui" /
           "templates" / "_screensaver_fields.html").read_text()
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


# ------------------------------------------------------------ the 400 save

_FULL_BODY = {
    "clock_font": "medium", "clock_weight": "bold", "clock_color": "#39c8e8",
    "clock_align": "left", "date_font": "large", "date_weight": "bold",
    "date_color": "#8b93a1", "date_align": "right",
    "show_ss_outside_temp": True, "show_ss_room_temp": False,
    "show_ss_forecast": True, "show_ss_wind": True, "show_ss_rain": False,
    "show_ss_sunrise_sunset": True,
    "ss_outside_temp_entity": "sensor.outside", "ss_room_temp_entity": "",
}


def _world():
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    panel = PanelConfig(id=7, mac="aabbcc", name="Kitchen", room_id=1,
                        accepted=True)
    cfg.panels.append(panel)
    manager = MagicMock()
    manager.config = cfg
    manager.panels.return_value = list(cfg.panels)
    manager.hass = SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: []))
    manager.async_save = AsyncMock()
    manager._publish_screensaver = AsyncMock()
    manager.notify_panels_changed = MagicMock()
    return cfg, panel, manager


class _Form(dict):
    """Enough of aiohttp's MultiDict for the save view: .items() and `in`."""


class _FormReq:
    def __init__(self, form, headers=None, match_info=None):
        self.app = {"hass": SimpleNamespace(data={f"{DOMAIN}_entry_id": "entry",
                                                  DOMAIN: {"entry": _MGR[0]}})}
        self.headers = headers or {"Content-Type": "application/x-www-form-urlencoded"}
        self.match_info = match_info or {}
        self._form = form

    async def post(self):
        return self._form


_MGR = [None]


def test_save_view_accepts_a_plain_form_post_not_just_json():
    """The 400 {"error": "malformed body"} regression: a form-encoded body
    (what any plain form submit sends) must save, with checkbox presence
    semantics — an unchecked box must not silently keep its old value."""
    _, panel, manager = _world()
    _MGR[0] = manager
    form = _Form(
        clock_font="medium", clock_weight="bold", clock_color="#39c8e8",
        clock_align="left", date_font="large", date_weight="bold",
        date_color="#8b93a1", date_align="right",
        show_ss_wind="on", show_ss_sunrise_sunset="on",
        ss_outside_temp_entity="sensor.outside",
    )
    resp = _run(D.DashboardScreensaverSaveView().post(_FormReq(
        form, match_info={"panel_id": "7"})))
    assert resp.status == 200, resp.text
    assert json.loads(resp.text) == {"ok": True, "panel_id": 7}
    assert panel.clock_font == "medium" and panel.date_align == "right"
    assert panel.show_ss_wind is True
    # the two flags that were NOT in the form post were unchecked by the user
    assert panel.show_ss_rain is False
    assert panel.show_ss_forecast is False
    assert panel.ss_outside_temp_entity == "sensor.outside"
    manager.async_save.assert_awaited_once_with()
    manager._publish_screensaver.assert_awaited_once_with(panel)


def test_form_post_still_rejects_bad_values():
    _, panel, manager = _world()
    _MGR[0] = manager
    form = _Form(clock_font="huge", show_ss_wind="on")
    resp = _run(D.DashboardScreensaverSaveView().post(_FormReq(
        form, match_info={"panel_id": "7"})))
    assert resp.status == 422
    assert json.loads(resp.text)["fields"] == {"clock_font": "must be one of small, medium, large, xlarge"}
    manager.async_save.assert_not_awaited()


def test_the_screensaver_form_never_races_the_global_data_authed_handler():
    """base.js intercepts every form[data-authed] and posts FormData — which
    the (JSON) save view answers with 400 "malformed body". The studio's own
    inline JS already posts the right JSON, so the attribute must be gone."""
    assert "data-authed" not in PARTIAL


def test_the_useless_weather_paragraph_is_gone():
    assert "Each detail can be hidden" not in PARTIAL
    assert "Leave the entity on the global / panel sensor" not in PARTIAL


# ------------------------------------------------------------ the pickers

def test_weather_sensors_render_as_type_to_filter_boxes():
    assert 'data-ss-picker="{{ name }}"' in PARTIAL
    assert 'class="ss-entity-picker"' in PARTIAL
    # the hidden input keeps the field name — the saved payload is unchanged
    assert 'type="hidden" name="{{ name }}" id="{{ name }}"' in PARTIAL
    # the option list is server-rendered into a hidden source select
    assert 'data-ss-source="{{ name }}"' in PARTIAL
    assert "for entity in entities" in PARTIAL
    # the visible search box never submits a value of its own
    # (the macro is used for both fields — one definition, two renderings)
    assert PARTIAL.count('type="search"') == 1
    # the studio binds the real filter behavior
    assert "function ssBindEntityPickers(" in HTML
    assert "ssBindEntityPickers(form);" in HTML


def test_entity_picker_filters_by_label_and_id_and_stores_the_choice():
    script = _js("ssBindEntityPickers", "esc") + """
var Event = function (type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); };
var changes = [];
var hidden = { value: '', dispatchEvent: function (e) { changes.push(e.type + ':' + hidden.value); } };
var handlers = {};
var search = { value: '', addEventListener: function (t, f) { handlers[t] = f; } };
var kids = [], clickHandlers = [];
var list = {
  _html: '',
  style: { display: 'none' },
  set innerHTML(v) { this._html = v; kids = (v.match(/data-v="[^"]*"/g) || [])
    .map(function (s) { return s.slice(8, -1); }); },
  get innerHTML() { return this._html; },
  get children() { return kids.map(function (v) {
    return { dataset: { v: v },
             addEventListener: function (t, f) { clickHandlers.push({ v: v, f: f }); } }; }); }
};
var picker = {
  dataset: { ssPicker: 'ss_outside_temp_entity' },
  querySelector: function (sel) {
    if (sel === 'input[type=hidden]') return hidden;
    if (sel === '.ss-entity-search') return search;
    if (sel === '.ss-entity-list') return list;
    return null;
  }
};
var source = { options: [
  { value: '', text: 'Use the global / panel sensor' },
  { value: 'sensor.outside', text: 'Outside Temperature' },
  { value: 'sensor.inside', text: 'Inside Temperature' },
  { value: 'switch.fan', text: 'Ceiling Fan' }
] };
var document = {
  querySelector: function (sel) {
    return sel === 'select[data-ss-source="ss_outside_temp_entity"]' ? source : null;
  }
};
ssBindEntityPickers({ querySelectorAll: function (s) {
  return s === '[data-ss-picker]' ? [picker] : [];
} });
var out = { changes: changes };
// current stored value shows in the box
out.initial = search.value;
// typing filters by label
search.value = 'OUTSIDE'; handlers.input();
out.filtered = list.innerHTML;
out.kids = kids;
// picking an option stores it in the hidden input and announces the change
clickHandlers[1].f({ preventDefault: function () {} });
out.hiddenAfter = hidden.value;
out.searchAfter = search.value;
out.changes = changes;
out.listHidden = list.style.display;
// the global/panel choice stores the empty value
search.value = ''; handlers.input();
var globalHandler = clickHandlers.filter(function (c) { return c.v === ''; })[0];
globalHandler.f({ preventDefault: function () {} });
out.globalHidden = hidden.value;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert out["initial"] == ""          # nothing stored yet -> empty box
    assert "Outside Temperature" in out["filtered"]
    assert "Ceiling Fan" not in out["filtered"]
    assert out["kids"] == ["", "sensor.outside"]   # global + the match only

    assert out["hiddenAfter"] == "sensor.outside"
    assert out["searchAfter"] == "Outside Temperature"
    assert "change:sensor.outside" in out["changes"]
    assert out["listHidden"] == "none"
    assert out["globalHidden"] == ""


# ------------------------------------------------------- pages: + per row

def test_pages_are_added_from_a_plus_on_the_row_not_a_separate_button():
    assert "+ Add page" not in HTML
    assert "addPage(" in _FNS["renderPages"]
    assert 'title="Add a page after this one"' in HTML
    assert "+ Add page" not in _FNS["renderPages"]


def test_add_page_inserts_after_the_row_and_appends_without_an_index():
    script = _js("esc", "pageSlug", "uniquePageName", "addPage") + """
var design = {pages: [
  {name: 'dash_kitchen', title: 'Kitchen', background_image: ''},
  {name: 'dash_hall', title: 'Hall', background_image: ''}
], items: [], screensaver_page: 'dash_kitchen'};
var selectedPage = null, status = '', calls = [];
function renderPages() { calls.push('pages'); }
function renderItems() { calls.push('items'); }
function renderPreview() { calls.push('preview'); }
function setStatus(t) { status = t; }
var document = { querySelectorAll: function () { return [{ focus: function () {} }]; } };
var out = {};
addPage(0);                       // the + on page row 1
out.insertedAt = 1;
out.inserted = design.pages[1].name;
out.selected = selectedPage;
out.countAfterInsert = design.pages.length;
addPage();                        // no argument appends at the end
out.appended = design.pages[3].name;
out.countAfterAppend = design.pages.length;
out.calls = calls;
out.status = status;
console.log(JSON.stringify(out));
"""
    out = _node_run(script)
    assert out["inserted"] == "dash_newpage"
    assert out["selected"] == "dash_newpage"      # the new page is the edit target
    assert out["countAfterInsert"] == 3
    assert out["appended"] == "dash_newpage_2"
    assert out["countAfterAppend"] == 4
    assert out["calls"] == ["pages", "items", "preview", "pages", "items", "preview"]


# --------------------------------------------------- upload error surfacing

def test_upload_failures_report_the_servers_reason():
    script = _js("studioJson", "uploadGalleryPhotos") + """
var Event = function (type, init) { this.type = type; };
function FileReader() {}
FileReader.prototype.readAsDataURL = function (f) {
  var self = this;
  setImmediate(function () { self.result = 'data:image/png;base64,QUJD'; self.onload(); });
};
var status = { text: '', err: false };
function setStatus(t, err) { status.text = t; status.err = !!err; }
var currentMac = function () { return 'aabbccddeeff'; };
var design = { mac: 'aabbccddeeff' };
var loadGalleryCalls = 0;
function loadGallery() { loadGalleryCalls++; return Promise.resolve(); }
var nspanelFetch = function () {
  return Promise.resolve({ text: function () {
    return Promise.resolve(JSON.stringify(
      { error: 'HEIC photos are not supported \\u2014 use JPG or PNG' }));
  } });
};
var input = { files: [{ name: 'holiday.heic' }], value: 'x' };
uploadGalleryPhotos(input);
setImmediate(function () {
  setImmediate(function () {
    console.log(JSON.stringify({ status: status, inputCleared: input.value === '',
                                 galleryReloads: loadGalleryCalls }));
  });
});
"""
    if not _NODE:
        import pytest
        pytest.skip("node not available")
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "holiday.heic" in out["status"]["text"]
    assert "HEIC photos are not supported" in out["status"]["text"]
    assert out["status"]["err"] is True
    assert out["inputCleared"] is True
    assert out["galleryReloads"] == 1


def test_a_photo_that_fails_to_load_is_reported_in_the_preview():
    fn = _FNS["renderPreview"]
    assert 'could not be loaded' in fn
    assert 're-upload it' in fn
    assert "sbg.onerror" in fn and "screensaver photo could not be loaded" in fn


# ------------------------------------------------------------- the backend

def test_heic_uploads_get_their_own_actionable_message():
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"\x00" * 8
    assert dd.image_reject_error(heic) == "HEIC photos are not supported — use JPG or PNG"
    assert dd.image_reject_error(b"not an image at all") == "the file is not a readable image"
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
    assert dd.image_reject_error(buf.getvalue()) is None


def test_background_store_reports_heic_and_gallery_keeps_working(tmp_path, monkeypatch):
    from nspanel_core.dashboard_manager import DashboardService

    class _Config:
        def path(self, *parts):
            return "/tmp/opencode/p308-fake-config"

    class _Hass:
        config = _Config()
        add_job = MagicMock()

    with __import__("unittest.mock", fromlist=["patch"]).patch(
            "nspanel_core.dashboard_manager.Store", return_value=MagicMock()):
        svc = DashboardService(_Hass(), MagicMock())
    monkeypatch.setattr("nspanel_core.dashboard_manager._dash_dir", lambda h: str(tmp_path))
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"\x00" * 8
    assert svc.store_gallery_photo("aa11bb22cc33", heic) == {
        "error": "HEIC photos are not supported — use JPG or PNG"}
    assert svc.store_background("aa11bb22cc33", "dash_x", heic, "p.heic") == {
        "error": "HEIC photos are not supported — use JPG or PNG"}
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (4, 5, 6)).save(buf, format="PNG")
    stored = svc.store_gallery_photo("aa11bb22cc33", buf.getvalue(), "ok.png")
    assert stored.get("ok") is True
