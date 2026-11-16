"""NSPanel Core v2 — HA entity platforms (parity port of v1's
sensor.py/switch.py/light.py, adapted to the v2 core API).

One platform file set, driven by the Core: sensors + relay switches +
relay-as-light entities. Registered from __init__.py via
async_forward_entry_setups.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, mac_for_connection, topic_safe

_LOGGER = logging.getLogger(__name__)


def _device_info(panel) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, mac_for_connection(panel.mac) or panel.mac)},
        name=panel.name or "NSPanel",
        manufacturer="NSPanel Core",
        model=panel.model,
    )


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

KINDS = {
    "temperature": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE,
                    SensorStateClass.MEASUREMENT, None),
    "rssi": (SIGNAL_STRENGTH_DECIBELS_MILLIWATT, SensorDeviceClass.SIGNAL_STRENGTH,
             SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC),
    "heap": (PERCENTAGE, None, SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC),
    "ip": (None, None, None, EntityCategory.DIAGNOSTIC),
}


class PanelSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, core, panel, kind: str) -> None:
        unit, device_class, state_class, category = KINDS[kind]
        self._core = core
        self._panel = panel
        self._kind = kind
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = category
        self._attr_name = kind
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_{kind}"
        self._attr_device_info = _device_info(panel)

    @property
    def native_value(self):
        return {
            "temperature": self._panel.temperature,
            "rssi": self._panel.rssi,
            "heap": self._panel.heap_used_pct,
            "ip": self._panel.ip,
        }.get(self._kind)

    @property
    def available(self) -> bool:
        return self._panel.online


# ---------------------------------------------------------------------------
# Relay switches (button1/button2 relays not flagged as light)
# ---------------------------------------------------------------------------

class RelaySwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, core, panel, relay: int) -> None:
        self._core = core
        self._panel = panel
        self._relay = relay
        self._attr_name = f"Relay {relay}"
        self._attr_unique_id = f"{DOMAIN}_{topic_safe(panel.mac)}_relay{relay}"
        self._attr_device_info = _device_info(panel)

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
