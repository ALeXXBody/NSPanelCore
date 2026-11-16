"""HA-runtime setup test — the v2 glue must complete a REAL setup path:
subscriptions registered, core built, OTA views registered, the sidebar
panel registered, time publishing started. This is the test that should
have existed before the first HACS release (the missing-sidebar incident
would have been caught locally)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "nspanel_core"


@pytest.fixture
def stub_http(hass):
    """The test harness's hass has no HTTP layer — stub the surface the glue uses."""
    http = MagicMock()
    http.register_view = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    return http


async def test_setup_entry_full_runtime(enable_custom_integrations, hass, stub_http):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.mqtt.async_subscribe", return_value=MagicMock()
    ) as mock_sub, patch(
        "homeassistant.components.mqtt.async_publish", new=AsyncMock()
    ), patch(
        "homeassistant.components.frontend.async_remove_panel"
    ), patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(),
    ) as mock_register_panel:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][entry.entry_id]
    assert data["core"] is not None, "core must exist after setup"
    assert data["save"] is not None, "persistence hook must exist"

    # MQTT subscriptions: manager command, status, status_report, relay x2
    topics = [c.args[1] for c in mock_sub.call_args_list]
    assert "nspanel/mqttmanager/command" in topics
    assert "nspanel/+/status_report" in topics
    assert "nspanel/+/r1_state" in topics
    assert "nspanel/+/r2_state" in topics

    # OTA views registered (6 endpoints)
    assert stub_http.register_view.call_count == 8  # 6 OTA + dashboard + action

    # The sidebar panel must have been registered (the missing-sidebar bug)
    assert mock_register_panel.await_count == 1, (
        "sidebar panel registration must run during setup"
    )
    args = mock_register_panel.await_args
    assert args.kwargs.get("sidebar_title") == "NSPanel Core"

    # Static assets (panel.js shim) served
    assert stub_http.async_register_static_paths.await_count == 1


async def test_setup_survives_register_failure(enable_custom_integrations, hass, stub_http):
    """The dashboard registration failure must not kill the whole setup —
    the panel keeps working even if the frontend registration throws."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.mqtt.async_subscribe", return_value=MagicMock()
    ), patch(
        "homeassistant.components.mqtt.async_publish", new=AsyncMock()
    ), patch(
        "homeassistant.components.frontend.async_remove_panel"
    ), patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    data = hass.data[DOMAIN][entry.entry_id]
    assert data["core"] is not None, "core must survive a frontend registration failure"
