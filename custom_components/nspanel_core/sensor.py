"""v2 sensor platform (temperature/rssi/heap/ip)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import platforms
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    core = hass.data[DOMAIN][entry.entry_id]["core"]
    entities = []
    for panel in core.config.panels:
        if panel.accepted and not panel.denied:
            for kind in platforms.KINDS:
                entities.append(platforms.PanelSensor(entry, core, panel, kind))
    if entities:
        async_add_entities(entities)
