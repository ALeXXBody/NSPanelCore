"""HA-runtime setup tests — the v2 glue must complete a REAL setup path.

These exist because three setup-path bugs (missing config_flow, the MQTT
not-connected race, the view base class) shipped before any real-runtime
verification. Every setup-path change must keep this file green."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "nspanel_core"


@pytest.fixture
def stub_http(hass):
    """The harness's hass has no HTTP layer — stub the surface the glue uses."""
    http = MagicMock()
    http.register_view = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    return http


@pytest.fixture
def runtime(enable_custom_integrations, hass, stub_http):
    """(hass, http-stub, ExitStack) — stack closed at teardown."""
    stack = ExitStack()
    yield hass, stub_http, stack
    stack.close()


def _apply_patches(stack: ExitStack, wire: "Wire | None" = None) -> "Wire | None":
    """Apply the runtime patches; returns the wire if one was requested."""
    if wire is None:
        wire = Wire()
    stack.enter_context(patch(
        "custom_components.nspanel_core.firmware_store.fetch_manifest",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_publish", new=wire.publish
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_subscribe", new=wire.subscribe
    ))
    stack.enter_context(patch(
        "homeassistant.components.frontend.async_remove_panel"
    ))
    stack.enter_context(patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(),
    ))
    return wire


class Wire:
    """Captures MQTT publishes + subscriptions, feeds messages to handlers."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []
        self.registered: list[str] = []
        self.handlers: dict[str, object] = {}

    def subscribe(self, hass, topic, callback, **kwargs):
        self.registered.append(topic)
        self.handlers[topic] = callback

        async def _unsub():
            return MagicMock()

        return _unsub()

    async def publish(self, topic, payload, retain=False, **kwargs):
        self.published.append((topic, str(payload), bool(retain)))

    async def feed(self, topic, payload):
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


def _register_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry_full_runtime(runtime):
    hass, stub_http, stack = runtime
    wire = _apply_patches(stack)
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ))
    entry = _register_entry(hass)

    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][entry.entry_id]
    print("DEBUG ids — fixture mock:", id(stub_http), "| hass.http:", id(hass.http), "| same:", hass.http is stub_http)
    assert data["core"] is not None
    assert data["save"] is not None

    topics = wire.registered
    assert "nspanel/mqttmanager/command" in topics
    assert "nspanel/+/status_report" in topics
    assert "nspanel/+/status" in topics
    assert "nspanel/+/r1_state" in topics
    assert "nspanel/+/r2_state" in topics

    # The real HTTP app is what views register on (the mqtt dependency pulls
    # the http integration in during setup — it replaces any stub).
    routes = str([r.resource for r in hass.http.app.router.routes()])
    for expected in ("/download_firmware", "/checksum_firmware",
                     "/download_data_file", "/checksum_data_file",
                     "/download_tft_eu", "/download_tft_us",
                     "/nspanel_core/ui"):
        assert expected in routes, f"route missing: {expected}"


async def test_setup_survives_register_failure(runtime):
    """A frontend-registration failure must not kill the integration."""
    hass, stub_http, stack = runtime
    _apply_patches(stack)
    stack.enter_context(patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ))
    entry = _register_entry(hass)

    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id]["core"] is not None


async def test_setup_survives_mqtt_not_connected(runtime):
    """P165: a publish failure at setup time must not fail the integration."""
    hass, stub_http, stack = runtime
    _apply_patches(stack)
    entry = _register_entry(hass)

    async def _not_ready(hass_, topic, payload, retain=False, **kwargs):
        raise HomeAssistantError(
            "Error talking to MQTT: The client is not currently connected."
        )

    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_publish", new=_not_ready
    ))
    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id]["core"] is not None


async def test_setup_waits_for_mqtt_client_before_subscribing(runtime):
    """P167: subscriptions must never run before the MQTT client is ready."""
    hass, stub_http, stack = runtime
    order = []

    async def _wait(hass_):
        order.append("wait")
        return True

    async def _sub(hass_, topic, callback, **kwargs):
        order.append("sub")
        return AsyncMock()

    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=_wait
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_subscribe", new=_sub
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_publish", new=AsyncMock()
    ))
    stack.enter_context(patch(
        "homeassistant.components.frontend.async_remove_panel"
    ))
    stack.enter_context(patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(),
    ))
    entry = _register_entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert order and order[0] == "wait"
    assert "sub" in order


async def test_setup_fails_gracefully_when_subscribe_raises(runtime):
    """If MQTT is genuinely broken, setup fails for HA to retry — no crash."""
    hass, stub_http, stack = runtime
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_subscribe",
        new=AsyncMock(side_effect=HomeAssistantError("mqtt_not_setup_cannot_subscribe")),
    ))
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_publish", new=AsyncMock()
    ))
    stack.enter_context(patch(
        "homeassistant.components.frontend.async_remove_panel"
    ))
    stack.enter_context(patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(),
    ))
    entry = _register_entry(hass)

    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert result is False or result is None, "must fail without raising to the caller"


async def test_dashboard_page_renders_registered_panels(runtime):
    """P170: the dashboard page must reflect the LIVE core at request time
    — a panel registered AFTER setup appears in the rendered HTML."""
    hass, stub_http, stack = runtime
    wire = Wire()
    wire = _apply_patches(stack, wire)
    stack.enter_context(patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()
    ))
    entry = _register_entry(hass)

    with wire:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await wire.feed("nspanel/mqttmanager/command", json.dumps({
            "command": "register_request",
            "mac_origin": "aa:bb:cc:dd:ee:09",
            "friendly_name": "RenderPanel",
            "version": "0.1.1",
        }))
        await hass.async_block_till_done()

    import custom_components.nspanel_core.dashboard as dash
    page_view = dash.DashboardPage()
    core = hass.data[DOMAIN][entry.entry_id]["core"]
    core.config.panels[0].accepted = True

    req = MagicMock()
    req.app = {"hass": hass}
    resp = await page_view.get(req)
    body = resp.text
    assert "RenderPanel" in body, "the registered panel must render on the page"
    assert "0.1.1" in body
