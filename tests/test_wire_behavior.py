"""Deep-audit runtime behavior tests (P162) — wire behaviors exercised through
the REAL setup path with a captured MQTT wire held open for the whole test."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "nspanel_core"

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


class Wire:
    """Captures MQTT publishes + subscriptions, feeds messages to handlers."""

    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []
        self.registered: list[str] = []
        self.handlers: dict[str, object] = {}

    def subscribe(self, hass, topic, callback, **kwargs):
        self.registered.append(topic)
        self.handlers[topic] = callback

        async def _unsub():
            return MagicMock()

        return _unsub()  # the glue awaits this (the unsub handle)

    async def publish(self, topic, payload, retain=False, **kwargs):
        self.published.append((topic, str(payload), bool(retain)))

    async def feed(self, topic, payload):
        """Deliver a message to the matching handler (wildcard aware)."""
        parts = topic.split("/")
        for t, handler in self.handlers.items():
            tparts = t.split("/")
            if len(tparts) != len(parts):
                continue
            if all(p == "+" or p == s for p, s in zip(tparts, parts)):
                coro = handler(type("Msg", (), {"topic": topic, "payload": payload}))
                if coro is not None:
                    await coro
                return True
        return False


@pytest.fixture
def wire():
    return Wire()


async def _setup(hass, wire: Wire, storage=None, request=None):
    """Run the real setup path with the MQTT/fetch patches held open for the
    whole test (feeds may happen at any point). Returns (data, hass)."""
    stack = contextlib.AsyncExitStack()
    if request is not None:
        request.addfinalizer(lambda: asyncio.get_event_loop().run_until_complete(stack.aclose()))

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    http = MagicMock()
    http.register_view = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    if storage is not None:
        from homeassistant.helpers.storage import Store

        await Store(hass, 1, "nspanel_core_state.json").async_save(storage)

    def _publish(hass_, topic, payload, retain=False, **kwargs):
        return wire.publish(topic, payload, retain=retain)

    def _subscribe(hass_, topic, callback, **kwargs):
        return wire.subscribe(hass_, topic, callback)

    stack.enter_context(
        patch("custom_components.nspanel_core.firmware_store.fetch_manifest",
              new=AsyncMock(return_value=None))
    )
    stack.enter_context(
        patch("homeassistant.components.mqtt.async_publish", new=_publish)
    )
    stack.enter_context(
        patch("homeassistant.components.mqtt.async_subscribe", new=_subscribe)
    )
    stack.enter_context(
        patch("homeassistant.components.frontend.async_remove_panel")
    )
    stack.enter_context(
        patch("homeassistant.components.panel_custom.async_register_panel",
              new=AsyncMock())
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id], hass


async def _settle(hass):
    await asyncio.sleep(0)
    await hass.async_block_till_done()


async def test_registration_end_to_end(hass, wire: Wire, request):
    data, hass = await _setup(hass, wire, request=request)
    core = data["core"]

    await wire.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:01",
        "friendly_name": "DemoPanel",
        "version": "0.1.0",
        "md5_firmware": "f" * 32,
    }))
    await _settle(hass)
    panel = core.panel_by_mac("aa:bb:cc:dd:ee:01")
    assert panel is not None and panel.accepted is False
    assert not [p for p in wire.published
                if p[0] == "nspanel/DemoPanel/command"], (
        "no accept reply before acceptance")

    panel.accepted, panel.denied = True, False
    await data["save"]()
    await wire.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:01",
        "friendly_name": "DemoPanel",
        "version": "0.1.0",
    }))
    await _settle(hass)
    replies = [p for p in wire.published if p[0] == "nspanel/DemoPanel/command"]
    assert replies, "accepted panel must receive the accept reply"
    body = json.loads(replies[-1][1])
    assert body["command"] == "register_accept"
    assert replies[-1][2] is True  # retained


async def test_status_report_updates_version_and_telemetry(hass, wire: Wire, request):
    data, hass = await _setup(hass, wire, request=request)
    core = data["core"]
    await wire.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:01",
        "friendly_name": "DemoPanel",
        "version": "0.1.0",
    }))
    await _settle(hass)
    await wire.feed("nspanel/DemoPanel/status_report", json.dumps({
        "version": "0.1.1", "rssi": -60, "temperature": "22.5",
        "heap_used_pct": 40, "ip": "10.0.0.5", "warnings": "",
    }))
    await _settle(hass)
    panel = core.panel_by_mac("aa:bb:cc:dd:ee:01")
    assert panel.version == "0.1.1"
    assert panel.temperature == 22.5
    assert panel.ip == "10.0.0.5"
    assert panel.online is True


async def test_deleted_mac_never_resurrects_after_restart(hass, wire: Wire, request):
    data, hass = await _setup(hass, wire, request=request)
    core = data["core"]
    await wire.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:02",
        "friendly_name": "GonePanel"}))
    await _settle(hass)
    core.config.deleted_macs.append("aabbccddee02")
    core.config.panels = [
        p for p in core.config.panels if p.mac != "aabbccddee02"
    ]
    await data["save"]()

    from homeassistant.helpers.storage import Store

    saved = await Store(hass, 1, "nspanel_core_state.json").async_load()
    assert saved["deleted_macs"] == ["aabbccddee02"]

    wire2 = Wire()
    data2, hass = await _setup(hass, wire2, storage=saved, request=request)
    await wire2.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:02",
        "friendly_name": "GonePanel"}))
    await _settle(hass)
    core2 = data2["core"]
    assert core2.panel_by_mac("aa:bb:cc:dd:ee:02") is None, (
        "deleted panel must never resurrect across restarts")


async def test_relay_command_flow(hass, wire: Wire, request):
    data, hass = await _setup(hass, wire, request=request)
    core = data["core"]
    await wire.feed("nspanel/mqttmanager/command", json.dumps({
        "command": "register_request",
        "mac_origin": "aa:bb:cc:dd:ee:01",
        "friendly_name": "DemoPanel",
        "version": "0.1.0"}))
    await _settle(hass)
    core.config.panels[0].accepted = True
    core.set_relay(core.config.panels[0], 1, True)
    await _settle(hass)
    cmds = [p for p in wire.published if p[0] == "nspanel/DemoPanel/r1_cmd"]
    assert cmds and cmds[-1][1] == "1" and cmds[-1][2] is False
    await wire.feed("nspanel/DemoPanel/r1_state", "1")
    await _settle(hass)
    assert core.relay_state(core.config.panels[0], 1) is True


async def test_ota_serving_refuses_without_active_set(hass, wire: Wire, request):
    data, hass = await _setup(hass, wire, request=request)
    views = [c.args[0] for c in hass.http.register_view.call_args_list]
    dl = next(v for v in views if getattr(v, "url", "") == "/download_firmware")
    resp = await dl.get(MagicMock())
    assert resp.status == 503, "no active set → must refuse, never fall back"


async def test_ota_serving_serves_active_bytes(hass, wire: Wire, request):
    import custom_components.nspanel_core.firmware_store as _fs  # installed tree

    data, hass = await _setup(hass, wire, request=request)
    tmp = pathlib.Path(hass.config.path()) / "nspanel_core" / "fwtest"
    tmp.mkdir(parents=True, exist_ok=True)
    blob = b"NATIVEFW" * 16
    f = tmp / "firmware.bin"
    f.write_bytes(blob)
    data["active"] = _fs.ActiveFirmware(
        version="9.9.9-test",
        files={"firmware/sonoff/firmware.bin": str(f)},
        md5s={},
    )
    views = [c.args[0] for c in hass.http.register_view.call_args_list]
    ck = next(v for v in views if getattr(v, "url", "") == "/checksum_firmware")
    resp = await ck.get(MagicMock())
    assert resp.status == 200
    assert hashlib.md5(blob).hexdigest() == resp.text
