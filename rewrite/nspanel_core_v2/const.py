"""NSPanel Core v2 — frozen wire constants (contract: tests/test_detach_contract.py).

These strings are the wire contract with the panel firmware. Changing any of
them is a coordinated firmware+manager release, never a casual edit.
"""

from __future__ import annotations

import re

DOMAIN = "nspanel_core"

TOPIC_ROOT = "nspanel"

TOPIC_PANEL_STATUS = "nspanel/+/status"
TOPIC_PANEL_COMMAND = "nspanel/+/command"
TOPIC_PANEL_STATUS_REPORT = "nspanel/+/status_report"
TOPIC_MANAGER_COMMAND = "nspanel/mqttmanager/command"

MANIFEST_URL = (
    "https://github.com/ALeXXBody/NSPanelCore/releases/download/"
    "firmware-latest/../raw/main/firmware/manifest.json"
).replace("/releases/download/firmware-latest/../raw/main/", "/raw/")


def topic_safe(value: str | None) -> str:
    """Normalize a string to a safe single MQTT topic segment.

    Guarantees: never contains '/', '+', '#', or control characters — the
    result cannot escape its topic level or act as a wildcard.
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


def panel_topic(mac: str, suffix: str) -> str:
    """MAC-based topic (mac lowercase, no colons — as the firmware uses)."""
    return f"nspanel/{topic_safe(mac)}/{suffix}"


def panel_mqtt_base(name: str | None) -> str:
    """Hostname base for a panel — VERBATIM (spaces kept, case kept).

    The firmware builds every per-panel topic from its wifi_hostname with no
    sanitization; the manager must address the exact same string or commands
    silently never arrive (P134 lesson).
    """
    s = (name or "").strip()
    s = re.sub(r'[+#/\x00-\x1f\x7f]', '_', s)
    return s or "panel"


def panel_mqtt_topic(name: str | None, suffix: str) -> str:
    return f"nspanel/{panel_mqtt_base(name)}/{suffix}"


def manager_prefix(manager_address: str) -> str:
    return f"nspanel/mqttmanager_{manager_address}"


# Panel commands (frozen — both firmware generations answer these)
CMD_REBOOT = "reboot"
CMD_FIRMWARE_UPDATE = "firmware_update"
CMD_TFT_UPDATE = "tft_update"
CMD_REGISTER_ACCEPT = "register_accept"
CMD_DISPLAY_RESTART = "display_restart"  # NSPanelCore firmware only

# OTA serving endpoints (frozen)
OTA_ENDPOINTS = (
    "/download_firmware", "/checksum_firmware",
    "/download_data_file", "/checksum_data_file",
    "/download_tft_eu", "/download_tft_us",
)
