"""P216/P217: the provisioning flow — the tests that were MISSING when
v0.1.4 was released (the user's audit question: "have you tested the code
before the release?" — no, and this file is the closure of that gap).

Covers:
  1. FirstRunView: gated before first_run_done, redirects after
  2. FirstRunSaveView: persists the broker credentials + first_run_done
  3. ProvisionPushView: pushes the credentials to the panel's /provision
     (HTTP mocked), and fails cleanly when the panel/first-run is missing
  4. The dashboard gate: MainPageView redirects to /first_run until saved
"""
from __future__ import annotations

import json
import pathlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest

from nspanel_core.models import GlobalSettings


def _make_manager(with_panel=True, first_run_done=False):
    """A minimal manager double: settings + panels + hass stubs."""
    mgr = MagicMock()
    mgr.config.settings = GlobalSettings()
    mgr.config.settings.first_run_done = first_run_done
    mgr.config.settings.panel_broker_host = ""
    mgr.config.settings.panel_broker_port = 1883
    mgr.config.settings.panel_broker_user = ""
    mgr.config.settings.panel_broker_pass = ""
    if with_panel:
        panel = MagicMock()
        panel.id = 1
        panel.name = "KitchenPanel"
        panel.ip_address = "192.168.50.23"
        panel.tft_md5 = ""
        panel.firmware_md5 = ""
        mgr.config.panels = [panel]
    else:
        mgr.config.panels = []
    mgr.hass = MagicMock()
    mgr.hass.auth = None  # P281: the auth-less HA — the gated views stay open
    mgr.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k))
    mgr.async_save = AsyncMock()
    return mgr


def _request():
    req = MagicMock()
    req.match_info = {}
    return req


def _manager_from_request(mgr):
    """Patch _manager(request) to return our double."""
    return patch("nspanel_core.dashboard._manager", return_value=mgr)


# ---------------------------------------------------------------- FirstRunView

def test_first_run_gated_fresh_install_only():
    """P222: the gate is for FRESH installs (no panels) — an existing
    install with an accepted panel must NEVER be gated (the user's
    dashboard was replaced by the wizard — the "visually a mess" bug)."""
    from nspanel_core.dashboard import MainPageView
    # fresh install: no panels, first_run not done -> gated
    mgr = _make_manager(with_panel=False, first_run_done=False)
    view = MainPageView()
    with _manager_from_request(mgr), \
         patch("nspanel_core.dashboard._redirect",
               side_effect=lambda request, location: types.SimpleNamespace(
                   status=302, headers={"Location": location})):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.get(_request()))
    assert resp.status == 302 and "/first_run" in resp.headers["Location"]


def test_existing_install_never_gated():
    """An accepted panel means an existing install: the dashboard shows,
    and first_run_done is auto-marked so the wizard never nags."""
    from nspanel_core.dashboard import MainPageView
    mgr = _make_manager(first_run_done=False)  # has an accepted panel
    view = MainPageView()
    with _manager_from_request(mgr), \
         patch("nspanel_core.dashboard._render", return_value="<html>dash</html>"):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.get(_request()))
    assert resp.status == 200
    assert mgr.config.settings.first_run_done is True, "existing installs auto-mark the first run"
    assert b"dash" in resp.body


def test_first_run_open_after_save():
    from nspanel_core.dashboard import MainPageView
    mgr = _make_manager(first_run_done=True)
    view = MainPageView()
    with _manager_from_request(mgr), \
         patch("nspanel_core.dashboard._render", return_value="<html>dash</html>"):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.get(_request()))
    assert resp.status == 200
    assert b"dash" in resp.body


def test_first_run_save_persists_credentials():
    """The save writes the broker credentials + first_run_done, and persists."""
    from nspanel_core.dashboard import FirstRunSaveView
    mgr = _make_manager()
    view = FirstRunSaveView()

    form = {"panel_broker_host": "192.168.50.20", "panel_broker_port": "1883",
            "panel_broker_user": "panels", "panel_broker_pass": "secret"}

    async def post():
        return form
    req = _request()
    req.post = post
    req.match_info = {}

    with _manager_from_request(mgr), \
         patch("nspanel_core.dashboard._redirect", return_value=MagicMock()) as redir, \
         patch("nspanel_core.dashboard._LOGGER"):
        import asyncio
        asyncio.get_event_loop().run_until_complete(view.post(req))

    s = mgr.config.settings
    assert s.panel_broker_host == "192.168.50.20"
    assert s.panel_broker_port == 1883
    assert s.panel_broker_user == "panels"
    assert s.panel_broker_pass == "secret"
    assert s.first_run_done is True
    mgr.async_save.assert_awaited()
    redir.assert_called_once()


# ------------------------------------------------------------ ProvisionPushView

def test_provision_push_sends_credentials():
    """The push POSTs the first-run credentials to the panel's /provision."""
    from nspanel_core.dashboard import ProvisionPushView
    mgr = _make_manager(first_run_done=True)
    mgr.config.settings.panel_broker_host = "192.168.50.20"
    mgr.config.settings.panel_broker_port = 1883
    mgr.config.settings.panel_broker_user = "panels"
    mgr.config.settings.panel_broker_pass = "secret"
    view = ProvisionPushView()
    req = _request()
    req.match_info = {"panel_id": "1"}

    captured = {}

    def fake_urlopen(req2, timeout=30):
        captured["url"] = req2.full_url
        captured["body"] = req2.data.decode()
        import io
        return io.BytesIO(b"provisioned - rebooting")

    with _manager_from_request(mgr), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.post(req))

    assert captured["url"] == "http://192.168.50.23/provision"
    body = json.loads(captured["body"])
    assert body["mqtt_server"] == "192.168.50.20"
    assert body["mqtt_port"] == 1883
    assert body["mqtt_user"] == "panels"
    assert body["mqtt_pass"] == "secret"


def test_provision_push_rejects_missing_first_run():
    from nspanel_core.dashboard import ProvisionPushView
    mgr = _make_manager(first_run_done=False)
    view = ProvisionPushView()
    req = _request()
    req.match_info = {"panel_id": "1"}
    with _manager_from_request(mgr):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.post(req))
    assert resp.status == 409


def test_provision_push_rejects_unknown_panel():
    from nspanel_core.dashboard import ProvisionPushView
    mgr = _make_manager(first_run_done=True)
    view = ProvisionPushView()
    req = _request()
    req.match_info = {"panel_id": "999"}
    with _manager_from_request(mgr):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(view.post(req))
    assert resp.status == 404
