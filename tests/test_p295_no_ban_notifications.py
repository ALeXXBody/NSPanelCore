"""P295 — no browser-facing request may trigger HA's ban notification.

HA 2026.1's helpers/http.py request_handler_factory raises HTTPUnauthorized
whenever a view has requires_auth=True and the request has no valid HA token.
ban.py's ban_middleware catches that exception and process_wrong_login() creates
the user-visible "Login attempt or request with invalid authentication" toast.

The integration's browser-facing views must therefore authenticate in their
own handler via @_gated -> _nspanel_auth_ok, returning a PLAIN 401 Response.
Same identity check (HA token / 24h session cookie / URL fallback), no exception
for HA's ban middleware to turn into a notification — even on a stale token,
which nspanelFetch retries with a refreshed one a moment later.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.dashboard import SESSION_COOKIE  # noqa: E402
from nspanel_core.models import GlobalSettings  # noqa: E402


def _mgr():
    mgr = MagicMock()
    mgr.config.settings = GlobalSettings()
    mgr.hass = MagicMock()
    mgr.hass.auth = MagicMock()
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=False)
    mgr.async_save = AsyncMock()
    return mgr


def _req(cookie="", headers=None, query=None):
    hdr = {"Cookie": cookie}
    hdr.update(headers or {})
    r = MagicMock()
    r.headers = hdr
    r.query = query or {}
    return r


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ------------------------------------------------------- structural invariants

def test_no_view_delegates_auth_to_ha_middleware():
    """A requires_auth=True view is the exact source of the toast: HA raises
    HTTPUnauthorized, ban_middleware catches it, notification created. None of
    our views may do that — they all gate in-handler."""
    views = [
        obj for _, obj in inspect.getmembers(D, inspect.isclass)
        if issubclass(obj, D.HomeAssistantView) and obj is not D.HomeAssistantView
        and obj.__module__ == D.__name__
    ]
    assert len(views) >= 40
    offenders = [v.__name__ for v in views if getattr(v, "requires_auth", False)]
    assert offenders == []


def test_every_browser_facing_view_has_a_gated_handler():
    """The views the UI actually calls must be gated, not merely marked False.

    Covers the whole class: sidebar/htmx/session, settings, rooms, firmware,
    entity pickers and panel actions — the endpoints opened while navigating.
    """
    names = [
        "AuthSessionView", "HtmxNspanelsSectionView", "PanelActionView",
        "SavePanelSettingsView", "AllowIgnoredMacView", "SaveSettingsView",
        "DownloadTftView", "ChecksumTftView", "SaveFirmwareView",
        "SaveDataFileView", "SaveTftFileView", "FirmwareStatusView",
        "FirmwareCheckView", "FirmwareInstallView", "ReorderRoomsView",
        "GetIpByHostnameView", "EntitiesListView", "EntityPickerModalView",
        "SaveNewRoomView", "UpdateRoomView", "DeleteRoomView", "RestartView",
        "ThemeView", "MessagesView",
    ]
    for name in names:
        cls = getattr(D, name)
        assert cls.requires_auth is False, name
        handlers = [
            fn for meth in ("get", "post", "delete", "put", "patch", "_act")
            if (fn := getattr(cls, meth, None)) is not None
        ]
        assert handlers, name
        assert any(getattr(fn, "__wrapped__", None) is not None for fn in handlers), name


# ------------------------------------------------------- behavior

def test_stale_token_returns_a_plain_401_without_an_exception():
    """This is the exact case that used to raise HA's notification: a stale
    Bearer on the exchange request. Now it is a quiet 401 response."""
    mgr = _mgr()
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(D.AuthSessionView().post(
            _req(headers={"Authorization": "Bearer stale"})))
    assert resp.status == 401
    assert resp.text == "Unauthorized"
    assert SESSION_COOKIE not in resp.cookies
    mgr.async_save.assert_not_awaited()


def test_stale_token_on_page_partial_is_also_quiet():
    mgr = _mgr()
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(D.HtmxNspanelsSectionView().get(
            _req(headers={"Authorization": "Bearer stale"})))
    assert resp.status == 401
    assert resp.text == "Unauthorized"


def test_valid_bearer_still_exchanges():
    mgr = _mgr()
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(D.AuthSessionView().post(
            _req(headers={"Authorization": "Bearer fresh"})))
    assert resp.status == 200
    assert SESSION_COOKIE in resp.cookies


def test_session_cookie_admits_exchange_with_no_bearer():
    """A plain navigation carries only the 24h cookie — no token at all."""
    mgr = _mgr()
    mgr.config.settings.nspanel_sessions = {"good": time.time() + 3600}
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(D.AuthSessionView().post(_req(cookie="nspanel_session=good")))
    assert resp.status == 200
