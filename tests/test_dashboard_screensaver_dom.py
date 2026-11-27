"""P306 Step 4 — the screensaver tab in a REAL DOM.

The harness loads the real server-rendered dashboard.html, the real rendered
screensaver partial, the repo's real jQuery/base.js/panel_settings.js and the
real inline <script> from the page into jsdom. `fetch` is the only fake: it
returns the real partial and records calls. No function is reimplemented.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

pytest.importorskip("homeassistant")

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402

STATIC = REPO / "custom_components" / "nspanel_core" / "ui" / "static"
JSDOM_MODULES = pathlib.Path("/tmp/opencode/dom-env/node_modules")
_NODE = shutil.which("node")

JS = r"""
const fs = require('fs');
const {JSDOM} = require('jsdom');
const P = JSON.parse(fs.readFileSync(0, 'utf8'));
const dom = new JSDOM(P.html, {url: 'http://localhost/nspanel_core/ui',
                               runScripts: 'outside-only'});
const w = dom.window;
const errors = [], calls = [];
w.addEventListener('error', function (e) {
  var msg = 'window error: ' + ((e.error && e.error.message) || e.message);
  if (/Not implemented: navigation/.test(msg)) return;
  errors.push(msg);
});
w.console.error = function () {
  var msg = 'console.error: ' + Array.from(arguments).map(String).join(' ');
  if (/Not implemented: navigation/.test(msg)) return;
  errors.push(msg);
};
w.stomp_subscribe = function () {};
w.stomp_unsubscribe = function () {};
w.setInterval = function () { return 0; };       // the clock tick is not under test
w.ResizeObserver = function () { this.observe = function () {}; };
w.fetch = function (url, options) {
  var u = String(url);
  calls.push({url: u, method: (options && options.method) || 'GET',
              body: (options && options.body) || null,
              contentType: (options && options.headers || {})['Content-Type'] || null});
  var body = '{}';
  if (u.indexOf('dashboard/screensaver_settings') >= 0) body = P.partial;
  else if (u.indexOf('screensaver_save') >= 0) body = JSON.stringify({ok: true});
  else if (u.indexOf('dashboard_design') >= 0) body = JSON.stringify({design: P.design});
  else if (u.indexOf('dashboard_entities') >= 0) body = JSON.stringify({entities: P.entities});
  else if (u.indexOf('dashboard_panels') >= 0) body = JSON.stringify(
      {panels: [{mac: 'aabbcc', name: 'Kitchen', id: 7}]});
  return Promise.resolve({
    ok: true, status: 200,
    text: function () { return Promise.resolve(body); },
    json: function () { return Promise.resolve(JSON.parse(body)); }
  });
};
function loadReal(p) { w.eval(fs.readFileSync(p, 'utf8')); }
loadReal(P.jquery);
loadReal(P.basejs);
loadReal(P.paneljs);
w.document.querySelectorAll('script:not([src])').forEach(function (s) {
  w.eval(s.textContent);                          // the page's REAL inline script
});
const tick = function () { return new Promise(function (r) { setTimeout(r, 0); }); };

