"""P355: the reload nudge is RESTORED — the P324 suppression is lifted.

P324 isolated the nudge as the last wire-level crash candidate; P334 later
root-caused the crash (the display write's portMUX critical section) and
the panel firmware has never had a reload handler (the nudge is an ignored
unknown command — harmless on the wire). Restored at BOTH publish sites
(register-time and _send_panel_config), non-retained (P326).
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
    mgr._publish_panel_device_config = AsyncMock()
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()
    mgr.dash = None
    return mgr


def _panel():
    return PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel",
                       wifi_hostname="KitchenPanel", accepted=True)


def _captured(mgr):
    return [c.args[1] for c in mgr._publish.await_args_list]


def test_register_sends_accept_and_the_reload_nudge():
    mgr = _mgr(_panel())
    _run(M.NSPanelCoreManager._send_panel_config(mgr, _panel()))
    sent = _captured(mgr)
    assert any("register_accept" in s for s in sent), "the accept must go out"
    assert any('"reload"' in s for s in sent), "the nudge is restored (P355)"


def test_nudge_and_accept_are_not_retained():
    # P326: retained commands replay at every boot and killed the panel.
    mgr = _mgr(_panel())
    _run(M.NSPanelCoreManager._send_panel_config(mgr, _panel()))
    for c in mgr._publish.await_args_list:
        retain = c.kwargs.get("retain", c.args[2] if len(c.args) > 2 else False)
        assert not retain, f"non-retained only: {c.args[1]}"


def test_button_config_still_pushed():
    mgr = _mgr(_panel())
    _run(M.NSPanelCoreManager._publish_panel_device_config(mgr, _panel()))
    sent = _captured(mgr)
    assert any("set_button_config" in s for s in sent), "the button config is untouched"
