"""NSPanel Core v2 — typed models (rewrite of models.py, no legacy fields)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Panel:
    """A wall panel known to the manager. Identity = MAC."""

    mac: str
    name: str = ""
    wifi_hostname: str = ""          # the VERBATIM hostname topics are built from
    version: str = "UNKNOWN"         # running firmware version (from registration
                                     # AND refreshed from every status report)
    model: str = "sonoff"
    ip: str = ""
    rssi: int | None = None
    temperature: float | None = None
    heap_used_pct: int | None = None
    online: bool = False
    accepted: bool = False
    denied: bool = False
    firmware_md5: str = ""
    littlefs_md5: str = ""
    tft_md5: str = ""
    has_humidity: bool = False
    has_pressure: bool = False
    warnings: list = field(default_factory=list)
    relay_states: dict = field(default_factory=dict)
    last_seen: datetime = field(default_factory=_utcnow)

    @property
    def id(self) -> int:
        """Stable integer id derived from the MAC (compat with v1 dashboards)."""
        return int(self.mac.replace(":", ""), 16) % 1000000

    def topic_base(self) -> str:
        from .const import panel_mqtt_base
        return panel_mqtt_base(self.wifi_hostname or self.name)

    def command_topic(self) -> str:
        return f"nspanel/{self.topic_base()}/command"

    def status_report_topic(self) -> str:
        from .const import panel_topic
        return panel_topic(self.mac, "status_report")

    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "wifi_hostname": self.wifi_hostname,
            "version": self.version,
            "model": self.model,
            "ip": self.ip,
            "rssi": self.rssi,
            "temperature": self.temperature,
            "heap_used_pct": self.heap_used_pct,
            "online": self.online,
            "accepted": self.accepted,
            "denied": self.denied,
            "firmware_md5": self.firmware_md5,
            "littlefs_md5": self.littlefs_md5,
            "tft_md5": self.tft_md5,
            "has_humidity": self.has_humidity,
            "has_pressure": self.has_pressure,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Panel":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Light:
    """A light mapped to one panel button."""

    name: str = ""
    ha_entity: str = ""
    page: str = "home"
    slot: int = 1


@dataclass
class Thermostat:
    name: str = ""
    ha_entity: str = ""
    entity_id: str = ""


@dataclass
class Settings:
    """Manager settings (persisted)."""

    manager_address: str = "core"
    manager_port: int = 8000
    color_temp_min: int = 2700
    color_temp_max: int = 6500
    date_format: str = "%d/%m"
    location_latitude: str = ""
    location_longitude: str = ""
    weather_entity: str = ""
    weather_update_interval: int = 30
    precipitation_format: str = "mm"
    wind_speed_format: str = "kmh"
    use_fahrenheit: bool = False
    reverse_color_temp: bool = False
    clock_us_style: bool = False
    optimistic_mode: bool = False
    turn_on_behaviour: str = "color_temp"
    light_turn_on_brightness: int = 0
    firmware_last_check: str = ""
    firmware_latest_version: str = ""
