
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_homeassistant_custom_component.common import MockConfigEntry

async def test_http_identity(hass, enable_custom_integrations):
    hass.http = MagicMock()
    print("HTTP after assign:", type(hass.http).__name__, id(hass.http) % 100000)
    entry = MockConfigEntry(domain="nspanel_core", data={})
    entry.add_to_hass(hass)
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("custom_components.nspanel_core.firmware_store.fetch_manifest", new=AsyncMock(return_value=None)))
    stack.enter_context(patch("homeassistant.components.mqtt.async_publish", new=AsyncMock()))
    stack.enter_context(patch("homeassistant.components.mqtt.async_subscribe", new=AsyncMock(return_value=MagicMock())))
    stack.enter_context(patch("homeassistant.components.frontend.async_remove_panel"))
    stack.enter_context(patch("homeassistant.components.panel_custom.async_register_panel", new=AsyncMock()))
    stack.enter_context(patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", new=AsyncMock()))
    import importlib
    cc = importlib.import_module("custom_components.nspanel_core")
    with stack:
        r = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    print("HTTP after setup:", type(hass.http).__name__, id(hass.http) % 100000)
