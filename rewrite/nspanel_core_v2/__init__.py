"""NSPanel Core v2 — HA glue: binds MQTT to the transport-injected core and
serves the OTA endpoints. Thin by design; all logic lives in the core."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import firmware_store
from .const import (
    DOMAIN,
    OTA_ENDPOINTS,
    TOPIC_MANAGER_COMMAND,
    TOPIC_PANEL_STATUS,
    TOPIC_PANEL_STATUS_REPORT,
)
from .manager import Core, ManagerConfig

_LOGGER = logging.getLogger(__name__)

STORE_DIR = "nspanel_core/firmware"   # under hass config dir


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = ManagerConfig(
        manager_address=_manager_address(hass),
        manager_port=8123,
        panels=[],
    )
    core = Core(cfg, publish=_make_publisher(hass))
    active = await hass.async_add_executor_job(
        firmware_store.load_active, str(Path(hass.config.path()) / STORE_DIR)
    )

    async def on_register(msg):
        await hass.async_add_executor_job(core.handle_register_request, msg.payload)
        # refresh the served set opportunistically — never stale (P131/P132)
        await _refresh_firmware(hass, core)

    async def on_status_report(msg):
        segment = msg.topic.split("/")[1]
        await hass.async_add_executor_job(core.handle_status_report, segment, msg.payload)

    unsub_mqtt = [
        await mqtt.async_subscribe(hass, TOPIC_MANAGER_COMMAND, on_register),
        await mqtt.async_subscribe(hass, TOPIC_PANEL_STATUS_REPORT, on_status_report),
        await mqtt.async_subscribe(hass, TOPIC_PANEL_STATUS, _on_panel_status),
    ]
    _register_ota_views(hass, active)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "core": core,
        "unsub": unsub_mqtt,
        "active": active,
    }
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id)
    for unsub in data["unsub"]:
        unsub()
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _make_publisher(hass: HomeAssistant):
    async def publish(topic: str, payload: str, retain: bool = False) -> None:
        await mqtt.async_publish(hass, topic, payload, retain=retain)
    # The core calls publish synchronously; bridge through the loop.
    return lambda t, p, retain=False: hass.loop.create_task(publish(t, p, retain))


def _manager_address(hass: HomeAssistant) -> str:
    """LAN address HA answers OTA downloads on."""
    url = hass.config.internal_url or hass.config.external_url or ""
    return url.split("//")[-1].split(":")[0] if url else ""


async def _on_panel_status(msg):
    """Retained online/offline state — nothing to adopt in v2 core yet."""
    return


async def _refresh_firmware(hass: HomeAssistant, core: Core) -> None:
    """Fetch manifest + activate when newer. Serving is either verified-new
    or nothing (P131/P132)."""
    import dataclasses

    manifest = await firmware_store.fetch_manifest(hass)
    if not manifest:
        return
    data = hass.data[DOMAIN]
    entry_id = next(iter(data))
    active = data[entry_id].get("active")
    current = active.version if active else "0.0.0"
    if not firmware_store.is_newer(manifest["version"], current):
        return
    store = str(Path(hass.config.path()) / STORE_DIR)
    new = await firmware_store.download_and_activate(hass, manifest, store)
    if new is None:
        _LOGGER.error("Firmware activation failed — OTA serving stays on %s", current)
        return
    data[entry_id]["active"] = new
    for panel in core.config.panels:
        if panel.accepted:
            core.send_firmware_update(panel)
            _LOGGER.info("Pushed firmware %s to panel %s", new.version, panel.name)


def _register_ota_views(hass: HomeAssistant, active) -> None:
    from aiohttp import web

    class OtaFileView(web.View):
        """Serves ONLY active-overlay bytes. No overlay → 503, never stale."""

        requires_auth = False

        async def get(self, request):
            kind, name = self._kind
            data = _current(hass)
            path = firmware_store.served_path(data, kind, name, "")
            if not path or not Path(path).is_file():
                return web.Response(status=503, text="No active verified firmware set")
            return web.FileResponse(path)

    class DownloadFirmware(OtaFileView):
        url = "/download_firmware"
        _kind = ("firmware/sonoff", "firmware.bin")

    class DownloadDataFile(OtaFileView):
        url = "/download_data_file"
        _kind = ("firmware/sonoff", "data_file.bin")

    class ChecksumFirmware(OtaFileView):
        url = "/checksum_firmware"
        _kind = ("firmware/sonoff", "firmware.bin")

    class ChecksumDataFile(OtaFileView):
        url = "/checksum_data_file"
        _kind = ("firmware/sonoff", "data_file.bin")

    class DownloadTftEu(OtaFileView):
        url = "/download_tft_eu"
        _kind = ("tft", "gui.tft")

    class DownloadTftUs(OtaFileView):
        url = "/download_tft_us"
        _kind = ("tft", "gui_us.tft")

    class _ChecksumMixin:
        async def get(self, request):
            kind, name = self._kind
            data = _current(hass)
            path = firmware_store.served_path(data, kind, name, "")
            if not path or not Path(path).is_file():
                return web.Response(status=503, text="No active verified firmware set")
            return web.Response(text=firmware_store.md5_of(path))

    for cls in (ChecksumFirmware, ChecksumDataFile):
        cls.get = _ChecksumMixin.get

    for cls in (DownloadFirmware, DownloadDataFile, ChecksumFirmware,
                ChecksumDataFile, DownloadTftEu, DownloadTftUs):
        hass.http.register_view(cls())


def _current(hass: HomeAssistant):
    data = hass.data.get(DOMAIN) or {}
    if not data:
        return None
    entry_id = next(iter(data))
    return data[entry_id].get("active")
