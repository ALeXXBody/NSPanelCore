"""P319: the verbatim-first panel resolution.

The Kitchen panel's hostname is the typo "KitchenPanrl" while its registry
name is "KitchenPanel" — mac_from_topic() lowercases the segment, and the
lowercased form matches NOTHING (name and hostname differ by an 'e'). Every
handler that resolved through the normalized segment only was deaf to this
panel: status reports were dropped (the Send guard's stale "No response from
the display" warnings never cleared, refusing the TFT delivery forever),
touch routing died, DETACHED button presses were dropped, the UI log stayed
empty. _on_relay_state parsed the segment VERBATIM and worked — this pins
that pattern for every handler.
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


def _mgr():
    """A real manager instance (no __init__) with a real panel registry."""
    mgr = object.__new__(M.NSPanelCoreManager)
    mgr.config = MagicMock()
    mgr.config.panels = [_panel()]
    mgr.hass = MagicMock()
    mgr.hass.services = MagicMock()
    mgr.hass.services.async_call = AsyncMock()
    mgr.stomp = None
    mgr.dash = MagicMock()
    mgr._last_telemetry = {}
    mgr._log_backlog = {}
    mgr._save_timer = None
    mgr._schedule_save = lambda: None  # no storage in the pure test harness
    mgr._new_panel_listeners = []
    mgr._report_listeners = []
    mgr._register_accept_reply = lambda pnl: json.dumps({"command": "register_accept"})
    mgr._publish = AsyncMock()
    return mgr


def _panel(**kw):
    """The live panel's exact registry shape: typo hostname, different name."""
    base = dict(id=7, mac="e465b849a100", name="KitchenPanel",
                wifi_hostname="KitchenPanrl", accepted=True,
                button1_mode=1, button1_detached_entity="switch.coffee")
    base.update(kw)
    return PanelConfig(**base)


def _msg(topic, payload='{"button":1,"event":"press"}'):
    m = MagicMock()
    m.topic = topic
    m.payload = payload
    return m


# --- the resolver itself -----------------------------------------------------

def test_verbatim_segment_resolves_the_typo_hostname():
    mgr = _mgr()
    got = mgr._panel_by_msg_topic(
        _msg("nspanel/KitchenPanrl/status_report"), "status_report")
    assert got is not None and got.mac == "e465b849a100"


def test_normalized_fallback_still_works_for_clean_hostnames():
    mgr = _mgr()
    got = mgr._panel_by_msg_topic(
        _msg("nspanel/kitchenpanel/status_report"), "status_report")
    # the lowercased segment matches nothing verbatim; the registry name
    # normalizes to "kitchenpanel" — the fallback must find it
    assert got is not None and got.mac == "e465b849a100"


def test_unknown_segment_resolves_nothing():
    mgr = _mgr()
    assert mgr._panel_by_msg_topic(
        _msg("nspanel/NoSuchPanel/status_report"), "status_report") is None


# --- every handler must be deaf no more --------------------------------------

def test_button_press_routes_on_the_typo_hostname():
    mgr = _mgr()
    _run(M.NSPanelCoreManager._on_panel_button(
        mgr, _msg("nspanel/KitchenPanrl/button")))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "switch", "toggle", {"entity_id": "switch.coffee"}, blocking=False)


def test_status_report_clears_stale_warnings_on_the_typo_hostname():
    mgr = _mgr()
    mgr._last_telemetry["e465b849a100"] = {
        "warnings": [{"level": "warning", "text": "No response from the display."}]}
    report = {"version": "0.1.11", "rssi": -59, "heap_used_pct": 39,
              "mac": "E4:65:B8:49:A1:00", "temperature": "32.6",
              "ip": "192.168.50.23", "warnings": ""}
    _run(M.NSPanelCoreManager._on_panel_status_report(
        mgr, _msg("nspanel/KitchenPanrl/status_report", json.dumps(report))))
    # the stale warning is GONE — the Send guard reads this store
    assert mgr._last_telemetry["e465b849a100"]["warnings"] == []


def test_status_report_stores_real_warnings_on_the_typo_hostname():
    mgr = _mgr()
    report = {"version": "0.1.10", "rssi": -59, "heap_used_pct": 46,
              "mac": "E4:65:B8:49:A1:00", "temperature": "30.3",
              "ip": "192.168.50.23",
              "warnings": "No response from the display."}
    _run(M.NSPanelCoreManager._on_panel_status_report(
        mgr, _msg("nspanel/KitchenPanrl/status_report", json.dumps(report))))
    warns = mgr._last_telemetry["e465b849a100"]["warnings"]
    assert warns and warns[0]["text"] == "No response from the display."


def test_touch_routes_by_panel_mac_on_the_typo_hostname():
    mgr = _mgr()
    _run(M.NSPanelCoreManager._on_panel_touch(
        mgr, _msg("nspanel/KitchenPanrl/touch", '{"page":2,"component":4,"event":1}')))
    mgr.dash.on_touch.assert_called_once_with("e465b849a100", 2, 4, 1)


def test_log_handler_accepts_the_typo_hostname():
    mgr = _mgr()
    mgr.stomp = MagicMock()
    entry = {"time": "", "level": "INFO", "message": "stage: mqtt connected"}
    _run(M.NSPanelCoreManager._on_panel_log(
        mgr, _msg("nspanel/KitchenPanrl/log", json.dumps(entry))))
    assert mgr._log_backlog["e465b849a100"], "the log must reach the backlog"
