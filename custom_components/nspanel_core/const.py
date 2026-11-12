"""Constants for the NSPanel Core integration."""

from __future__ import annotations

import re

DOMAIN = "nspanel_core"

# MQTT topic templates (wire-compatible with the panels' firmware).
TOPIC_ROOT = "nspanel"

TOPIC_PANEL_STATUS = "nspanel/+/status"
TOPIC_PANEL_COMMAND = "nspanel/+/command"
TOPIC_PANEL_STATUS_REPORT = "nspanel/+/status_report"
TOPIC_MANAGER_COMMAND = "nspanel/mqttmanager/command"


def topic_safe(value: str | None) -> str:
    """Normalize an arbitrary string for use as a single MQTT topic segment.

    Lowercases, strips colons/dashes (MAC forms), and maps anything outside
    [a-z0-9_] to underscore. Never returns slashes or wildcards, so the
    result can never escape its topic level or act as a wildcard.
    """
    s = (value or "").strip().lower().replace(":", "").replace("-", "")
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def mac_for_connection(mac: str | None) -> str | None:
    """Format a 12-hex-digit MAC as aa:bb:cc:dd:ee:ff for device connections."""
    s = topic_safe(mac)
    if len(s) == 12 and all(c in "0123456789abcdef" for c in s):
        return ":".join(s[i:i + 2] for i in range(0, 12, 2))
    return None


# Per-panel (mac formatted without colons, lowercase — as the firmware uses)
def panel_topic(mac: str, suffix: str) -> str:
    return f"nspanel/{topic_safe(mac)}/{suffix}"


def manager_prefix(manager_address: str) -> str:
    return f"nspanel/mqttmanager_{manager_address}"


def panel_mqtt_base(name: str | None) -> str:
    """MQTT topic base for a panel: its wifi hostname, verbatim.

    The firmware builds every per-panel topic from ``wifi_hostname`` with no
    sanitization, so the manager must address panels the same way or nothing
    arrives (hostname ``My Panel`` subscribes to ``nspanel/My Panel/command``
    — not to a lowercased or MAC-based variant). Only characters that would
    break the topic structure (MQTT wildcards, level separators, controls)
    are replaced; case and spaces are kept verbatim to match the panel.
    """
    s = (name or "").strip()
    s = re.sub(r'[+#/\x00-\x1f\x7f]', '_', s)
    return s or "panel"


def panel_mqtt_topic(name: str | None, suffix: str) -> str:
    """Per-panel MQTT topic, e.g. nspanel/My Panel/r1_cmd."""
    return f"nspanel/{panel_mqtt_base(name)}/{suffix}"


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
