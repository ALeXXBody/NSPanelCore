"""Regression tests for entity platforms (switch/sensor/light).

Run with an HA dev venv:
    /tmp/opencode/ha-venv-2611/bin/python -m pytest tests/ -v

Covers the setup paths that crashed in production (light platform
UnboundLocalError on setup with panels present): entity creation,
is_light routing between switch/light, denied/unaccepted cleanup,
relay-state hydration, and toggling through the manager.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

pytest.importorskip("homeassistant")

import homeassistant.helpers.entity_registry as er  # noqa: E402
from nspanel_core import light as LI  # noqa: E402
from nspanel_core import sensor as SE  # noqa: E402
from nspanel_core import switch as SW  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402


class FakeReg:
    def __init__(self):
        self.entities = {}
        self.removed = []

    def async_get_entity_id(self, domain, integ, uid):
        return self.entities.get((domain, uid))

    def async_remove(self, entity_id):
        self.removed.append(entity_id)
        for key, val in list(self.entities.items()):
            if val == entity_id:
                del self.entities[key]


class FakeHass:
    def __init__(self, manager):
        self.data = {DOMAIN: {"entry1": manager}}
        self.reg = FakeReg()


class FakeEntry:
    entry_id = "entry1"

    def __init__(self):
        self.unloads = []

    def async_on_unload(self, fn):
        self.unloads.append(fn)


class FakeManager:
    def __init__(self, cfg):
        self.config = cfg
        self._nl = []
        self._rep = []
        self._rel = {}
        self.relay_state_map = {}

    def panels(self):
        return list(self.config.panels)

    def add_new_panel_listener(self, listener):
        self._nl.append(listener)
        return lambda: self._nl.remove(listener)

    def add_report_listener(self, listener):
        self._rep.append(listener)
        return lambda: self._rep.remove(listener)

    def add_relay_listener(self, panel, relay, listener):
        key = (panel.mac, relay)
        self._rel.setdefault(key, []).append(listener)
        return lambda: self._rel[key].remove(listener)

    def relay_state(self, panel, relay):
        return self.relay_state_map.get((panel.mac, relay), False)

    async def set_relay(self, panel, relay, state):
        self.relay_state_map[(panel.mac, relay)] = state

    def notify_panels_changed(self):
        for listener in list(self._nl):
            listener()


async def _setup(mod, manager):
    hass, entry = FakeHass(manager), FakeEntry()
    orig = er.async_get
    er.async_get = lambda h: hass.reg
    added = []

    def _add(ents):
        # NOTE: sync on purpose — HA calls async_add_entities without await.
        # An async def here silently drops every entity (never-awaited coroutine).
        added.extend(ents)

    try:
        await mod.async_setup_entry(hass, entry, _add)
    finally:
        er.async_get = orig
    return hass, added


@pytest.fixture()
def manager():
    cfg = IntegrationConfig()
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    return FakeManager(cfg)


async def test_light_setup_with_panels_present_no_crash(manager):
    """Regression: set-comprehension clause order crashed setup (UnboundLocalError)."""
    manager.config.panels.append(
        PanelConfig(id=1, mac="aa", name="A", accepted=True, relay1_is_light=True)
    )
    hass, added = await _setup(LI, manager)
    assert [e._attr_unique_id for e in added] == [f"{DOMAIN}_aa_relay1_as_light"]


async def test_relay_is_light_routing(manager):
    manager.config.panels.append(
        PanelConfig(id=1, mac="aa", name="A", accepted=True, relay1_is_light=True)
    )
    manager.config.panels.append(PanelConfig(id=2, mac="bb", name="B", accepted=True))
    manager.config.panels.append(PanelConfig(id=3, mac="cc", name="C", accepted=False))
    _, sw = await _setup(SW, manager)
    _, li = await _setup(LI, manager)
    assert sorted(e._attr_unique_id for e in sw) == [
        f"{DOMAIN}_aa_relay2",
        f"{DOMAIN}_bb_relay1",
        f"{DOMAIN}_bb_relay2",
    ]
    assert [e._attr_unique_id for e in li] == [f"{DOMAIN}_aa_relay1_as_light"]


async def test_stale_entities_removed_on_flip_and_deny(manager):
    manager.config.panels.append(
        PanelConfig(id=2, mac="bb", name="B", accepted=True)
    )
    hass, _ = await _setup(SW, manager)
    hass.reg.entities[("switch", f"{DOMAIN}_bb_relay1")] = "switch.b_relay1"
    panel = manager.config.panels[0]
    panel.relay1_is_light = True
    er_orig = er.async_get
    er.async_get = lambda h: hass.reg
    try:
        manager.notify_panels_changed()
    finally:
        er.async_get = er_orig
    assert "switch.b_relay1" in hass.reg.removed
    panel.accepted = False
    panel.denied = True
    er.async_get = lambda h: hass.reg
    try:
        manager.notify_panels_changed()
    finally:
        er.async_get = er_orig
    assert "switch.b_relay1" in hass.reg.removed


async def test_relay_hydration_and_toggle(manager):
    manager.config.panels.append(
        PanelConfig(id=2, mac="bb", name="B", accepted=True)
    )
    manager.relay_state_map[("bb", 2)] = True
    _, sw = await _setup(SW, manager)
    sw2 = next(e for e in sw if e._relay == 2)
    assert sw2.is_on is True
    await sw2.async_turn_off()
    assert manager.relay_state_map[("bb", 2)] is False


async def test_sensor_kinds_gated_by_capability(manager):
    manager.config.panels.append(
        PanelConfig(id=1, mac="aa", name="A", accepted=True)
    )
    _, added = await _setup(SE, manager)
    kinds = sorted(e._kind for e in added)
    assert kinds == ["heap", "ip", "rssi", "temperature"]
