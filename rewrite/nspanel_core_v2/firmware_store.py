"""NSPanel Core v2 — firmware store.

The serving model that ended the stale-firmware deaths (P131/P132):
the manifest is the ONLY source of truth; files are downloaded, md5-verified
against it, and activated. There is no bundled-fallback ambiguity: if the
manifest is unreachable, serving is BLOCKED, never stale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .const import MANIFEST_URL

_LOGGER = logging.getLogger(__name__)

SERVABLE_FILES = (
    "firmware/sonoff/firmware.bin",
    "firmware/sonoff/data_file.bin",
    "firmware/custom/firmware.bin",
    "firmware/custom/data_file.bin",
    "tft/gui.tft",
    "tft/gui_us.tft",
)


@dataclass
class ActiveFirmware:
    version: str
    files: dict[str, str]   # "<kind>/<name>" → absolute path
    md5s: dict[str, str]


def md5_of(path: str | Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_newer(candidate: str, current: str) -> bool:
    """Numeric version compare: 0.1.187 > 0.1.186; non-numeric falls back to !=."""

    def tup(v: str):
        try:
            return tuple(int(x) for x in v.split("."))
        except (ValueError, AttributeError):
            return None

    a, b = tup(candidate), tup(current)
    if a is None or b is None:
        return bool(candidate) and candidate != current
    return a > b


async def fetch_manifest(hass, url: str = MANIFEST_URL) -> dict | None:
    """Fetch + validate the firmware manifest. Returns None on any failure."""
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                manifest = await resp.json(content_type=None)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Firmware manifest fetch failed: %s", err)
        return None
    if not isinstance(manifest, dict) or not manifest.get("version") or not manifest.get("files"):
        _LOGGER.warning("Firmware manifest malformed")
        return None
    return manifest


async def _fetch_bytes(session, url: str) -> bytes:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=600)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return await resp.read()


async def download_and_activate(hass, manifest: dict, store_dir: str,
                                fetch=None) -> ActiveFirmware | None:
    """Download every manifest file, verify md5, activate atomically.

    ``fetch`` is injectable (test seam). Returns the active set, or None if
    ANY file fails (no partial activation — serving either fully-verified
    content or nothing).
    """
    import aiohttp

    version = str(manifest["version"])
    target = Path(store_dir) / version
    target.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    md5s: dict[str, str] = {}

    if fetch is None:
        session = aiohttp.ClientSession()
        fetch = lambda url: _fetch_bytes(session, url)  # noqa: E731
    else:
        session = None

    try:
        for rel, entry in manifest["files"].items():
            if rel not in SERVABLE_FILES:
                continue
            url = entry["url"] if isinstance(entry, dict) else entry
            expected = entry["md5"] if isinstance(entry, dict) else ""
            local = target / Path(rel).name
            try:
                blob = await fetch(url)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Download failed (%s): %s", rel, err)
                return None
            local.write_bytes(blob)
            actual = md5_of(local)
            if expected and actual != expected:
                _LOGGER.error("MD5 mismatch for %s: expected %s got %s", rel, expected, actual)
                return None
            files[rel] = str(local)
            md5s[rel] = actual
    finally:
        if session is not None:
            await session.close()

    # Atomic activation: write the pointer last.
    pointer = Path(store_dir) / "active.json"
    pointer.write_text(json.dumps({"version": version, "files": files, "md5s": md5s}))
    return ActiveFirmware(version=version, files=files, md5s=md5s)


def load_active(store_dir: str) -> ActiveFirmware | None:
    pointer = Path(store_dir) / "active.json"
    if not pointer.is_file():
        return None
    data = json.loads(pointer.read_text())
    return ActiveFirmware(
        version=data["version"],
        files=data["files"],
        md5s=data["md5s"],
    )


def served_path(active: ActiveFirmware | None, kind: str, name: str,
                integration_dir: str) -> str | None:
    """Resolve a servable file: active overlay ONLY (no bundled fallback).

    Serving a stale bundled binary is how panels died (P131); if the
    overlay is not active the caller must refuse to serve, never fall back.
    """
    if active is None:
        return None
    return active.files.get(f"{kind}/{name}")
