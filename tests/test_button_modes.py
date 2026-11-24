"""P312: the physical-button rework — DETACHED presses route to a Home
Assistant entity DIRECTLY (no lights-in-rooms detour), the manager delivers
the button configuration to the panel (the firmware never fetched the old
JSON config), and the press event rides nspanel/<hostname>/button."""

from __future__ import annotations

import asyncio
import tempfile
import json
import os
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import manager as M  # noqa: E402
from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
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
    mgr._panel_cmd_topic = lambda p, s: f"nspanel/{p.wifi_hostname or p.name}/{s}"
    mgr._register_accept_reply = lambda pnl: json.dumps({"command": "register_accept"})
    mgr._publish = AsyncMock()
    mgr._publish_panel_status = AsyncMock()
    mgr._publish_panel_device_config = AsyncMock()
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()
    return mgr


def _panel(**kw):
    base = dict(id=7, mac="e465b849a100", name="KitchenPanel", accepted=True,
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
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "switch", "toggle", {"entity_id": "switch.coffee"}, blocking=False)


def test_script_entities_use_turn_on_not_toggle():
    panel = _panel(button1_detached_entity="script.door_sequence")
    mgr = _mgr(panel)
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "script", "turn_on", {"entity_id": "script.door_sequence"}, blocking=False)


def test_input_button_uses_press():
    panel = _panel(button1_detached_entity="input_button.doorbell")
    mgr = _mgr(panel)
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_awaited_once_with(
        "input_button", "press", {"entity_id": "input_button.doorbell"}, blocking=False)


def test_button2_uses_the_button2_binding():
    panel = _panel(button1_detached_entity="switch.never",
                   button2_mode=1, button2_detached_entity="light.desk")
    mgr = _mgr(panel)
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
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
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
    mgr._light_by_id = lambda lid: light if lid == 3 else None
    mgr._apply_light_command = AsyncMock()
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr._apply_light_command.assert_awaited_once_with(light, None)
    mgr.hass.services.async_call.assert_not_awaited()


def test_direct_mode_press_is_ignored_by_the_manager():
    """DIRECT toggles on-panel — the manager must NOT actuate anything."""
    panel = _panel(button1_mode=0)
    mgr = _mgr(panel)
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
    _run(M.NSPanelCoreManager._on_panel_button(mgr, _msg()))
    mgr.hass.services.async_call.assert_not_awaited()


def test_nothing_bound_is_logged_not_crashed():
    panel = _panel(button1_detached_entity="", button1_detached_light=0)
    mgr = _mgr(panel)
    mgr._panel_by_msg_topic = lambda msg, suffix: panel  # P319: the handler resolves via the helper
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
    mgr._publish_panel_device_config = AsyncMock()
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()

    _run(M.NSPanelCoreManager._send_panel_config(mgr, panel))

    # P359: the device config is delegated to the helper (which carries the
    # modes AND the relay defaults — asserted directly below)
    mgr._publish_panel_device_config.assert_awaited_once_with(panel)


def test_publish_panel_device_config_carries_the_modes():
    """P359: the helper owns the payload — the modes, the custom topics AND
    the relay boot defaults (the studio's "default mode" must reach the
    panel's boot behavior)."""
    panel = _panel(button1_mode=2, button2_mode=3,
                   button1_mqtt_topic="home/btn1", button1_mqtt_payload="ON",
                   button2_mqtt_topic="home/btn2", button2_mqtt_payload="OFF",
                   relay1_default_mode=True, relay2_default_mode=True)
    mgr = MagicMock()
    mgr._panel_cmd_topic = lambda p, s: f"nspanel/{p.wifi_hostname or p.name}/{s}"
    mgr._publish = AsyncMock()

    _run(M.NSPanelCoreManager._publish_panel_device_config(mgr, panel))

    payloads = [c.args[1] for c in mgr._publish.await_args_list]
    btn_cfg = next((p for p in payloads if "set_button_config" in p), None)
    assert btn_cfg is not None, payloads
    d = json.loads(btn_cfg)
    assert d["button1_mode"] == 2
    assert d["button2_mode"] == 3
    assert d["button1_mqtt_topic"] == "home/btn1"
    assert d["button1_mqtt_payload"] == "ON"
    # P359b: STRINGS — the firmware's parser drops a bare JSON bool
    assert d["relay1_default_mode"] == "true"
    assert d["relay2_default_mode"] == "true"
    assert d["button2_mqtt_topic"] == "home/btn2"
    assert d["button2_mqtt_payload"] == "OFF"


