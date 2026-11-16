"""NSPanel Core v2 — manager core.

Pure logic, transport-injected: the HA glue binds MQTT publish/subscribe to
this core, and every behavior here is unit-testable without a broker.
Contracts enforced by tests/test_detach_contract.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from v2_const import (
    CMD_DISPLAY_RESTART,
    CMD_FIRMWARE_UPDATE,
    CMD_REBOOT,
    CMD_REGISTER_ACCEPT,
    CMD_TFT_UPDATE,
    TOPIC_MANAGER_COMMAND,
    topic_safe,
)
from v2_models import Panel, Settings

_LOGGER = logging.getLogger(__name__)

REREGISTRATION_SECONDS = 300   # P135: version must never go stale
DEFAULT_MANAGER_PORT = 8123


@dataclass
class ManagerConfig:
    """Everything the core needs beyond panels."""

    manager_address: str = ""
    manager_port: int = DEFAULT_MANAGER_PORT
    settings: Settings = field(default_factory=Settings)
    panels: list[Panel] = field(default_factory=list)


class Core:
    """Panel lifecycle + wire protocol, transport-injected."""

    def __init__(self, config: ManagerConfig, publish, log=None):
        """``publish(topic, payload, retain=False)`` is the only I/O primitive."""
        self.config = config
        self._publish = publish
        self._log = log or _LOGGER

    # -- lookups ------------------------------------------------------------

    def panel_by_mac(self, mac: str) -> Panel | None:
        want = topic_safe(mac)
        for p in self.config.panels:
            if topic_safe(p.mac) == want:
                return p
        return None

    def panel_by_topic_segment(self, segment: str) -> Panel | None:
        """Match a topic segment (hostname OR mac) to a panel."""
        seg = segment.lower().replace(":", "")
        for p in self.config.panels:
            base = (p.wifi_hostname or p.name).lower()
            if base == segment.lower() or topic_safe(p.mac) == seg:
                return p
        return None

    # -- registration (panel → manager command topic) ------------------------

    def handle_register_request(self, payload: bytes | str) -> bool:
        """Process a register_request. Returns True if a known panel updated.

        Adopts hostname (verbatim), version, and md5s; replies
        register_accept on the panel's OWN command topic (retained).
        """
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            self._log.warning("Ignoring unparsable register_request")
            return False
        mac = str(data.get("mac_origin") or "")
        panel = self.panel_by_mac(mac)
        if panel is None:
            self._log.info("Registration from unknown panel %s", mac)
            return False

        friendly = str(data.get("friendly_name") or "")
        if friendly and friendly.strip() != "NSPanelCore":
            # Never adopt a bare compiled default — it would re-point command
            # topics at a hostname the panel abandons on its next register.
            panel.wifi_hostname = friendly
        version = str(data.get("version") or "").strip()
        if version:
            panel.version = version          # P135: never stale
        if data.get("md5_firmware"):
            panel.firmware_md5 = str(data["md5_firmware"])
        if data.get("md5_data_file"):
            panel.littlefs_md5 = str(data["md5_data_file"])
        if data.get("md5_tft_file"):
            panel.tft_md5 = str(data["md5_tft_file"])

        reply = {
            "command": CMD_REGISTER_ACCEPT,
            "address": self.config.manager_address,
            "port": self.config.manager_port,
            "config_topic": "nspanel/" + topic_safe(panel.mac) + "/config",
        }
        self._publish(panel.command_topic(), json.dumps(reply), retain=True)
        return True

    # -- status --------------------------------------------------------------

    def handle_status_report(self, segment: str, payload: bytes | str) -> Panel | None:
        """Process a status_report (JSON). Adopts version (P135), rssi,
        temperature, heap, ip, warnings. Returns the panel."""
        panel = self.panel_by_topic_segment(segment)
        if panel is None:
            return None
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return panel
        version = str(data.get("version") or "").strip()
        if version and panel.version != version:
            panel.version = version          # P135: adopt live
        if data.get("rssi") is not None:
            try:
                panel.rssi = int(data["rssi"])
            except (ValueError, TypeError):
                pass
        try:
            panel.temperature = float(str(data.get("temperature", "")))
        except (ValueError, TypeError):
            pass
        if data.get("heap_used_pct") is not None:
            try:
                panel.heap_used_pct = int(data["heap_used_pct"])
            except (ValueError, TypeError):
                pass
        ip = str(data.get("ip") or "").strip()
        if ip:
            panel.ip = ip
        raw = data.get("warnings", "")
        if isinstance(raw, str) and raw.strip():
            panel.warnings = [{"level": "warning", "text": line}
                              for line in raw.splitlines() if line.strip()]
        elif isinstance(raw, list):
            panel.warnings = raw
        state = str(data.get("state") or "")
        panel.online = state not in ("updating_tft", "updating_fw", "updating_fs")
        from datetime import datetime, timezone
        panel.last_seen = datetime.now(timezone.utc)
        return panel

    # -- commands (manager → panel) -------------------------------------------

    def send_command(self, panel: Panel, command: str) -> str:
        """Publish a frozen command to the panel's VERBATIM hostname topic."""
        topic = panel.command_topic()
        self._publish(topic, json.dumps({"command": command}))
        return topic

    def send_reboot(self, panel: Panel) -> str:
        return self.send_command(panel, CMD_REBOOT)

    def send_firmware_update(self, panel: Panel) -> str:
        return self.send_command(panel, CMD_FIRMWARE_UPDATE)

    def send_tft_update(self, panel: Panel) -> str:
        return self.send_command(panel, CMD_TFT_UPDATE)

    def send_display_restart(self, panel: Panel) -> str:
        """Manual display recovery (NSPanelCore firmware only)."""
        return self.send_command(panel, CMD_DISPLAY_RESTART)

    # -- topic helpers used by the HA glue ------------------------------------

    @staticmethod
    def subscriptions() -> tuple[str, ...]:
        return (TOPIC_MANAGER_COMMAND, "nspanel/+/status",
                "nspanel/+/status_report")
