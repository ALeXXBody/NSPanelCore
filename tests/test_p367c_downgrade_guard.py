"""P367c: a STALE manifest must never DOWNGRADE the served firmware.

The P366 release chain crashed halfway and left firmware/manifest.json at
0.2.6 for a day: the manager's manifest auto-check kept seeing "0.2.6" and
(re)activating it, and the bundled 0.2.6 binaries kept re-staling the store
after every integration update - the panel flashed the OLD firmware over
the NEW one twice ("OTA succeeded", the version went BACKWARDS)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import firmware_store as fs  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_older_manifest_is_refused():
    mgr = MagicMock()
    mgr._ota_active_version = "0.2.8"
    manifest = {"version": "0.2.6", "files": {
        k: {"url": "https://x/" + k, "md5": "0" * 32} for k in fs.SERVABLE_FILES}}
    ok, msg = _run(fs.download_and_activate(MagicMock(), mgr, manifest))
    assert ok is True  # not an error - a deliberate skip
    assert "downgrade refused" in msg, msg
    mgr.set_firmware_overlay.assert_not_called()


def test_equal_manifest_still_activates_the_recut():
    """P252: a reused release number with changed bytes must activate."""
    mgr = MagicMock()
    mgr._ota_active_version = "0.2.8"
    manifest = {"version": "0.2.8", "files": {
        k: {"url": "https://x/" + k, "md5": "0" * 32} for k in fs.SERVABLE_FILES}}

    # the download will fail against the fake URL - that is fine: the point
    # is that the guard did NOT refuse before the download started
    ok, msg = _run(fs.download_and_activate(MagicMock(), mgr, manifest))
    assert "downgrade refused" not in msg, msg


def test_newer_manifest_still_activates():
    mgr = MagicMock()
    mgr._ota_active_version = "0.2.6"
    manifest = {"version": "0.2.8", "files": {
        k: {"url": "https://x/" + k, "md5": "0" * 32} for k in fs.SERVABLE_FILES}}
    ok, msg = _run(fs.download_and_activate(MagicMock(), mgr, manifest))
    assert "downgrade refused" not in msg, msg


def test_bundled_version_fallback_when_no_overlay():
    """No overlay set: the guard falls back to the bundled version marker."""
    mgr = MagicMock()
    mgr._ota_active_version = ""
    manifest = {"version": "0.1.0", "files": {
        k: {"url": "https://x/" + k, "md5": "0" * 32} for k in fs.SERVABLE_FILES}}
    ok, msg = _run(fs.download_and_activate(MagicMock(), mgr, manifest))
    # the bundled marker is 0.2.8 in the repo - 0.1.0 is strictly older
    assert "downgrade refused" in msg or "no version" in msg, msg
