"""P352: a STALE panel md5 must never complete a running send.

Root cause of the "66% wall": the panel reports its CURRENTLY RECORDED
md5_tft_file in every 5-minute register. A value recorded by a PREVIOUS
send (resume-style completion / prior stock delivery) can EQUAL the
expected md5 — on_tft_md5 then treated it as "delivered", cleared the
serving slot mid-transfer, and every later block GET silently served the
STOCK gui.tft (1222192 bytes): the transfer died at the stock file's EOF
(exactly 66% of the real file) or the retry "delivered" the stock TFT to
the display. The firmware bumps tft_md5_seq at every record; the send
snapshots the counter at arm time and only a HIGHER count completes it.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core.dashboard_manager import DashboardService  # noqa: E402


def _svc(pre_seq=0):
    svc = object.__new__(DashboardService)
    svc._pushed_map = {}
    svc._serving = {
        "mac": "aabbccddeeff",
        "path": os.path.join(str(REPO), "custom_components", "nspanel_core", "tft", "gui.tft"),
        "md5": "expected_md5",
        "ts": time.time(),
        "pre_seq": pre_seq,
    }
    return svc


def _md5_call(svc, seq):
    return DashboardService.on_tft_md5(svc, "aabbccddeeff", "expected_md5", seq)


def test_stale_seq_does_not_complete_the_send(caplog):
    svc = _svc(pre_seq=5)
    with caplog.at_level(logging.WARNING):
        info = _md5_call(svc, 5)
    assert not info.get("delivered")
    assert svc._serving is not None, "the slot must stay armed for the live transfer"
    assert "PRE-SEND record" in caplog.text


def test_fresh_seq_completes_the_send():
    svc = _svc(pre_seq=5)
    info = _md5_call(svc, 6)
    assert info.get("delivered") is True
    assert svc._serving is None


def test_no_counter_evidence_falls_back_to_old_behavior():
    svc = _svc(pre_seq=0)
    info = _md5_call(svc, 0)
    assert info.get("delivered") is True
    assert svc._serving is None


def test_other_mac_never_touches_the_slot():
    svc = _svc(pre_seq=5)
    info = DashboardService.on_tft_md5(svc, "ffffffffffff", "expected_md5", 99)
    assert info == {}
    assert svc._serving is not None


def test_wrong_md5_never_completes_the_send():
    svc = _svc(pre_seq=5)
    info = DashboardService.on_tft_md5(svc, "aabbccddeeff", "other_md5", 99)
    assert not info.get("delivered")
    assert svc._serving is not None


def test_send_slot_snapshots_the_panel_seq():
    """The armed slot must carry the panel's PRE-send counter."""
    svc = object.__new__(DashboardService)
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    svc.manager = MagicMock()
    panel = MagicMock(accepted=True)
    panel.tft_md5_seq = 7
    svc.manager._panel_by_mac = lambda mac: panel
    svc.manager._publish = AsyncMock()
    svc.hass = MagicMock()
    svc.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    from nspanel_core.dashboard_design import DashItem, DashPage, PanelDesign
    design = PanelDesign(mac="aabbccddeeff")
    design.pages = [DashPage(name="dash_page", title="Bench")]
    design.items = [DashItem(id="it1", page="dash_page", slot=0,
                             entity_id="switch.x", widget="switch")]
    svc._designs = {"aabbccddeeff": design}
    svc._maps = {}
    svc._page_ids = {"aabbccddeeff": [4]}
    svc._delivered = {}
    svc._serving = None
    svc._auto_serving = None
    svc._store = MagicMock()
    svc._store.async_save = AsyncMock()
    svc._store.save = AsyncMock()
    art = pathlib.Path("/tmp/p352/generated.tft")
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(b"\x00" * 2048)
    svc.async_generate = AsyncMock(return_value=(str(art), "deadbeef", {}, [4]))

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        DashboardService.async_send_to_panel(svc, "aabbccddeeff"))
    loop.close()
    assert result.get("ok") is True, result
    assert svc._serving["pre_seq"] == 7


def test_tft_override_sliding_expiry_keeps_a_live_transfer_served():
    """A slot near its expiry must still serve — and extend its window."""
    svc = object.__new__(DashboardService)
    path = os.path.join(str(REPO), "custom_components", "nspanel_core", "tft", "gui.tft")
    old_ts = time.time() - 590  # 10 s left on the fixed clock
    svc._serving = {"mac": "aabbccddeeff", "path": path,
                    "md5": "expected_md5", "ts": old_ts}
    svc._auto_serving = None
    got = DashboardService.tft_override(svc, "aabbccddeeff")
    assert got == path
    assert svc._serving["ts"] > old_ts, "the honored fetch must extend the window"
    # the extended window serves the NEXT fetch too (a fixed clock would have
    # expired it mid-transfer)
    got2 = DashboardService.tft_override(svc, "aabbccddeeff")
    assert got2 == path
