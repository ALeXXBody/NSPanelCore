"""v2 manager core tests — registration, status, command routing, OTA push."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "rewrite" / "nspanel_core_v2"


def _load(unique: str, filename: str):
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, V2 / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def core():
    const = _load("v2_const", "const.py")
    sys.modules.setdefault("const", const)
    _load("v2_models", "models.py")
    manager = _load("v2_manager", "manager.py")
    published: list[tuple[str, str, bool]] = []

    def publish(topic, payload, retain=False):
        published.append((topic, payload, retain))

    cfg = manager.ManagerConfig(manager_address="192.168.50.20", manager_port=8123)
    cfg.panels = [manager.Panel(mac="E4:65:B8:49:A1:00", name="KitchenPanel",
                                wifi_hostname="KitchenPanel", accepted=True)]
    return manager.Core(cfg, publish), published


def test_register_request_adopts_and_accepts(core):
    core, published = core
    req = {
        "command": "register_request",
        "mac_origin": "E4:65:B8:49:A1:00",
        "friendly_name": "KitchenPanel",
        "version": "0.1.187",
        "md5_firmware": "a" * 32,
        "md5_data_file": "b" * 32,
        "md5_tft_file": "c" * 32,
        "address": "192.168.50.23",
    }
    assert core.handle_register_request(json.dumps(req)) is True
    panel = core.config.panels[0]
    assert panel.version == "0.1.187"           # P135: version adopted
    assert panel.firmware_md5 == "a" * 32
    # accept reply on the panel's VERBATIM hostname topic, retained
    assert published, "accept reply must be published"
    topic, payload, retain = published[-1]
    assert topic == "nspanel/KitchenPanel/command"
    assert retain is True
    reply = json.loads(payload)
    assert reply["command"] == "register_accept"
    assert reply["address"] == "192.168.50.20"
    assert reply["port"] == 8123
    assert reply["config_topic"] == "nspanel/e465b849a100/config"


def test_register_ignores_bare_default_hostname(core):
    """A compiled-default friendly_name must never re-point command topics."""
    core, published = core
    req = {"mac_origin": "E4:65:B8:49:A1:00", "friendly_name": "NSPanelCore",
           "version": "0.1.187"}
    core.handle_register_request(json.dumps(req))
    assert core.config.panels[0].wifi_hostname == "KitchenPanel"


def test_unknown_panel_registration_ignored(core):
    core, published = core
    req = {"mac_origin": "AA:BB:CC:DD:EE:FF", "version": "9"}
    assert core.handle_register_request(json.dumps(req)) is False
    assert published == []


def test_status_report_adopts_version_and_telemetry(core):
    core, published = core
    panel = core.handle_status_report(
        "KitchenPanel",
        json.dumps({"version": "0.1.187", "rssi": -58, "temperature": "27.3",
                    "heap_used_pct": 59, "ip": "192.168.50.23",
                    "warnings": "No response from the display."}),
    )
    assert panel is not None
    assert panel.version == "0.1.187"           # P135: live adoption
    assert panel.rssi == -58
    assert panel.temperature == 27.3
    assert panel.heap_used_pct == 59
    assert panel.ip == "192.168.50.23"
    assert panel.online is True


def test_status_report_updating_state_marks_offline(core):
    core, published = core
    panel = core.handle_status_report(
        "KitchenPanel", json.dumps({"version": "0.1.187", "state": "updating_fs"}))
    assert panel.online is False


def test_commands_route_to_verbatim_hostname_topic(core):
    core, published = core
    panel = core.config.panels[0]
    topic = core.send_reboot(panel)
    assert topic == "nspanel/KitchenPanel/command"
    assert json.loads(published[-1][1]) == {"command": "reboot"}
    assert published[-1][2] is False            # commands are NOT retained

    core.send_firmware_update(panel)
    assert json.loads(published[-1][1]) == {"command": "firmware_update"}
    core.send_tft_update(panel)
    assert json.loads(published[-1][1]) == {"command": "tft_update"}


def test_subscriptions_cover_the_wire_contract(core):
    core, published = core
    subs = core.subscriptions()
    assert "nspanel/mqttmanager/command" in subs
    assert "nspanel/+/status_report" in subs
