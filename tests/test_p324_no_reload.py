"""P324: the reload nudge is suppressed (the isolation step of the crash
hunt — the panel dies ~1s after the register-time messages and the
reload's handler never logs; with the dash_map already eliminated, the
reload is the last wire-level candidate). The manager sends ONLY the
accept at register; the nudge comes back after the 0.1.14 verdict.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import PanelConfig  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr(panel):
    mgr = MagicMock()
    mgr.config.panels = [panel]
    mgr.hass = MagicMock()
    mgr.hass.services = MagicMock()
    mgr.hass.services.async_call = AsyncMock()
    mgr._panel_cmd_topic = lambda p, s: f"nspanel/{p.wifi_hostname or p.name}/{s}"
    mgr._register_accept_reply = lambda pnl: json.dumps({"command": "register_accept"})
    mgr._publish = AsyncMock()
    mgr._publish_panel_status = AsyncMock()
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()
    mgr.dash = None
    return mgr


def _panel():
    return PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel",
                       wifi_hostname="KitchenPanrl", accepted=True)


def _captured(mgr):
    return [c.args[1] for c in mgr._publish.await_args_list]


def test_register_sends_accept_but_never_reload():
    mgr = _mgr(_panel())
    _run(M.NSPanelCoreManager._send_panel_config(mgr, _panel()))
    sent = _captured(mgr)
    assert any("register_accept" in s for s in sent), "the accept must go out"
    assert not any("reload" in s for s in sent), "the reload nudge is suppressed"


def test_button_config_still_pushed():
    mgr = _mgr(_panel())
    _run(M.NSPanelCoreManager._send_panel_config(mgr, _panel()))
    sent = _captured(mgr)
    assert any("set_button_config" in s for s in sent), "the button config is untouched"
