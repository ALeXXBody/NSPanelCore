"""Panel relay switches (button1/button2 relays)."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    def _add_new():
        new_entities = []
        for panel in manager.panels():
            for relay in (1, 2):
                unique = f"{DOMAIN}_{panel.mac}_relay{relay}"
                if panel.accepted and unique not in added:
                    added.add(unique)
                    new_entities.append(RelaySwitch(entry, manager, panel, relay))
        if new_entities:
            async_add_entities(new_entities)

    _add_new()
    entry.async_on_unload(manager.add_new_panel_listener(_add_new))


class RelaySwitch(CoordinatorEntity, SwitchEntity):
    """Controls a panel relay via nspanel/<mac>/relayN_cmd ("1"/"0")."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager, panel, relay: int) -> None:
        self._manager = manager
        self._panel = panel
        self._relay = relay
        self._attr_name = f"{panel.name} Relay {relay}"
        self._attr_unique_id = f"{DOMAIN}_{panel.mac}_relay{relay}"
        self._state = False
        entry.async_on_unload(manager.add_relay_listener(panel.mac, relay, self._on_state))

    def _on_state(self, state: bool) -> None:
        self._state = state
        self.schedule_update_ha_state()

    def _subscribe_topic(self) -> str:
        return f"nspanel/{self._panel.mac}/relay{self._relay}_state"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._panel.mac)},
            name=self._panel.name,
            manufacturer="Sonoff",
            model=f"NSPanel ({self._panel.model})",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        await self._manager.set_relay(self._panel.mac, self._relay, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._manager.set_relay(self._panel.mac, self._relay, False)