(async function () {
  for (var i = 0; i < 5; i++) await tick();        // loadDesign + loadEntities
  // P312: the studio boot waits for auth or a no-frontend verdict — give
  // the bounded wait its rounds (2 x 0ms ticks is not enough for the
  // promise chain; advance a few real-ish ticks)
  for (var i = 0; i < 5; i++) await tick();
  w.setTab('design');
  var designTab = w.document.querySelector('.studio-tab.active').dataset.tab;
  w.setTab('screensaver');
  for (var j = 0; j < 6; j++) await tick();        // the partial fetch resolves

  var form = w.document.querySelector('#screensaver_settings_box form');
  var out = {
    designTab: designTab,
    activeTab: w.document.querySelector('.studio-tab.active').dataset.tab,
    activePane: w.document.querySelector('.studio-tabpane.active').id,
    formPresent: !!form,
    controlCount: form ? form.querySelectorAll('input, select').length : 0,
    settingsFetched: calls.some(function (c) {
      return c.url.indexOf('dashboard/screensaver_settings?panel_id=7') >= 0;
    }),
    previewAtLoad: (function () {
      var c = w.document.getElementById('pvs_clock');
      return c ? {fontSize: c.parentElement.style.fontSize,
                  color: c.parentElement.style.color,
                  textAlign: c.parentElement.style.textAlign} : null;
    })()
  };
  if (!form) throw new Error('the real partial was not injected');

  function set(name, value, check) {
    var el = form.elements[name];
    if (!el) throw new Error('missing control ' + name);
    if (check) el.checked = value; else el.value = value;
    el.dispatchEvent(new w.Event('change', {bubbles: true}));
  }
  set('clock_font', 'xlarge');
  set('clock_weight', 'bold');
  set('clock_color', '#39c8e8');
  set('clock_align', 'right');
  set('date_font', 'medium');
  set('date_weight', 'bold');
  set('date_color', '#8b93a1');
  set('date_align', 'left');
  set('show_ss_outside_temp', true, true);
  set('show_ss_room_temp', true, true);
  set('show_ss_forecast', true, true);
  set('show_ss_wind', true, true);
  set('show_ss_rain', true, true);
  set('show_ss_sunrise_sunset', true, true);

  /* P369: the preview is the drag canvas — the comps live as .ss-item
   * blocks at the page coordinates; the styles ride the inner text div. */
  var clock = w.document.getElementById('pvs_clock');
  var dateEl = w.document.getElementById('pvs_date');
  var insideItem = w.document.querySelector('.ss-item[data-group="inside"]');
  var outItem = w.document.querySelector('.ss-item[data-group="outside"]');
  var fRow0 = w.document.querySelector('.ss-item[data-group="forecast0"]');
  out.preview = {
    clock: {fontSize: clock.parentElement.style.fontSize,
            fontWeight: clock.parentElement.style.fontWeight,
            color: clock.parentElement.style.color,
            textAlign: clock.parentElement.style.textAlign},
    date: {fontSize: dateEl.parentElement.style.fontSize,
           fontWeight: dateEl.parentElement.style.fontWeight,
           color: dateEl.parentElement.style.color,
           textAlign: dateEl.parentElement.style.textAlign},
    inside: insideItem ? insideItem.textContent : null,
    outside: outItem ? outItem.textContent : null,
    forecast0: fRow0 ? fRow0.textContent : null,
    dragItems: w.document.querySelectorAll('#pvs_scr .ss-item').length
  };

  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  for (var k = 0; k < 6; k++) await tick();
  var saveCall = calls.filter(function (c) {
    return c.url.indexOf('screensaver_save') >= 0;
  })[0];
  out.save = saveCall ? {
    url: saveCall.url, method: saveCall.method,
    contentType: saveCall.contentType,
    body: JSON.parse(saveCall.body)
  } : null;
  out.statusText = w.document.getElementById('screensaver_status').textContent;
  out.errors = errors;
  console.log('RESULT' + JSON.stringify(out));
})().catch(function (e) {
  console.error('HARNESS ' + (e && e.stack || e));
  process.exit(1);
});
"""


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Req:
    def __init__(self, manager, query=None):
        self.app = {"hass": SimpleNamespace(data={f"{DOMAIN}_entry_id": "entry",
                                                  DOMAIN: {"entry": manager}})}
        self.query = query or {}
        self.headers = {"Cookie": "nspanel_session=sess"}


def _rendered_pages():
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    panel = PanelConfig(id=7, mac="aabbcc", name="Kitchen", room_id=1,
                        accepted=True, clock_font="large", show_ss_wind=True,
                        ss_outside_temp_entity="sensor.outside")
    cfg.panels.append(panel)

    manager = SimpleNamespace(config=cfg, hass=SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: [
            SimpleNamespace(entity_id="sensor.outside",
                            attributes={"friendly_name": "Outside Temperature"}),
            SimpleNamespace(entity_id="sensor.inside",
                            attributes={"friendly_name": "Inside Temperature"}),
        ])))
    manager.panels = lambda: list(cfg.panels)

    page = _run(D.DashboardView().get(_Req(manager)))
    partial = _run(D.DashboardScreensaverSettingsView().get(
        _Req(manager, query={"panel_id": "7"})))
    assert page.status == 200 and partial.status == 200
    return page.text, partial.text


def test_real_dom_studio_tab_controls_preview_and_save_payload():
    if not _NODE or not (JSDOM_MODULES / "jsdom").is_dir():
        pytest.skip("jsdom harness not installed")

    page, partial = _rendered_pages()
    payload = {
        "html": page,
        "partial": partial,
        "design": {"mac": "aabbcc", "pages": [], "items": [], "screensaver_page": ""},
        "entities": [],
        "jquery": str(STATIC / "jquery.min.js"),
        "basejs": str(STATIC / "base.js"),
        "paneljs": str(STATIC / "panel_settings.js"),
    }
    env = os.environ.copy()
    env["NODE_PATH"] = str(JSDOM_MODULES)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
        tf.write(JS)
        script_path = tf.name
    try:
        proc = subprocess.run([_NODE, script_path], input=json.dumps(payload),
                              text=True, capture_output=True, timeout=45, env=env)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
    assert proc.returncode == 0, proc.stderr
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT"))
    out = json.loads(line[len("RESULT"):])

    # The third tab exists, switches, and loads the real server-rendered form.
    assert out["designTab"] == "design"
    assert out["activeTab"] == "screensaver"
    assert out["activePane"] == "pane_screensaver"
    assert out["formPresent"] is True
    assert out["settingsFetched"] is True
    assert out["controlCount"] >= 16
    assert out["previewAtLoad"]["fontSize"] == "48px"   # default large clock
    assert out["previewAtLoad"]["textAlign"] == "center"

    # Live preview follows every control, without a save (jsdom normalises
    # hex colours to rgb(), so accept either spelling).
    assert out["preview"]["clock"]["fontSize"] == "64px"
    assert out["preview"]["clock"]["fontWeight"] == "700"
    assert out["preview"]["clock"]["color"] in ("#39c8e8", "rgb(57, 200, 232)")
    assert out["preview"]["clock"]["textAlign"] == "right"
    assert out["preview"]["date"]["fontSize"] == "32px"
    assert out["preview"]["date"]["fontWeight"] == "700"
    assert out["preview"]["date"]["color"] in ("#8b93a1", "rgb(139, 147, 161)")
    assert out["preview"]["date"]["textAlign"] == "left"
    # P369: the preview is the DRAG CANVAS — the weather row items are the
    # real page's comps (the toggled-on ones rendered, the off ones gone).
    assert out["preview"]["outside"] == "21.5°C", out["preview"]["outside"]
    assert out["preview"]["inside"] == "19.5°C", out["preview"]["inside"]
    assert "Mon" in out["preview"]["forecast0"], out["preview"]["forecast0"]
    assert "23°/9°" in out["preview"]["forecast0"], out["preview"]["forecast0"]
    # the full drag canvas: clock, date, ampm, wx_icon, outside, inside,
    # forecast0, forecast1
    assert out["preview"]["dragItems"] == 8, out["preview"]["dragItems"]

    # The submit posts the real form values as JSON to the real endpoint.
    save = out["save"]
    assert save is not None
    assert save["url"] == "/nspanel_core/api/screensaver_save/7"
    assert save["method"] == "POST"
    assert save["contentType"] == "application/json"
    assert save["body"] == {
        "clock_font": "xlarge", "clock_weight": "bold", "clock_color": "#39c8e8",
        "clock_align": "right", "date_font": "medium", "date_weight": "bold",
        "date_color": "#8b93a1", "date_align": "left",
        "show_ss_outside_temp": True, "show_ss_room_temp": True,
        "show_ss_forecast": True, "show_ss_wind": True, "show_ss_rain": True,
        "show_ss_sunrise_sunset": True,
        "ss_outside_temp_entity": "sensor.outside", "ss_room_temp_entity": "",
        "screensaver_activation_timeout": "15",
        "show_clock": True, "show_date": True,
    }
    assert out["statusText"] == "Saved"
    assert out["errors"] == [], out["errors"]
