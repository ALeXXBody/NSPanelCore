"""The NSPanel Core integration.

A Home Assistant-native replacement for the NSPanel Core add-on: manages
Sonoff NSPanel panels over MQTT using the same protobuf wire protocol the
panels' firmware already speaks, and exposes panel data as native HA entities.

Architecture (see BRIDGE_GO_REWRITE.md for the full wire contract):
- Panel <-> integration: MQTT, protobuf + JSON (same topics as the add-on)
- Integration <-> HA: event bus (state changes), service calls — no WebSocket
  client, no token, no separate process.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .manager import NSPanelManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NSPanel Core from a config entry."""
    # The MQTT integration must be present and configured.
    if "mqtt" not in hass.config.components:
        raise ConfigEntryNotReady("The MQTT integration is required")

    manager = NSPanelManager(hass, entry)
    await manager.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("NSPanel Core integration started")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: NSPanelManager = hass.data[DOMAIN][entry.entry_id]
    await manager.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
