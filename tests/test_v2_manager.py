"""v2 manager core tests — registration, status, command routing, OTA push."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "custom_components" / "nspanel_core"


def _pkg():
    """Load the v2 tree as a real package (relative imports resolve)."""
    if "v2pkg" in sys.modules:
        return sys.modules["v2pkg"]
    spec = importlib.util.spec_from_file_location(
        "v2pkg", V2 / "__init__.py", submodule_search_locations=[str(V2)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["v2pkg"] = pkg
    spec.loader.exec_module(pkg)
    return pkg


def _load(unique: str, filename: str):
    """Load a v2 submodule inside the package context (unique name kept)."""
    _pkg()
    return importlib.import_module("v2pkg." + filename.rsplit(".", 1)[0])


@pytest.fixture()
def core():
    const = _load("v2_const", "const.py")
    sys.modules.setdefault("const", const)
    _load("v2_models", "models.py")
    manager = _load("v2_manager", "manager.py")
    published: list[tuple[str, str, bool]] = []

    def publish(topic, payload, retain=False):
        published.append((topic, payload, retain))

    cfg = manager.ManagerConfig(manager_address="10.0.0.2", manager_port=8123)
    cfg.panels = [manager.Panel(mac="AA:BB:CC:DD:EE:01", name="DemoPanel",
                                wifi_hostname="DemoPanel", accepted=True)]
    return manager.Core(cfg, publish), published


def test_register_request_adopts_and_accepts(core):
    core, published = core
    req = {
        "command": "register_request",
        "mac_origin": "AA:BB:CC:DD:EE:01",
        "friendly_name": "DemoPanel",
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
    assert topic == "nspanel/DemoPanel/command"
    assert retain is True
    reply = json.loads(payload)
    assert reply["command"] == "register_accept"
    assert reply["address"] == "10.0.0.2"
    assert reply["port"] == 8123
    assert reply["config_topic"] == "nspanel/aabbccddee01/config"


def test_register_ignores_bare_default_hostname(core):
    """A compiled-default friendly_name must never re-point command topics."""
    core, published = core
    req = {"mac_origin": "AA:BB:CC:DD:EE:01", "friendly_name": "NSPanelCore",
           "version": "0.1.187"}
    core.handle_register_request(json.dumps(req))
    assert core.config.panels[0].wifi_hostname == "DemoPanel"


def test_unknown_panel_autoregisters_unaccepted(core):
    """v1 contract: new panels auto-register as UNACCEPTED, no accept reply,
    and wait for the dashboard's Accept button."""
    core, published = core
    req = {"mac_origin": "AA:BB:CC:DD:EE:FF", "friendly_name": "GaragePanel",
           "version": "0.1.0"}
    assert core.handle_register_request(json.dumps(req)) is True
    assert published == []                       # no accept reply yet
    new = next(p for p in core.config.panels if p.mac == "aabbccddeeff")
    assert new.accepted is False and new.name == "GaragePanel"


def test_deleted_panel_never_resurrects(core):
    """P72 contract: deleting must remember the MAC — the panel re-registers
    every few seconds and would resurrect instantly otherwise."""
    core, published = core
    panel = core.config.panels[0]
    core.config.deleted_macs.append("aabbccddee01")
    req = {"mac_origin": "AA:BB:CC:DD:EE:01", "friendly_name": "DemoPanel",
           "version": "0.1.0"}
    assert core.handle_register_request(json.dumps(req)) is False
    assert all(p.mac != "aabbccddee01" for p in core.config.panels)


def test_status_report_adopts_version_and_telemetry(core):
    core, published = core
    panel = core.handle_status_report(
        "DemoPanel",
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
        "DemoPanel", json.dumps({"version": "0.1.187", "state": "updating_fs"}))
    assert panel.online is False


def test_commands_route_to_verbatim_hostname_topic(core):
    core, published = core
    panel = core.config.panels[0]
    topic = core.send_reboot(panel)
    assert topic == "nspanel/DemoPanel/command"
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