def test_send_refused_when_the_display_is_not_responding():
    """P312 HARD LESSON (the user's dead panel): a TFT delivery toward a
    display that is not answering wedges the panel (the stall watchdog
    restarts it; the restart dropped it off the network). The Send must
    refuse with the action that fixes it instead of killing the panel."""
    panel = _panel(button1_mode=0, button2_mode=0)
    mgr = _mgr(panel)
    mgr._panel_by_mac = lambda mac: next(
        (p for p in mgr.config.panels if p.mac == mac), None)
    mgr._last_telemetry = {
        "e465b849a100": {"warnings": [
            {"level": "warning", "text": "No response from the display."}]},
    }
    mgr.dash._designs = {panel.mac: MagicMock()}
    mgr.dash._serving = None
    mgr.dash.manager = mgr  # self.manager resolves through the dash mock

    async def run():
        return await DashboardService.async_send_to_panel(
            mgr.dash, panel.mac)

    result = _run(run())
    assert "display is not responding" in result.get("error", ""), result
    assert mgr._serving in (None, {}) or not mgr.dash._serving, \
        "the serving slot must stay free — nothing was sent"


def test_send_allowed_when_the_display_answers():
    panel = _panel(button1_mode=0)
    mgr = _mgr(panel)
    mgr._panel_by_mac = lambda mac: next(
        (p for p in mgr.config.panels if p.mac == mac), None)
    mgr._last_telemetry = {"e465b849a100": {"warnings": []}}
    mgr.dash._designs = {panel.mac: MagicMock()}
    mgr.dash._serving = None
    svc = mgr.dash
    svc.manager = mgr  # self.manager._publish resolves through the chain
    _tmp = tempfile.NamedTemporaryFile(delete=False)
    _tmp.write(b"x" * 1000)
    _tmp.close()
    svc.async_generate = AsyncMock(return_value=(_tmp.name, "m", {}, []))
    svc._maps = {}
    svc._page_ids = {}
    svc._delivered = {}
    svc._cmd_topic = lambda mac: f"nspanel/{panel.name}/command"
    svc._save = AsyncMock()

    async def run():
        return await DashboardService.async_send_to_panel(mgr.dash, panel.mac)

    result = _run(run())
    assert result.get("ok") is True, result
    os.unlink(_tmp.name)


def test_ota_trigger_skipped_when_the_display_is_not_responding():
    """P312 (the user's crash loop): an empty TFT md5 triggered a tft_update
    on EVERY register — the panel downloaded, streamed to the dead display,
    the stall watchdog restarted it, and the next register triggered again.
    The trigger must SKIP a panel whose display is not answering."""
    import json
    mgr = MagicMock()
    mgr.config.settings.auto_tft_updates = True
    mgr.ota_md5 = MagicMock(side_effect=lambda kind, name: {
        ("tft", "gui.tft"): "b2b6a2e3e53ab56405d2202d51c98a29",
    }.get((kind, name), ""))
    mgr._ota_md5 = {"tft/gui.tft": "x"}
    mgr.dash = None
    mgr._last_telemetry = {"e465b849a100": {"warnings": [
        {"level": "warning", "text": "No response from the display."}]}}
    panel = PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel", accepted=True)
    published = []

    async def _publish(topic, payload, retain=False):
        published.append(payload)

    mgr._publish = _publish
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(mgr, panel, {"md5_tft_file": ""}))
    assert not any('"tft_update"' in p for p in published), published


def test_ota_trigger_still_fires_when_the_display_answers():
    mgr = MagicMock()
    mgr.config.settings.auto_tft_updates = True
    mgr.ota_md5 = MagicMock(side_effect=lambda kind, name: {
        ("tft", "gui.tft"): "b2b6a2e3e53ab56405d2202d51c98a29",
    }.get((kind, name), ""))
    mgr._ota_md5 = {"tft/gui.tft": "x"}
    mgr.dash = None
    mgr._last_telemetry = {"e465b849a100": {"warnings": []}}
    panel = PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel", accepted=True)
    published = []

    async def _publish(topic, payload, retain=False):
        published.append(payload)

    mgr._publish = _publish
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(mgr, panel, {"md5_tft_file": ""}))
    assert any('"tft_update"' in p for p in published), published
