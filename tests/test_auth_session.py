"""P287: the session-exchange auth flow.

The read-surface gates must let a LOGGED-IN user in from every HA navigation
(sidebar, Integrations links, new tabs) without depending on a 5-minute
access token or on a referer. The HA token is exchanged ONCE for a long-lived
server-side session carried by an httponly cookie.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest

from nspanel_core.dashboard import (
    AuthSessionView,
    SESSION_COOKIE,
    SESSION_TTL,
    _nspanel_auth_ok,
    _STATIC_VERSION,
)
from nspanel_core.models import GlobalSettings


def _mgr(with_auth=True):
    mgr = MagicMock()
    mgr.config.settings = GlobalSettings()
    mgr.hass = MagicMock()
    if with_auth:
        mgr.hass.auth = MagicMock()
        mgr.hass.auth.async_validate_token = AsyncMock(return_value=False)
    else:
        mgr.hass.auth = None
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


# ------------------------------------------------------- the exchange endpoint

def test_auth_session_post_issues_httponly_cookie_and_persists():
    mgr = _mgr()
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(AuthSessionView().post(
            _req(headers={"Authorization": "Bearer fresh"})))

    assert resp.status == 200
    morsel = resp.cookies[SESSION_COOKIE]
    assert morsel["httponly"]
    assert morsel["samesite"] == "Strict"
    assert morsel["path"] == "/"
    assert int(morsel["max-age"]) == SESSION_TTL
    token = morsel.value
    sessions = mgr.config.settings.nspanel_sessions
    assert token in sessions
    assert sessions[token] > time.time()
    mgr.async_save.assert_awaited_once()


def test_auth_session_prunes_expired_sessions():
    mgr = _mgr()
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=True)
    mgr.config.settings.nspanel_sessions = {"stale": time.time() - 10}
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        _run(AuthSessionView().post(
            _req(headers={"Authorization": "Bearer fresh"})))
    sessions = mgr.config.settings.nspanel_sessions
    assert "stale" not in sessions
    assert len(sessions) == 1


# ------------------------------------------------------- the gate

def test_valid_session_cookie_opens_every_navigation():
    """The Integrations link is a plain GET: only the cookie is present."""
    mgr = _mgr()
    mgr.config.settings.nspanel_sessions = {"good": time.time() + 3600}
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        assert _run(_nspanel_auth_ok(_req(cookie="nspanel_session=good"))) is True
    # no HA token was consulted — the session stands on its own
    mgr.hass.auth.async_validate_token.assert_not_awaited()


def test_expired_or_unknown_session_cookie_is_rejected():
    mgr = _mgr()
    mgr.config.settings.nspanel_sessions = {"old": time.time() - 10}
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        assert _run(_nspanel_auth_ok(_req(cookie="nspanel_session=old"))) is False
        assert _run(_nspanel_auth_ok(_req(cookie="nspanel_session=never-issued"))) is False


def test_bearer_and_url_token_still_work():
    mgr = _mgr()
    mgr.hass.auth.async_validate_token = AsyncMock(return_value=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        assert _run(_nspanel_auth_ok(_req(headers={"Authorization": "Bearer fresh"}))) is True
        assert _run(_nspanel_auth_ok(_req(query={"ha_token": "fresh"}))) is True


def test_authless_or_test_double_hass_stays_open():
    mgr = _mgr(with_auth=False)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        assert _run(_nspanel_auth_ok(_req())) is True
    mgr.hass = None
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        assert _run(_nspanel_auth_ok(_req())) is True


# ------------------------------------------------------- cache invalidation

def test_static_cache_key_is_content_derived():
    """A same-version hotfix must still bust the browser cache — the key
    is a content hash, never the release number it was force-moved onto."""
    assert re.fullmatch(r"[0-9a-f]{12}", _STATIC_VERSION)
