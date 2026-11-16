"""v2 relay parity tests — the switch/sensor wire contract must hold in v2."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "custom_components" / "nspanel_core"


def _pkg():
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


def test_relay_command_wire_contract(core):
    core, published = core
    panel = core.config.panels[0]
    topic = core.set_relay(panel, 1, True)
    assert topic == "nspanel/DemoPanel/r1_cmd"      # hostname-based, VERBATIM
    assert published[-1][1] == "1"                     # "1"/"0", not JSON
    assert published[-1][2] is False
    core.set_relay(panel, 2, False)
    assert published[-1][0] == "nspanel/DemoPanel/r2_cmd"
    assert published[-1][1] == "0"


def test_relay_state_tracking(core):
    core, published = core
    panel = core.config.panels[0]
    core.handle_relay_state("DemoPanel", 1, "1")
    core.handle_relay_state("DemoPanel", 2, "0")
    assert core.relay_state(panel, 1) is True
    assert core.relay_state(panel, 2) is False
    assert core.handle_relay_state("UnknownHost", 1, "1") is None


def test_subscriptions_include_relay_topics(core):
    core, published = core
    subs = core.subscriptions()
    assert "nspanel/+/r1_state" in subs
    assert "nspanel/+/r2_state" in subs
