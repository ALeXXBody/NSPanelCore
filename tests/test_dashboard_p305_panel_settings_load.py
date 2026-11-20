"""P305 — the Panel hardware sub-tabs actually load in the real app.

The previous harnesses injected `data-id="1"` by hand, so they could never see
that the real DashboardView passes no `id` at all: the option rendered
`data-id=""`, panelId stayed falsy, `setTab('panel')` skipped the fetch and the
box stayed empty. These tests exercise the REAL view and the REAL JS.
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

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

pytest.importorskip("homeassistant")

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402

HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html").read_text()
_NODE = shutil.which("node")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ------------------------------------------------------------ the real view

def test_real_dashboard_view_puts_a_numeric_panel_id_on_the_option():
    """P311: the studio shell is PUBLIC — the options come from the AUTHED
    panel-list endpoint (the HA app's webview has no stored credential, so
    the shell must load without one)."""
    cfg = IntegrationConfig()
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    cfg.panels.append(PanelConfig(id=7, mac="aabbcc", name="Kitchen Panel",
                                  room_id=1, accepted=True))
    mgr = SimpleNamespace(config=cfg, hass=None)

    class Req:
        app = {"hass": SimpleNamespace(data={"nspanel_core": {"entry": mgr}})}
        headers = {}
        query = {}

    resp = _run(D.DashboardView().get(Req()))
    assert resp.status == 200
    # the shell carries NO panel names — nothing is leaked to an
    # unauthenticated viewer
    assert "Kitchen Panel" not in resp.text
    # the client populates the selector from the authed endpoint
    assert "dashboard_panels" in resp.text and "populatePanels" in resp.text

    list_resp = _run(D.DashboardPanelsView().get(Req()))
    assert list_resp.status == 200
    import json as _json
    body = _json.loads(list_resp.text)
    assert body["panels"] == [{"mac": "aabbcc", "name": "Kitchen Panel",
                               "id": 7}]


# ----------------------------------------------------------- the real inline JS

def test_panel_tab_always_attempts_the_load_and_never_silently_blanks():
    assert "if (t === 'panel') loadPanelSettings();" in HTML
    assert "if (t === 'panel' && panelId)" not in HTML
    assert "No panel id — reload the Dashboard page" in HTML

    if not _NODE:
        pytest.skip("node not available for inline-JS behavior tests")

    def fn(name: str) -> str:
        m = re.search(r"^function %s\([^)]*\) \{[\s\S]*?^\}" % name, HTML, re.M)
        assert m, name
        return m.group(0)

    script = fn("setTab") + "\n" + fn("loadPanelSettings") + """
var panelId = null, settingsLoading = false, panelSubTab = 'screen';
var status = '', box = {innerHTML: ''};
var document = {
  querySelectorAll: function () { return []; },
  getElementById: function (id) { return id === 'panel_settings_box' ? box : null; }
};
function setStatus(t) { status = t; }
function bindPanelSettingsBehavior() {}
function renderPreview() {}
function savePanelSettings() {}
function nspanelFetch() { throw new Error('must not fetch without an id'); }
setTab('panel');
console.log(JSON.stringify({box: box.innerHTML, status: status}));
"""
    proc = subprocess.run([_NODE, "-"], input=script, text=True,
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "No panel id" in out["box"]
    assert out["status"]


def test_screensaver_picker_lives_in_the_screensaver_pane():
    # P308: "Picture shown on the screensaver:" belongs to the
    # Build-the-screensaver tab, not the dashboard design pane.
    pane = HTML[HTML.index('id="pane_screensaver"'):]
    pane = pane[:pane.index("</div>\n    </div>")] if "</div>\n    </div>" in pane else pane
    assert 'for="scr_sel"' in pane
    assert "Picture shown on the screensaver:" in pane
    assert "Editing" not in pane
    design_pane = HTML[HTML.index('id="pane_design"'):HTML.index('id="pane_panel"')]
    assert "scr_sel" not in design_pane      # moved out of the design pane
    step1 = HTML[HTML.index('<span class="studio-step-title">Pages</span>'):]
    step1 = step1[:step1.index('id="pane_panel"')]
    assert "<th>#</th>" in step1
    assert "studio-page-pick" in HTML
