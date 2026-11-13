"""Decoupled firmware delivery for NSPanel Core.

Panels should get ESP/TFT firmware updates WITHOUT requiring a new release
of this integration. The flow:

1. A manifest (JSON) published alongside the firmware lists the current
   version, per-file download URLs and MD5 checksums.
2. The integration periodically fetches the manifest (or on user request),
   compares with the bundled/served version and — on approval — downloads
   the files into <hass_config>/.storage/nspanel_core/firmware/<version>/.
3. Serving + OTA triggering then resolve through the downloaded set
   (overlay) instead of the files bundled with the integration.

The bundled files remain the fallback when no overlay is active or the
manifest is unreachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

_LOGGER = logging.getLogger(__name__)

DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ALeXXBody/NSPanelCore/main/firmware/manifest.json"
)

# Keys are "<kind>/<name>" matching manager.ota_md5() / _hash_ota_files().
SERVABLE_FILES = (
    "firmware/sonoff/firmware.bin",
    "firmware/sonoff/data_file.bin",
    "firmware/custom/firmware.bin",
    "firmware/custom/data_file.bin",
    "tft/gui.tft",
    "tft/gui_us.tft",
)

_BUNDLED_VERSION_FILE = "version"


def bundled_version(integration_dir: str) -> str:
    """Version of the firmware bundled with the integration."""
    try:
        with open(os.path.join(integration_dir, "firmware", _BUNDLED_VERSION_FILE)) as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


def overlay_dir(hass_config_path: str, version: str) -> str:
    return os.path.join(hass_config_path, ".storage", "nspanel_core", "firmware", version)


def _version_tuple(v: str) -> tuple:
    parts = []
    for p in str(v).strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    # Zero-pad so different-length versions compare semantically
    # ("1.0" == "1.0.0", not newer).
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


async def fetch_manifest(hass, url: str) -> dict | None:
    """Download + minimally validate the firmware manifest. Runs in executor."""
    import urllib.request

    def _get():
        req = urllib.request.Request(url, headers={"User-Agent": "NSPanelCore/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = await hass.async_add_executor_job(_get)
    except Exception as err:  # noqa: BLE001 — network/users can break anything
        _LOGGER.warning("Firmware manifest fetch failed (%s): %s", url, err)
        return None
    if not isinstance(data, dict) or "version" not in data or "files" not in data:
        _LOGGER.warning("Firmware manifest at %s is malformed", url)
        return None
    return data


async def download_and_activate(hass, manager, manifest: dict) -> tuple[bool, str]:
    """Download every manifest file, verify MD5, activate as serving overlay.

    Returns (ok, message). Runs downloads in the executor; updates the
    manager overlay + OTA MD5 cache on success.
    """
    version = str(manifest.get("version", "")).strip()
    if not version:
        return False, "manifest has no version"
    files = manifest.get("files", {})
    missing = [k for k in SERVABLE_FILES if k not in files]
    if missing:
        return False, f"manifest missing files: {', '.join(missing)}"

    import urllib.request

    target = overlay_dir(hass.config.path(), version)

    def _download() -> dict[str, str]:
        os.makedirs(target, exist_ok=True)
        paths: dict[str, str] = {}
        for key in SERVABLE_FILES:
            entry = files[key]
            url, want = entry.get("url", ""), (entry.get("md5") or "").lower()
            if not url or not want:
                raise ValueError(f"{key}: manifest entry lacks url/md5")
            dest = os.path.join(target, key.replace("/", "__"))
            req = urllib.request.Request(url, headers={"User-Agent": "NSPanelCore/1.0"})
            h = hashlib.md5()
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
            if h.hexdigest() != want:
                raise ValueError(f"{key}: checksum mismatch")
            paths[key] = dest
        return paths

    try:
        paths = await hass.async_add_executor_job(_download)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Firmware %s download failed: %s", version, err)
        return False, str(err)

    manager.set_firmware_overlay(version, paths)
    await manager.refresh_ota_cache()
    return True, f"firmware {version} active"


def validate_manifest_against(paths: dict[str, str], manifest: dict | None = None) -> bool:
    """Verify overlay files exist AND still match the manifest md5s.

    Existence alone re-activated truncated/corrupt overlays on every boot;
    callers that have the manifest pass it for hash verification.
    """
    expected: dict[str, str] = {}
    if isinstance(manifest, dict):
        files = manifest.get("files", {})
        if isinstance(files, dict):
            for key, entry in files.items():
                if isinstance(entry, dict) and entry.get("md5"):
                    expected[key] = str(entry["md5"]).lower()
    import hashlib as _hashlib

    for key, path in paths.items():
        if not os.path.isfile(path):
            return False
        want = expected.get(key, "")
        if not want:
            continue
        try:
            h = _hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != want:
                _LOGGER.warning("Firmware overlay file %s failed checksum; ignoring overlay", key)
                return False
        except OSError:
            return False
    return True
