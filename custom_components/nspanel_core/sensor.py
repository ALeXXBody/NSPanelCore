"""Panel sensors — temperature, humidity, pressure, RSSI reported by panels."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import UnitOfTemperature, UnitOfPressure, PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT

from .const import DOMAIN, mac_for_connection, topic_safe

_LOGGER = logging.getLogger(__name__)

KINDS = {
    "temperature": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    "humidity": (PERCENTAGE, SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT),
    "pressure": (UnitOfPressure.HPA, SensorDeviceClass.PRESSURE, SensorStateClass.MEASUREMENT),
    "rssi": (SIGNAL_STRENGTH_DECIBELS_MILLIWATT, SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT),
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


class PanelSensor(SensorEntity):
    """Reports live values from a panel's NSPanelStatusReport."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, manager, panel, kind: str) -> None:
        self._manager = manager
        self._panel = panel
        self._kind = kind
        unit, device_class, state_class = KINDS[kind]
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_name = kind
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_{kind}"
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
    def native_value(self):
        return self._value
