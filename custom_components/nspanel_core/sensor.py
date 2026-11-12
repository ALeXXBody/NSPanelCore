"""Panel sensors — temperature, humidity, pressure, RSSI reported by panels."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

KINDS = {
    "temperature": ("°C", "temperature"),
    "humidity": ("%", "humidity"),
    "pressure": ("hPa", "pressure"),
    "rssi": ("dBm", "signal_strength"),
}


async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    def _add_new():
        new_entities = []
        for panel in manager.panels():
            for kind in KINDS:
                unique = f"{DOMAIN}_{panel.mac}_{kind}"
                if panel.accepted and unique not in added:
                    added.add(unique)
                    new_entities.append(PanelSensor(entry, manager, panel, kind))
        if new_entities:
            async_add_entities(new_entities)

    _add_new()
    entry.async_on_unload(manager.add_new_panel_listener(_add_new))


class PanelSensor(CoordinatorEntity, SensorEntity):
    """Reports live values from a panel's NSPanelStatusReport."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager, panel, kind: str) -> None:
        self._manager = manager
        self._panel = panel
        self._kind = kind
        unit, device_class = KINDS[kind]
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_name = f"{panel.name} {kind}"
        self._attr_unique_id = f"{DOMAIN}_{panel.mac}_{kind}"
        self._value = None
        entry.async_on_unload(manager.add_report_listener(self._on_report))

    def _on_report(self, mac: str, report) -> None:
        if mac != self._panel.mac:
            return
        value = {
            "temperature": lambda: report.get("temperature"),
            "humidity": lambda: report.get("humidity") if report.get("has_humidity") else None,
            "pressure": lambda: report.get("pressure") if report.get("has_pressure") else None,
            "rssi": lambda: report.get("rssi"),
        }[self._kind]()
        if value is not None:
            self._value = value
            self.schedule_update_ha_state()

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
    def native_value(self):
        return self._value
