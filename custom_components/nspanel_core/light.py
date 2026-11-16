"""Panel relays registered as lights (v1 parity: per-panel relay_is_light)."""

from __future__ import annotations

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import platforms
from .const import DOMAIN, mac_for_connection, topic_safe


class RelayLight(LightEntity):
    """A panel relay exposed as a light (on/off only)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, core, panel, relay: int) -> None:
        self._core = core
        self._panel = panel
        self._relay = relay
        self._attr_name = f"Light {relay}"
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_relay{relay}_as_light"
        self._attr_device_info = platforms._device_info(panel)

    @property
    def is_on(self) -> bool:
        return self._core.relay_state(self._panel, self._relay)

    @property
    def available(self) -> bool:
        return self._panel.online

    async def async_turn_on(self, **kwargs) -> None:
        self._core.set_relay(self._panel, self._relay, True)

    async def async_turn_off(self, **kwargs) -> None:
        self._core.set_relay(self._panel, self._relay, False)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    core = hass.data[DOMAIN][entry.entry_id]["core"]
    entities: list[LightEntity] = []
    for panel in core.config.panels:
        if panel.accepted and not panel.denied:
            for relay in (1, 2):
                if panel.relay_is_light.get(relay, False):
                    entities.append(RelayLight(entry, core, panel, relay))
    if entities:
        async_add_entities(entities)
