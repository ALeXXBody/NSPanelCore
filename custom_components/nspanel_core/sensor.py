"""Panel sensors — temperature, humidity, pressure, RSSI, IP and heap reported by panels."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, mac_for_connection, topic_safe

_LOGGER = logging.getLogger(__name__)

# kind -> (unit, device_class, state_class, entity_category)
KINDS = {
    "temperature": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, None),
    "humidity": (PERCENTAGE, SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, None),
    "pressure": (UnitOfPressure.HPA, SensorDeviceClass.PRESSURE, SensorStateClass.MEASUREMENT, None),
    "rssi": (SIGNAL_STRENGTH_DECIBELS_MILLIWATT, SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC),
    "ip": (None, None, None, EntityCategory.DIAGNOSTIC),
    "heap": (PERCENTAGE, None, SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC),
}

# Capabilities required before the entity is created (plain ESP32 panels
# have neither sensor — creating them anyway leaves permanent Unknowns).
REQUIRES_CAPABILITY = {
    "humidity": "has_humidity",
    "pressure": "has_pressure",
}


def _wanted_kinds(panel) -> list[str]:
    kinds = []
    for kind in KINDS:
        cap = REQUIRES_CAPABILITY.get(kind)
        if cap is not None and not getattr(panel, cap, False):
            continue
        kinds.append(kind)
    return kinds


async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    def _add_new():
        new_entities = []
        for panel in manager.panels():
            if not panel.accepted:
                continue
            for kind in _wanted_kinds(panel):
                unique = f"{DOMAIN}_{topic_safe(panel.mac)}_{kind}"
                if unique not in added:
                    added.add(unique)
                    new_entities.append(PanelSensor(entry, manager, panel, kind))
        if new_entities:
            async_add_entities(new_entities)
        _remove_incapable()

    def _remove_incapable() -> None:
        """Drop humidity/pressure entities for panels that never reported
        the capability — they would sit at Unknown forever."""
        from homeassistant.helpers import entity_registry as er

        try:
            reg = er.async_get(hass)
        except Exception:  # noqa: BLE001
            return
        for panel in manager.panels():
            for kind, cap in REQUIRES_CAPABILITY.items():
                if getattr(panel, cap, False):
                    continue
                unique = f"{DOMAIN}_{topic_safe(panel.mac)}_{kind}"
                entity_id = reg.async_get_entity_id("sensor", DOMAIN, unique)
                if entity_id is not None:
                    reg.async_remove(entity_id)

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
        unit, device_class, state_class, entity_category = KINDS[kind]
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = entity_category
        self._attr_name = kind
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_{kind}"
        self._value = None
        entry.async_on_unload(manager.add_report_listener(self._on_report))

    def _on_report(self, mac: str, report) -> None:
        if mac != self._panel.mac:
            return
        raw = {
            "temperature": report.get("temperature"),
            "humidity": report.get("humidity") if report.get("has_humidity") else None,
            "pressure": report.get("pressure") if report.get("has_pressure") else None,
            "rssi": report.get("rssi"),
            "ip": report.get("ip"),
            "heap": report.get("heap_used_pct"),
        }.get(self._kind)
        value = self._coerce(raw)
        if value is not None:
            self._value = value
            self.schedule_update_ha_state()

    def _coerce(self, raw):
        if raw is None:
            return None
        if self._kind == "ip":
            text = str(raw).strip()
            return text or None
        try:
            num = float(raw)
        except (ValueError, TypeError):
            return None
        if self._kind == "rssi":
            return int(num)
        return round(num, 1)

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
