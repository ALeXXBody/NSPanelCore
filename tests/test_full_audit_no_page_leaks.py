"""FULL AUDIT regression: no browser-facing page may render panel data
without a credential. Proven live leak: the second (shadowing) EditPanelView
definition had no gate, so /edit/{id} without any credential returned the
full panel-settings page (name + MAC). This test pins the gate on the
page-rendering views so a future duplicate-class edit can never silently
re-open the leak."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.models import GlobalSettings, PanelConfig, RoomConfig  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr():
    mgr = MagicMock()
    mgr.config.settings = GlobalSettings()
    mgr.config.rooms = [RoomConfig(id=1, name="Living")]
    mgr.config.panels = [
        PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel", room_id=1, accepted=True)
    ]
    mgr.panels = lambda: list(mgr.config.panels)
    mgr.hass = MagicMock()
    mgr.hass.auth = MagicMock()
    # nothing validates: every gate must hold without a credential
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=False)
    mgr.hass.auth.async_validate_access_token = MagicMock(return_value=None)
    return mgr


def _req(path, match=None):
    r = MagicMock()
    r.path = path
    r.headers = {"Cookie": ""}
    r.cookies = {}
    r.query = {}
    r.match_info = match or {}
    hass = SimpleNamespaceHass()
    r.app = {"hass": hass}
    return r


class SimpleNamespaceHass(types.SimpleNamespace):
    pass


def _app_hass(mgr):
    return types.SimpleNamespace(
        data={"nspanel_core_entry_id": "e1", "nspanel_core": {"e1": mgr}}
    )


@pytest.mark.parametrize("path,cls", [
    ("/nspanel_core/edit/7", "EditPanelView"),
    ("/nspanel_core/rooms/1", "EditRoomView"),
])
def test_no_panel_data_without_credential(path, cls):
    mgr = _mgr()
    with __import__("unittest").mock.patch.object(D, "_manager", return_value=mgr):
        view = getattr(D, cls)()
        kwargs = {"panel_id": "7"} if cls == "EditPanelView" else {"room_id": "1"}
        resp = _run(view.get(_req(path), **kwargs))
    assert resp.status == 401
    body = str(getattr(resp, "text", ""))
    assert "KitchenPanel" not in body, f"{cls} leaked panel data without a credential"


def test_settings_denied_tab_receives_ignored_macs():
    """The Denied tab must receive the manager's ignored MACs — without the
    context the 'Deleted panels' section renders nothing and a deleted panel
    becomes invisible (it can never be allowed again from the UI)."""
    import jinja2
    mgr = _mgr()
    mgr.config.settings.ignored_macs = ["e465b849a100"]
    tpl_dir = D.TEMPLATES_DIR
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(tpl_dir)))
    tpl = env.get_template("_tab_denied.html")
    html = tpl.render(nspanels=[{"denied": False}], ignored=["e465b849a100"])
    assert "e465b849a100" in html
    assert "Allow again" in html
    html_empty = tpl.render(nspanels=[], ignored=[])
    assert "No deleted panels" in html_empty
