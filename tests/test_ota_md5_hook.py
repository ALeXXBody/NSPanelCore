"""MD5-hooked OTA trigger semantics (the user's direction: updates are
md5-hooked, never version-hooked).

Covers the exact branch the live Kitchen panel hits: a register report
carrying NO/EMPTY md5s (the pre-0.1.4 firmware never recorded the fields).
The TFT branch treats an empty reported md5 as "never delivered" and still
triggers (P239); these tests pin the FIRMWARE branch to the same contract —
an empty reported firmware md5 must trigger the firmware OTA for an accepted
panel, exactly like a mismatched one. A matching md5 must not trigger.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import PanelConfig  # noqa: E402


def _mgr():
    mgr = MagicMock()
    mgr.hass = MagicMock()
    mgr.config.settings.auto_tft_updates = True
    return mgr


def _panel():
    return PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel", accepted=True)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _evaluate(monkeypatch, report: dict) -> list[str]:
    """Run the real evaluator against a mocked publish and return the
    command topics+payloads it issued."""
    mgr = _mgr()
    mgr.ota_md5 = MagicMock(
        side_effect=lambda kind, name: {
            ("firmware", "sonoff/firmware.bin"): "587386d3e042c6303087745a7341ebcf",
            ("firmware", "sonoff/data_file.bin"): "74d7ce6e39754a9bec2ae3a075620c49",
            ("tft", "gui.tft"): "b2b6a2e3e53ab56405d2202d51c98a29",
        }.get((kind, name), "")
    )
    mgr._ota_md5 = {"firmware/sonoff/firmware.bin": "x", "tft/gui.tft": "y"}
    mgr.dash = None
    published: list[tuple[str, str]] = []

    async def _publish(topic, payload, retain=False):
        published.append((topic, payload))

    mgr._publish = _publish
    monkeypatch.setattr(
        M.NSPanelCoreManager,
        "_panel_cmd_topic",
        lambda self, panel, suffix: f"nspanel/{panel.mac}/{suffix}",
        raising=False,
    )
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(mgr, _panel(), report))
    return [p for _, p in published]


@pytest.mark.parametrize("report,label", [
    ({}, "no md5 keys at all"),
    ({"md5_firmware": ""}, "empty firmware md5"),
    ({"md5_firmware": "deadbeef"}, "mismatched firmware md5"),
])
def test_empty_or_mismatched_md5_triggers_firmware_ota(monkeypatch, report, label):
    """P311: the firmware branch follows the TFT branch's P239 contract —
    an EMPTY reported md5 is 'unknown firmware' and must trigger the update
    (the update itself is md5-hooked; version strings never gate)."""
    payloads = _evaluate(monkeypatch, dict(report))
    assert any('"firmware_update"' in p for p in payloads), (
        f"firmware OTA not triggered for case: {label} -> {payloads}"
    )


def test_matching_md5_does_not_trigger(monkeypatch):
    payloads = _evaluate(
        monkeypatch, {"md5_firmware": "587386d3e042c6303087745a7341ebcf"}
    )
    assert not any('"firmware_update"' in p for p in payloads)
