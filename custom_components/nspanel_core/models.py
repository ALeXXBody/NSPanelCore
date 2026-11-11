"""Data model for NSPanel Core configuration, persisted in HA storage.

Replaces the shared SQLite schema the add-on used (web_room, web_entity,
web_roomentitiespage, web_scene, web_nspanel, web_settings). The panels see
exactly the same MQTT/protobuf contract — only the storage moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class LightConfig:
    id: int
    name: str
    ha_entity: str  # Home Assistant entity_id, e.g. "light.kitchen"
    room_id: int
    page_id: int
    page_slot: int
    light_type: str = "table"  # "ceiling" | "table"
    can_dim: bool = False
    can_color_temperature: bool = False
    can_rgb: bool = False
    controlled_from_main_page: bool = True

    # live state (mirrors what the C++ bridge kept in entity_data)
    state: bool = False
    brightness: int = 0  # 0-100
    color_temp: int = 0  # kelvin
    hue: int = 0
    saturation: int = 0
    mode: str = "default"  # "default" | "rgb"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LightConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class RoomConfig:
    id: int
    name: str
    display_order: int = 0
    temp_sensor_entity: str = ""  # optional HA sensor for room temperature


@dataclass
class EntityPageConfig:
    id: int
    room_id: int | None  # None = global page
    page_type: int = 4  # 4 / 8 / 12 entities
    is_scenes_page: bool = False
    display_order: int = 0


@dataclass
class SceneConfig:
    id: int
    name: str
    page_id: int
    page_slot: int
    ha_entity: str = ""  # "scene.x" or "script.x"; empty = NSPM-managed
    # NSPM-managed scenes carry saved light states
    light_states: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PanelConfig:
    id: int
    mac: str  # lowercase, no separators — as used in MQTT topics
    name: str
    model: str = "eu"
    room_id: int = 0
    accepted: bool = False
    denied: bool = False
    # Panel behaviour (subset of NSPanelSettings protobuf fields)
    default_page: int = 0  # 0=MAIN, 1=SCENES, 2=ROOM
    screensaver_mode: int = 0
    screensaver_activation_timeout: int = 15
    min_button_push_time: int = 50
    button_long_press_time: int = 400
    special_mode_trigger_time: int = 350
    special_mode_release_time: int = 600
    screen_dim_level: int = 0
    screensaver_dim_level: int = 20
    clock_us_style: bool = False
    use_fahrenheit: bool = False
    is_us_panel: bool = False
    reverse_relays: bool = False
    relay1_default_mode: bool = False
    relay2_default_mode: bool = False
    temperature_calibration: int = 0
    button1_mode: int = 0  # 0=DIRECT 1=FOLLOW 2=NOTIFY_MANAGER 3/4 thermostat
    button2_mode: int = 0
    raise_to_100_light_level: int = 0
    optimistic_mode: bool = False
    temperature_unit: str = "celsius"
    inside_temperature_sensor_topic: str = ""
    rooms: list[int] = field(default_factory=list)
    relay1_group: list[int] = field(default_factory=list)
    relay2_group: list[int] = field(default_factory=list)
    default_light_brightness: int = 0

    # runtime
    online: bool = False
    firmware_md5: str = ""
    tft_md5: str = ""
    littlefs_md5: str = ""


@dataclass
class GlobalSettings:
    manager_address: str = "core"
    mqtt_wait_time: int = 0
    clock_us_style: bool = False
    date_format: str = "%d/%m"
    color_temp_min: int = 2700
    color_temp_max: int = 6500
    reverse_color_temp: bool = False
    optimistic_mode: bool = False
    turn_on_behaviour: str = "color_temp"  # "color_temp" | "restore"
    light_turn_on_brightness: int = 0
    use_fahrenheit: bool = False
    weather_update_interval: int = 30
    location_latitude: str = ""
    location_longitude: str = ""
    outside_temp_sensor_entity: str = ""
    outside_temp_provider: str = ""
    precipitation_format: str = "mm"
    wind_speed_format: str = "kmh"


@dataclass
class IntegrationConfig:
    """Everything persisted in HA storage."""

    settings: GlobalSettings = field(default_factory=GlobalSettings)
    rooms: list[RoomConfig] = field(default_factory=list)
    lights: list[LightConfig] = field(default_factory=list)
    pages: list[EntityPageConfig] = field(default_factory=list)
    scenes: list[SceneConfig] = field(default_factory=list)
    panels: list[PanelConfig] = field(default_factory=list)
    next_id: dict[str, int] = field(default_factory=lambda: {"room": 1, "light": 1, "page": 1, "scene": 1, "panel": 1})

    def next_id_for(self, kind: str) -> int:
        value = self.next_id.get(kind, 1)
        self.next_id[kind] = value + 1
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": asdict(self.settings),
            "rooms": [asdict(r) for r in self.rooms],
            "lights": [l.to_dict() for l in self.lights],
            "pages": [asdict(p) for p in self.pages],
            "scenes": [asdict(s) for s in self.scenes],
            "panels": [asdict(p) for p in self.panels],
            "next_id": self.next_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntegrationConfig":
        cfg = cls()
        if not data:
            return cfg
        settings = data.get("settings", {})
        cfg.settings = GlobalSettings(**{k: v for k, v in settings.items() if k in GlobalSettings.__dataclass_fields__})
        cfg.rooms = [RoomConfig(**r) for r in data.get("rooms", [])]
        cfg.lights = [LightConfig.from_dict(l) for l in data.get("lights", [])]
        cfg.pages = [EntityPageConfig(**p) for p in data.get("pages", [])]
        cfg.scenes = [SceneConfig(**s) for s in data.get("scenes", [])]
        cfg.panels = [PanelConfig(**p) for p in data.get("panels", [])]
        cfg.next_id = data.get("next_id", cfg.next_id)
        return cfg
