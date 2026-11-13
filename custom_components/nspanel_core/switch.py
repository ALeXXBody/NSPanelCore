"""Panel relay switches (button1/button2 relays)."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, mac_for_connection, topic_safe

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    def _wanted(panel, relay: int) -> bool:
        # Relays flagged "register as light" live in the light platform.
        return (
            bool(panel.accepted)
            and not bool(panel.denied)
            and not bool(getattr(panel, f"relay{relay}_is_light", False))
        )

    def _add_new():
        new_entities = []
        for panel in manager.panels():
            for relay in (1, 2):
                unique = f"{DOMAIN}_{topic_safe(panel.mac)}_relay{relay}"
                if _wanted(panel, relay) and unique not in added:
                    added.add(unique)
                    new_entities.append(RelaySwitch(entry, manager, panel, relay))
        if new_entities:
            async_add_entities(new_entities)
        _remove_stale()

    def _remove_stale() -> None:
        """Drop switches for removed/denied panels AND relays flipped to light."""
        from homeassistant.helpers import entity_registry as er

        try:
            reg = er.async_get(hass)
        except Exception:  # noqa: BLE001
            return
        live = {
            f"{DOMAIN}_{topic_safe(p.mac)}_relay{r}"
            for p in manager.panels()
            for r in (1, 2)
            if _wanted(p, r)
        }
        for unique in list(added):
            if unique not in live:
                entity_id = reg.async_get_entity_id("switch", DOMAIN, unique)
                if entity_id is not None:
                    reg.async_remove(entity_id)
                added.discard(unique)

    _add_new()
    entry.async_on_unload(manager.add_new_panel_listener(_add_new))


class RelaySwitch(SwitchEntity):
    """Controls a panel relay via nspanel/<mac>/relayN_cmd ("1"/"0")."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, manager, panel, relay: int) -> None:
        self._manager = manager
        self._panel = panel
        self._relay = relay
        self._attr_name = f"Relay {relay}"
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_relay{relay}"
        try:
            self._state = bool(manager.relay_state(self._panel, self._relay))
        except Exception:  # noqa: BLE001
            self._state = False
        entry.async_on_unload(manager.add_relay_listener(panel, relay, self._on_state))

    def _on_state(self, state: bool) -> None:
        self._state = state
        self.schedule_update_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

        conn = mac_for_connection(self._panel.mac)
        return DeviceInfo(
            identifiers={(DOMAIN, topic_safe(self._panel.mac))},
            connections={(CONNECTION_NETWORK_MAC, conn)} if conn else set(),
            name=self._panel.name,
            manufacturer="Sonoff",
            model=f"NSPanel ({self._panel.model})",
        )

    @property
    def is_on(self) -> bool:
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        await self._manager.set_relay(self._panel, self._relay, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._manager.set_relay(self._panel, self._relay, False)
