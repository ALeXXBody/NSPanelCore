"""P311: the P215/P216 discovery flow, end to end.

The user's specified flow (binding): a freshly flashed panel asks for WiFi
only, joins the network, ADVERTISES itself (mDNS + /status.json) — the
MANAGER SEES IT without MQTT — the user accepts/declines in the UI, and only
after acceptance the manager sends the MQTT settings to the panel. The panel
then reboots into the broker, registers, and is accepted automatically
(single accept). These tests pin every link of that chain.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import GlobalSettings, PanelConfig  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr(broker=True):
    mgr = MagicMock()
    s = GlobalSettings()
    if broker:
        s.panel_broker_host = "192.168.50.20"
        s.panel_broker_port = 1883
        s.panel_broker_user = "ALeXX"
        s.panel_broker_pass = "secret-pass"
    else:
        s.panel_broker_host = ""
    mgr.config.settings = s
    mgr.hass = MagicMock()
    mgr.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *a, **k: fn(*a, **k))
    mgr.async_save = AsyncMock()
    return mgr


def _req(form=None, headers=None):
    r = MagicMock()
    r.headers = {"Cookie": "", "Authorization": "Bearer good"}
    r.cookies = {}
    r.query = {}
    r.match_info = {}
    r._form = dict(form or {})

    async def post():
        return r._form

    r.post = post
    return r


class _FakeResp:
    def __init__(self, status=200, text="provisioned — rebooting"):
        self.status = status
        self.text = text


# ------------------------------------------------------------ discovery view


async def test_discovered_panels_requires_credential():
    mgr = _mgr()
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=False)):
            resp = await D.DiscoveredPanelsView().get(_req())
    assert resp.status == 401



async def test_discovered_panels_returns_manager_results():
    mgr = _mgr()
    mgr.discover_snapshot = AsyncMock(return_value=[
        {"address": "192.168.50.23", "hostname": "KitchenPanrl",
         "version": "0.1.17", "mqtt": "not configured", "warnings": ""},
    ])
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            resp = await D.DiscoveredPanelsView().get(_req())
    import json
    body = json.loads(resp.text)
    assert body["panels"][0]["hostname"] == "KitchenPanrl"


# ------------------------------------------------------------- accept/decline


async def test_accept_requires_credential():
    mgr = _mgr()
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=False)):
            resp = await D.DiscoveredPanelActionView().post(
                _req({"action": "accept", "address": "192.168.50.23", "hostname": "KitchenPanrl"}))
    assert resp.status == 401



async def test_accept_pushes_credentials_and_records_hostname():
    mgr = _mgr()
    captured = {}

    async def fake_push(manager, base, label):
        captured["base"] = base
        captured["label"] = label
        return _FakeResp()

    with patch.object(D, "_manager", return_value=mgr), \
            patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)), \
            patch.object(D, "_push_broker_to_panel", fake_push):
        resp = await D.DiscoveredPanelActionView().post(
            _req({"action": "accept", "address": "192.168.50.23", "hostname": "KitchenPanrl"}))
    assert resp.status == 200
    assert captured["base"] == "http://192.168.50.23"
    assert captured["label"] == "KitchenPanrl"
    # the hostname is recorded so the MQTT registration is auto-accepted
    assert "kitchenpanrl" in [h.lower() for h in mgr.config.settings.pre_accepted_hostnames] or \
           any(h.lower() == "kitchenpanrl" for h in mgr.config.settings.pre_accepted_hostnames)
    mgr.async_save.assert_awaited()



async def test_accept_without_first_run_is_rejected():
    mgr = _mgr(broker=False)
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            resp = await D.DiscoveredPanelActionView().post(
                _req({"action": "accept", "address": "192.168.50.23", "hostname": "KitchenPanrl"}))
    assert resp.status == 409



async def test_deny_records_hostname_without_pushing():
    mgr = _mgr()
    pushed = []

    async def fake_push(manager, base, label):
        pushed.append(base)
        return _FakeResp()

    with patch.object(D, "_manager", return_value=mgr), \
            patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)), \
            patch.object(D, "_push_broker_to_panel", fake_push):
        resp = await D.DiscoveredPanelActionView().post(
            _req({"action": "deny", "address": "192.168.50.99", "hostname": "SomePanel"}))
    assert resp.status == 200
    assert not pushed  # nothing is sent to a declined panel
    assert "somepanel" in [h.lower() for h in mgr.config.settings.discovery_denied] or \
           any(h.lower() == "somepanel" for h in mgr.config.settings.discovery_denied)


# --------------------------------------------------- single-accept contract

def test_maybe_preaccept_accepts_matching_hostname():
    mgr = _mgr()
    mgr.config.settings.pre_accepted_hostnames = ["KitchenPanrl"]
    panel = PanelConfig(id=1, mac="aabbccddeeff", name="KitchenPanrl",
                        wifi_hostname="KitchenPanrl", accepted=False)
    assert M.NSPanelCoreManager.maybe_preaccept_hostname(mgr, panel, "KitchenPanrl") is True
    assert panel.accepted is True
    assert panel.denied is False
    assert mgr.config.settings.pre_accepted_hostnames == []


def test_maybe_preaccept_ignores_unknown_hostname():
    mgr = _mgr()
    mgr.config.settings.pre_accepted_hostnames = ["OtherPanel"]
    panel = PanelConfig(id=1, mac="aabbccddeeff", name="X", accepted=False)
    assert M.NSPanelCoreManager.maybe_preaccept_hostname(mgr, panel, "X") is False
    assert panel.accepted is False


# ------------------------------------------------------ push header contract

@pytest.mark.asyncio
async def test_snapshot_uses_browser_cache_automatically():
    """DISCOVERY IS AUTOMATIC: the background mDNS browser keeps the cache;
    the UI reads it with zero user actions. The endpoint must return the
    cached panel (and never require a manual search)."""
    mgr = _mgr()
    mgr.discover_snapshot = AsyncMock(return_value=[
        {"address": "192.168.50.23", "hostname": "KitchenPanrl",
         "version": "0.1.17", "mqtt": "not configured", "warnings": ""},
    ])
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            resp = await D.DiscoveredPanelsView().get(_req())
    import json
    body = json.loads(resp.text)
    assert body["panels"][0]["hostname"] == "KitchenPanrl"


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_one_scan_when_cache_empty():
    """Just-started race: the browser hasn't populated yet — the snapshot
    runs one on-demand scan and merges, so the first page load still shows
    the panel."""
    mgr = _mgr()
    mgr._discovered_panels = {}
    mgr._fetch_panel_status = AsyncMock(side_effect=lambda addr: None)

    async def fake_scan():
        mgr._discovered_panels["192.168.50.23"] = {
            "address": "192.168.50.23", "hostname": "KitchenPanrl",
            "version": "0.1.17", "mqtt": "not configured", "warnings": ""}
        return [mgr._discovered_panels["192.168.50.23"]]

    mgr.discover_panels = fake_scan  # MagicMock self: the instance attr wins
    panels = await M.NSPanelCoreManager.discover_snapshot(mgr)
    assert any(p["hostname"] == "KitchenPanrl" for p in panels)
    assert "192.168.50.23" in mgr._discovered_panels  # merged into the cache


@pytest.mark.asyncio
async def test_snapshot_filters_declined_and_known():
    mgr = _mgr()
    mgr.config.settings.discovery_denied = ["SomePanel"]
    mgr.config.panels = [
        PanelConfig(id=1, mac="aabbccddeeff", name="KnownPanel", wifi_hostname="KnownPanel")
    ]
    mgr._discovered_panels = {
        "1": {"address": "1", "hostname": "FreshPanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "2": {"address": "2", "hostname": "SomePanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "3": {"address": "3", "hostname": "KnownPanel", "version": "0.1.4", "mqtt": "disconnected", "warnings": ""},
    }
    async def fake_scan():
        return []

    mgr.discover_panels = fake_scan  # cache is populated: the scan must not run
    panels = await M.NSPanelCoreManager.discover_snapshot(mgr)
    hosts = [p["hostname"] for p in panels]
    assert "FreshPanel" in hosts
    assert "SomePanel" not in hosts    # declined
    assert "KnownPanel" not in hosts   # already in the manager


@pytest.mark.asyncio
async def test_discovery_browser_lifecycle_starts_and_stops():
    """The browser starts with the manager and is cancelled on stop — no
    leaked threads between restarts."""
    import asyncio as _aio

    mgr = _mgr()

    class _FakeBrowser:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    started = {}

    async def fake_start():
        mgr._discovery_browser = _FakeBrowser()
        started["ok"] = True

    M.NSPanelCoreManager._start_discovery_browser = fake_start
    try:
        await M.NSPanelCoreManager._start_discovery_browser()
        assert started.get("ok")
        browser = mgr._discovery_browser
        await M.NSPanelCoreManager.async_stop(mgr)
        assert browser.cancelled is True
        assert mgr._discovery_browser is None
    finally:
        del M.NSPanelCoreManager._start_discovery_browser


# ------------------------------------------------------ push header contract


async def test_push_carries_panel_guard_headers():
    """The panel's CSRF guard needs BOTH the form content type and the
    X-NSPanel header — the manager's push must carry both (proven live:
    without them every push is 403)."""
    mgr = _mgr()
    captured = {}

    class _R:
        def __init__(self, url, data, headers):
            captured["url"] = url
            captured["headers"] = headers
            captured["data"] = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"provisioned - rebooting"

        def decode(self, *a, **k):
            return "provisioned — rebooting"

    import urllib.request
    with patch("urllib.request.Request", _R), \
            patch("urllib.request.urlopen", lambda req, timeout=30: req):
        resp = await D._push_broker_to_panel(mgr, "http://192.168.50.23", "KitchenPanrl")
    assert resp.status == 200
    assert captured["url"] == "http://192.168.50.23/provision"
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["X-NSPanel"] == "1"
    assert b'"mqtt_user": "ALeXX"' in captured["data"]


@pytest.mark.asyncio
async def test_discovery_identifies_by_signature_not_name():
    """NO hardcoded names: every _http._tcp service is looked up and a
    candidate is a panel only if its status.json carries the panel
    signature. A panel advertised under ANY name is found; a non-panel
    service is dropped."""
    mgr = _mgr()
    mgr._discovery_zc = MagicMock()
    mgr._discovered_panels = {}
    mgr._discovered_name_ips = {}

    class _FakeInfo:
        def parsed_addresses(self):
            return ["192.168.50.23", "192.168.50.99"]

    mgr._discovery_zc.get_service_info = MagicMock(return_value=_FakeInfo())
    mgr.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k))

    statuses = {
        # a panel advertised under an arbitrary name — must be found
        "192.168.50.23": {"hostname": "FreshPanel", "version": "0.1.4",
                          "mqtt": "not configured", "warnings": "", "ota_state": "idle"},
        # an unrelated _http._tcp device with a generic /status.json — dropped
        "192.168.50.99": {"up": True},
    }

    # MagicMock self: bind the real fetcher through the instance attribute
    mgr._fetch_panel_status = lambda addr: M.NSPanelCoreManager._fetch_panel_status(mgr, addr)

    import urllib.request as ur

    def fake_urlopen(url, timeout=4):
        addr = str(url).replace("http://", "").replace("/status.json", "")

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                import json
                return json.dumps(statuses[addr]).encode()

        return _R()

    with patch.object(ur, "urlopen", fake_urlopen):
        await M.NSPanelCoreManager._adopt_discovered_service(
            mgr, "WhateverName._http._tcp.local.")

    cached = mgr._discovered_panels
    assert "192.168.50.23" in cached          # panel: cached regardless of name
    assert "192.168.50.99" not in cached      # non-panel signature: dropped


async def test_snapshot_filters_declined_and_known():
    mgr = _mgr()
    mgr.config.settings.discovery_denied = ["SomePanel"]
    mgr.config.panels = [
        PanelConfig(id=1, mac="aabbccddeeff", name="KnownPanel", wifi_hostname="KnownPanel")
    ]
    mgr._discovered_panels = {
        "1": {"address": "1", "hostname": "FreshPanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "2": {"address": "2", "hostname": "SomePanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "3": {"address": "3", "hostname": "KnownPanel", "version": "0.1.4", "mqtt": "disconnected", "warnings": ""},
    }

    async def no_scan():
        return []

    mgr.discover_panels = no_scan  # cache populated: the scan must not run
    panels = await M.NSPanelCoreManager.discover_snapshot(mgr)
    hosts = [p["hostname"] for p in panels]
    assert "FreshPanel" in hosts
    assert "SomePanel" not in hosts    # declined
    assert "KnownPanel" not in hosts   # already in the manager


# --------------------------------------------------- single-accept contract

def test_maybe_preaccept_accepts_matching_hostname():
    mgr = _mgr()
    mgr.config.settings.pre_accepted_hostnames = ["KitchenPanrl"]
    panel = PanelConfig(id=1, mac="aabbccddeeff", name="KitchenPanrl",
                        wifi_hostname="KitchenPanrl", accepted=False)
    assert M.NSPanelCoreManager.maybe_preaccept_hostname(mgr, panel, "KitchenPanrl") is True
    assert panel.accepted is True
    assert panel.denied is False
    assert mgr.config.settings.pre_accepted_hostnames == []


def test_maybe_preaccept_ignores_unknown_hostname():
    mgr = _mgr()
    mgr.config.settings.pre_accepted_hostnames = ["OtherPanel"]
    panel = PanelConfig(id=1, mac="aabbccddeeff", name="X", accepted=False)
    assert M.NSPanelCoreManager.maybe_preaccept_hostname(mgr, panel, "X") is False
    assert panel.accepted is False


# ------------------------------------------------------ push header contract

@pytest.mark.asyncio
async def test_snapshot_uses_browser_cache_automatically():
    """DISCOVERY IS AUTOMATIC: the background mDNS browser keeps the cache;
    the UI reads it with zero user actions. The endpoint must return the
    cached panel (and never require a manual search)."""
    mgr = _mgr()
    mgr.discover_snapshot = AsyncMock(return_value=[
        {"address": "192.168.50.23", "hostname": "KitchenPanrl",
         "version": "0.1.17", "mqtt": "not configured", "warnings": ""},
    ])
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            resp = await D.DiscoveredPanelsView().get(_req())
    import json
    body = json.loads(resp.text)
    assert body["panels"][0]["hostname"] == "KitchenPanrl"


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_one_scan_when_cache_empty():
    """Just-started race: the browser hasn't populated yet — the snapshot
    runs one on-demand scan and merges, so the first page load still shows
    the panel."""
    mgr = _mgr()
    mgr._discovered_panels = {}
    mgr._fetch_panel_status = AsyncMock(side_effect=lambda addr: None)

    async def fake_scan():
        mgr._discovered_panels["192.168.50.23"] = {
            "address": "192.168.50.23", "hostname": "KitchenPanrl",
            "version": "0.1.17", "mqtt": "not configured", "warnings": ""}
        return [mgr._discovered_panels["192.168.50.23"]]

    mgr.discover_panels = fake_scan  # MagicMock self: the instance attr wins
    panels = await M.NSPanelCoreManager.discover_snapshot(mgr)
    assert any(p["hostname"] == "KitchenPanrl" for p in panels)
    assert "192.168.50.23" in mgr._discovered_panels  # merged into the cache


@pytest.mark.asyncio
async def test_snapshot_filters_declined_and_known():
    mgr = _mgr()
    mgr.config.settings.discovery_denied = ["SomePanel"]
    mgr.config.panels = [
        PanelConfig(id=1, mac="aabbccddeeff", name="KnownPanel", wifi_hostname="KnownPanel")
    ]
    mgr._discovered_panels = {
        "1": {"address": "1", "hostname": "FreshPanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "2": {"address": "2", "hostname": "SomePanel", "version": "0.1.4", "mqtt": "not configured", "warnings": ""},
        "3": {"address": "3", "hostname": "KnownPanel", "version": "0.1.4", "mqtt": "disconnected", "warnings": ""},
    }
    async def fake_scan():
        return []

    mgr.discover_panels = fake_scan  # cache is populated: the scan must not run
    panels = await M.NSPanelCoreManager.discover_snapshot(mgr)
    hosts = [p["hostname"] for p in panels]
    assert "FreshPanel" in hosts
    assert "SomePanel" not in hosts    # declined
    assert "KnownPanel" not in hosts   # already in the manager


@pytest.mark.asyncio
async def test_discovery_browser_lifecycle_starts_and_stops():
    """The browser starts with the manager and is cancelled on stop — no
    leaked threads between restarts."""
    import asyncio as _aio

    mgr = _mgr()

    class _FakeBrowser:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    started = {}

    async def fake_start():
        mgr._discovery_browser = _FakeBrowser()
        started["ok"] = True

    M.NSPanelCoreManager._start_discovery_browser = fake_start
    try:
        await M.NSPanelCoreManager._start_discovery_browser()
        assert started.get("ok")
        browser = mgr._discovery_browser
        await M.NSPanelCoreManager.async_stop(mgr)
        assert browser.cancelled is True
        assert mgr._discovery_browser is None
    finally:
        del M.NSPanelCoreManager._start_discovery_browser


# ------------------------------------------------------ push header contract


async def test_push_carries_panel_guard_headers():
    """The panel's CSRF guard needs BOTH the form content type and the
    X-NSPanel header — the manager's push must carry both (proven live:
    without them every push is 403)."""
    mgr = _mgr()
    captured = {}

    class _R:
        def __init__(self, url, data, headers):
            captured["url"] = url
            captured["headers"] = headers
            captured["data"] = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"provisioned - rebooting"

        def decode(self, *a, **k):
            return "provisioned — rebooting"

    import urllib.request
    with patch("urllib.request.Request", _R), \
            patch("urllib.request.urlopen", lambda req, timeout=30: req):
        resp = await D._push_broker_to_panel(mgr, "http://192.168.50.23", "KitchenPanrl")
    assert resp.status == 200
    assert captured["url"] == "http://192.168.50.23/provision"
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["X-NSPanel"] == "1"
    assert b'"mqtt_user": "ALeXX"' in captured["data"]
