"""v2 skeleton conformance tests — the new code must satisfy the SAME
contracts as v1 (tests/test_detach_contract.py) plus its own guarantees.

Modules are loaded under unique names (v2_*) so they can never collide with
the v1 integration modules of the same basename in sys.modules."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
V2 = ROOT / "custom_components" / "nspanel_core"


def _pkg():
    """Load the v2 tree as a real package (relative imports resolve)."""
    if "v2pkg" in sys.modules:
        return sys.modules["v2pkg"]
    spec = importlib.util.spec_from_file_location(
        "v2pkg", V2 / "__init__.py", submodule_search_locations=[str(V2)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["v2pkg"] = pkg
    spec.loader.exec_module(pkg)
    return pkg


def _load(unique: str, filename: str):
    """Load a v2 submodule inside the package context (unique name kept)."""
    _pkg()
    return importlib.import_module("v2pkg." + filename.rsplit(".", 1)[0])


def _const():
    m = _load("v2_const", "const.py")
    # const.py is loaded as "v2_const" but models/firmware_store do
    # `from const import ...` — alias so their relative-style imports resolve.
    sys.modules.setdefault("const", m)
    return m


def _models():
    _const()
    return _load("v2_models", "models.py")


def _store():
    _const()
    return _load("v2_firmware_store", "firmware_store.py")


def test_manifest_present():
    import json
    m = json.loads((V2 / "manifest.json").read_text())
    assert m["domain"] == "nspanel_core"
    assert m["config_flow"] is True


def test_topic_constants_match_v1_wire_contract():
    const = _const()
    assert const.TOPIC_PANEL_COMMAND == "nspanel/+/command"
    assert const.TOPIC_PANEL_STATUS_REPORT == "nspanel/+/status_report"
    assert const.TOPIC_MANAGER_COMMAND == "nspanel/mqttmanager/command"


def test_topic_safe_never_escalates():
    const = _const()
    for bad in ("a/b", "a+b", "a#b", "../../etc", "a:b:c"):
        out = const.topic_safe(bad)
        assert "/" not in out and "+" not in out and "#" not in out


def test_hostname_topics_verbatim():
    """P134: spaces and case kept — commands reach panels whose hostname
    contains spaces (e.g. 'Kitchen Panel')."""
    const = _const()
    assert const.panel_mqtt_topic("My Panel", "command") == "nspanel/My Panel/command"
    assert const.panel_mqtt_topic("DemoPanel", "command") == "nspanel/DemoPanel/command"


def test_panel_identity_and_topics():
    models = _models()
    p = models.Panel(mac="AA:BB:CC:DD:EE:01", name="DemoPanel", wifi_hostname="DemoPanel")
    assert p.command_topic() == "nspanel/DemoPanel/command"
    assert p.status_report_topic() == "nspanel/aabbccddee01/status_report"
    d = p.to_dict()
    p2 = models.Panel.from_dict(d)
    assert p2.mac == p.mac and p2.wifi_hostname == p.wifi_hostname


def test_version_compare():
    fs = _store()
    assert fs.is_newer("0.1.187", "0.1.186")
    assert not fs.is_newer("0.1.186", "0.1.187")
    assert not fs.is_newer("0.1.186", "0.1.186")


def test_served_path_never_falls_back_to_bundled():
    """P131: no overlay → refuse to serve (never serve stale bundled bytes)."""
    fs = _store()
    assert fs.served_path(None, "firmware/sonoff", "firmware.bin", "/tmp") is None


def test_firmware_store_rejects_partial_activation():
    """A failed file download must return None (no partial activation)."""
    fs = _store()
    import asyncio

    manifest = {
        "version": "9.9.9",
        "files": {
            "firmware/sonoff/firmware.bin": {"url": "http://x/nope", "md5": "x"},
        },
    }

    async def failing_fetch(url):
        raise RuntimeError("boom")

    result = asyncio.run(
        fs.download_and_activate(None, manifest, "/tmp/v2store_test", fetch=failing_fetch)
    )
    assert result is None


def test_firmware_store_md5_mismatch_activates_nothing():
    """md5 mismatch on ANY file → no activation (fully-verified or nothing)."""
    import hashlib

    fs = _store()
    blob = b"good bytes"
    good_md5 = hashlib.md5(blob).hexdigest()
    manifest = {
        "version": "9.9.9",
        "files": {
            "firmware/sonoff/firmware.bin": {"url": "http://x/a", "md5": "0" * 32},
            "tft/gui.tft": {"url": "http://x/b", "md5": good_md5},
        },
    }
    import asyncio

    async def fetch(url):
        return blob

    result = asyncio.run(
        fs.download_and_activate(None, manifest, "/tmp/v2store_test2", fetch=fetch)
    )
    assert result is None

    manifest["files"]["firmware/sonoff/firmware.bin"]["md5"] = good_md5
    result = asyncio.run(
        fs.download_and_activate(None, manifest, "/tmp/v2store_test2", fetch=fetch)
    )
    assert result is not None and result.version == "9.9.9"
    assert (pathlib.Path("/tmp/v2store_test2/active.json")).is_file()
