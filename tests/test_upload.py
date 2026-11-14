"""Regression tests for the exact-file upload path (TFT/firmware/data).

Run with an HA dev venv:
    /tmp/opencode/ha-venv-2611/bin/python -m pytest tests/test_upload.py -v

Background: uploaded files used to be silently shadowed by the firmware
overlay (the panel would download the OLD release file while the cache
claimed the new hash — or loop reflashing). These tests execute the real
manager + view code and prove, byte for byte, that what the user uploads
is what the panel is served.

NOTE: the full view POST writes to the repo tft/ dir, so it is exercised
in dev only (see audit notes). The committed tests cover everything
around it: _save_upload streaming, overlay pinning, cache, proof text.
"""

import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

pytest.importorskip("homeassistant")

from aiohttp import web  # noqa: E402
from multidict import MultiDict  # noqa: E402
from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import IntegrationConfig  # noqa: E402

BLANK = Path("/tmp/opencode/nspanel_blank.tft")


def _mgr():
    m = M.NSPanelCoreManager.__new__(M.NSPanelCoreManager)
    m.config = IntegrationConfig()
    m._ota_md5 = {}
    m._ota_overlay = {}
    m._ota_active_version = ""
    return m


class _Hass:
    async def async_add_executor_job(self, fn, *a):
        return fn(*a)


def test_save_upload_streams_bytes_identically(tmp_path):
    """_save_upload must write the uploaded bytes verbatim (no truncation)."""
    payload = os.urandom(300000)

    from nspanel_core.const import DOMAIN as _DOMAIN

    class _Hass:
        async def async_add_executor_job(self, fn, *a):
            return fn(*a)

    class _Mgr:
        hass = _Hass()

    _Hass.data = {_DOMAIN: {"entry": _Mgr()}}

    class Req:
        headers = {}
        match_info = {}
        app = {"hass": _Hass()}

        def __init__(self, form):
            self._form = form

        async def post(self):
            return self._form

    ff = web.FileField("tft_file", "up.tft", io.BytesIO(payload), "application/octet-stream", {})
    view = D.SaveTftFileView()
    dest = tmp_path / "out.tft"

    async def go():
        return await view._save_upload(Req(MultiDict([("tft_file", ff)])), "tft_file", str(dest))

    import asyncio

    assert asyncio.run(go()) is None
    assert dest.read_bytes() == payload


def test_save_upload_rejects_missing_file(tmp_path):
    class Req:
        headers = {}
        match_info = {}

        async def post(self):
            return MultiDict([])

    view = D.SaveTftFileView()

    async def go():
        return await view._save_upload(Req(), "tft_file", str(tmp_path / "x.tft"))

    import asyncio

    resp = asyncio.run(go())
    assert resp.status == 400


def test_pin_overwrites_overlay_and_cache(tmp_path):
    """An upload must replace any overlay copy (anti-shadow) and re-hash."""
    mgr = _mgr()
    mgr.hass = _Hass()
    overlay_file = tmp_path / "gui.tft"
    overlay_file.write_bytes(b"STALE-RELEASE-BYTES")
    mgr._ota_overlay = {"tft/gui.tft": str(overlay_file)}
    proof = mgr.note_custom_tft("gui.tft")
    bundled = Path(M.__file__).parent / "tft" / "gui.tft"
    assert proof["md5"] == hashlib.md5(bundled.read_bytes()).hexdigest()
    assert overlay_file.read_bytes() == bundled.read_bytes()
    assert mgr._ota_md5["tft/gui.tft"] == proof["md5"]


def test_served_proof_prefers_manual_upload(tmp_path):
    mgr = _mgr()
    mgr.hass = _Hass()
    overlay_file = tmp_path / "gui.tft"
    overlay_file.write_bytes(b"STALE-RELEASE-BYTES")
    mgr._ota_overlay = {"tft/gui.tft": str(overlay_file)}
    mgr.note_custom_tft("gui.tft")
    info = mgr.served_tft_info()["eu"]
    assert info["md5"] == hashlib.md5(
        (Path(M.__file__).parent / "tft" / "gui.tft").read_bytes()
    ).hexdigest()
    assert info["source"].startswith("manual upload"), info["source"]
    mgr._ota_overlay = {}
    info2 = mgr.served_tft_info()["eu"]
    assert info2["source"].startswith("manual upload"), info2


def test_blank_tft_fixture_valid():
    """The unbrick test file must be a valid landscape Nextion TFT."""
    import struct

    assert BLANK.is_file(), "download hmi/nspanel_blank.tft from Blackymas/NSPanel_HA_Blueprint"
    d = BLANK.read_bytes()
    assert d[1:3] == b"\x01\x44" and d[3:4] == b"N"
    assert d[0xC:0x10] == bytes.fromhex("e0014001") and d[0x14] == 0x03
    assert struct.unpack("<I", d[0x3C:0x40])[0] == len(d)
    assert len(d) < 1_000_000  # fast test vehicle, not a 16MB flash


def test_refresh_ota_cache_yields_dict_not_coroutine():
    """Regression: startup scheduled the async refresh in the executor, so
    _ota_md5 became a coroutine object and every later upload 500'd with
    "'coroutine' object does not support item assignment"."""
    import asyncio

    import nspanel_core.manager as M

    class _Hass:
        async def async_add_executor_job(self, fn, *a):
            return fn(*a)

    mgr = M.NSPanelCoreManager.__new__(M.NSPanelCoreManager)
    mgr.config = IntegrationConfig()
    mgr.hass = _Hass()
    mgr._ota_overlay = {}
    mgr._ota_active_version = ""

    async def go():
        await mgr.refresh_ota_cache()

    asyncio.run(go())
    assert isinstance(mgr._ota_md5, dict), f"_ota_md5 is {type(mgr._ota_md5)}"
    assert mgr._ota_md5.get("tft/gui.tft"), "tft hash missing"
    mgr._ota_md5["tft/gui.tft"] = "x"  # must not raise
