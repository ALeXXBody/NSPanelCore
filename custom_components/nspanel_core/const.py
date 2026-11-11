"""Constants for the NSPanel Core integration."""

from __future__ import annotations

DOMAIN = "nspanel_core"

# MQTT topic templates (wire-compatible with the panels' firmware).
TOPIC_ROOT = "nspanel"

TOPIC_PANEL_STATUS = "nspanel/+/status"
TOPIC_PANEL_COMMAND = "nspanel/+/command"
TOPIC_PANEL_STATUS_REPORT = "nspanel/+/status_report"
TOPIC_MANAGER_COMMAND = "nspanel/mqttmanager/command"

# Per-panel (mac formatted without colons, lowercase — as the firmware uses)
def panel_topic(mac: str, suffix: str) -> str:
    return f"nspanel/{mac}/{suffix}"


def manager_prefix(manager_address: str) -> str:
    return f"nspanel/mqttmanager_{manager_address}"


def room_state_topic(manager_address: str, room_id: int) -> str:
    return f"{manager_prefix(manager_address)}/room/{room_id}/state"


def room_temperature_topic(manager_address: str, room_id: int) -> str:
    return f"{manager_prefix(manager_address)}/room/{room_id}/temperature_state"


def entity_page_state_topic(manager_address: str, page_id: int) -> str:
    return f"{manager_prefix(manager_address)}/entity_pages/{page_id}/state"


def light_state_topic(manager_address: str, light_id: int) -> str:
    return f"{manager_prefix(manager_address)}/entities/lights/{light_id}/state"


def thermostat_state_topic(manager_address: str, thermostat_id: int) -> str:
    return f"{manager_prefix(manager_address)}/entities/thermostats/{thermostat_id}/state"


def all_rooms_status_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/all_rooms_status"


def weather_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/status/weather"


def time_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/status/time"


def date_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/status/date"


def ampm_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/status/ampm"


def status_topic(manager_address: str) -> str:
    return f"{manager_prefix(manager_address)}/status/status"


def config_reload_topic() -> str:
    return "nspanel/config/reload"


# Defaults
DEFAULT_COLOR_TEMP_MIN = 2700  # kelvin — see web_settings defaults
DEFAULT_COLOR_TEMP_MAX = 6500
DEFAULT_NAME = "NSPanel Core"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_config"

# HA platforms this integration provides
PLATFORMS = ["sensor", "switch"]
