"""v2 switch platform (panel relays 1/2)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import platforms
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    core = hass.data[DOMAIN][entry.entry_id]["core"]
    entities: list[SwitchEntity] = []
    for panel in core.config.panels:
        if panel.accepted and not panel.denied:
            for relay in (1, 2):
                entities.append(platforms.RelaySwitch(entry, core, panel, relay))
    if entities:
        async_add_entities(entities)
