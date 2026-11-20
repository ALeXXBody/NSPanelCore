"""P312: the physical-button rework — DETACHED presses route to a Home
Assistant entity DIRECTLY (no lights-in-rooms detour), the manager delivers
the button configuration to the panel (the firmware never fetched the old
JSON config), and the press event rides nspanel/<hostname>/button."""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import PanelConfig  # noqa: E402
from nspanel_core.const import TOPIC_PANEL_BUTTON  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr(panel: PanelConfig):
    mgr = MagicMock()
    mgr.config.panels = [panel]
    mgr.hass = MagicMock()
    mgr.hass.services = MagicMock()
    mgr.hass.services.async_call = AsyncMock()
    return mgr


def _panel(**kw):
    base = dict(id=7, mac="e465b849a100", name="KitchenPanel",
                button1_mode=1, button1_detached_entity="switch.coffee")
    base.update(kw)
    return PanelConfig(**base)


def _msg(topic="nspanel/KitchenPanel/button", payload='{"button":1,"event":"press"}'):
    m = MagicMock()
    m.topic = topic
    m.payload = payload
    return m


def test_const_declares_the_button_topic():
    assert TOPIC_PANEL_BUTTON == "nspanel/+/button"


def test_detached_press_toggles_the_bound_ha_entity():
    """The user's rule: the press goes STRAIGHT to the HA entity —
    no lights-in-rooms detour, no manager-registered light needed."""
    panel = _panel()
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "switch", "toggle", {"entity_id": "switch.coffee"}, blocking=False)


def test_script_entities_use_turn_on_not_toggle():
    panel = _panel(button1_detached_entity="script.door_sequence")
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "script", "turn_on", {"entity_id": "script.door_sequence"}, blocking=False)


def test_input_button_uses_press():
    panel = _panel(button1_detached_entity="input_button.doorbell")
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "input_button", "press", {"entity_id": "input_button.doorbell"}, blocking=False)


def test_button2_uses_the_button2_binding():
    panel = _panel(button1_detached_entity="switch.never",
                   button2_mode=1, button2_detached_entity="light.desk")
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(
        mgr, _msg(payload='{"button":2,"event":"press"}')))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "light", "toggle", {"entity_id": "light.desk"}, blocking=False)


def test_legacy_light_binding_still_routes():
    """Configs stored before the rework keep working: a manager light id
    toggles through the existing light command path."""
    light = MagicMock()
    light.name = "Ceiling"
    panel = _panel(button1_detached_entity="", button1_detached_light=3)
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    mgr._light_by_id = lambda lid: light if lid == 3 else None
    mgr._apply_light_command = AsyncMock()
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr._apply_light_command.assert_awaited_once_with(light, None)
    mgr.hass.services.async_call.assert_not_awaited()


def test_direct_mode_press_is_ignored_by_the_manager():
    """DIRECT toggles on-panel — the manager must NOT actuate anything."""
    panel = _panel(button1_mode=0)
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_not_awaited()


def test_nothing_bound_is_logged_not_crashed():
    panel = _panel(button1_detached_entity="", button1_detached_light=0)
    mgr = _mgr(panel)
    mgr._panel_by_topic = lambda seg: panel
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))  # no raise


def test_unknown_panel_is_ignored():
    mgr = _mgr(_panel())
    mgr._panel_by_topic = lambda seg: None
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))  # no raise


# ------------------------------------------------- the config delivery

def test_send_panel_config_delivers_button_config():
    """The firmware never consumed the old JSON config — the button modes
    and custom topics/payloads ride set_button_config on the command topic
    (sent on accept AND after every settings save)."""
    panel = _panel(button1_mode=2, button2_mode=3,
                   button1_mqtt_topic="home/btn1", button1_mqtt_payload="ON",
                   button2_mqtt_topic="home/btn2", button2_mqtt_payload="OFF")
    mgr = MagicMock()
    mgr.config.panels = [panel]
    mgr._panel_cmd_topic = lambda p, s: f"nspanel/{p.wifi_hostname or p.name}/{s}"
    # the real register_accept body (settings carry the manager address)
    mgr._register_accept_reply = lambda pnl: json.dumps({
        "command": "register_accept",
        "address": "192.168.50.20", "port": 8123,
        "config_topic": f"nspanel/{pnl.mac}/config"})
    mgr._publish = AsyncMock()
    mgr._publish_panel_status = AsyncMock()
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()

    _run(M.NSPanelCoreManager._send_panel_config(mgr, panel))

    payloads = [c.args[1] for c in mgr._publish.await_args_list]
    btn_cfg = next((p for p in payloads if "set_button_config" in p), None)
    assert btn_cfg is not None, payloads
    d = json.loads(btn_cfg)
    assert d["button1_mode"] == 2
    assert d["button2_mode"] == 3
    assert d["button1_mqtt_topic"] == "home/btn1"
    assert d["button1_mqtt_payload"] == "ON"
    assert d["button2_mqtt_topic"] == "home/btn2"
    assert d["button2_mqtt_payload"] == "OFF"
