"""P323: the Send guard honours the serving-slot expiry.

The bench reproduced the wedge: a delivery that never completes arms the
serving slot; the Send guard checked the bare slot without the expiry, so
every later send was refused with "already in progress" FOREVER — the
serving_info() expiry fix (P312) only fixed the REPORTED state, not the
guard. The guard now applies the same 600 s expiry: an expired slot is
cleared and the send proceeds; a live slot is still refused.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
from nspanel_core.dashboard_design import DashItem, DashPage, PanelDesign  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _svc(slot_ts=None, delivered_md5="abc123"):
    svc = object.__new__(DashboardService)
    svc.manager = MagicMock()
    svc.manager._panel_by_mac = lambda mac: MagicMock(accepted=True)
    svc.manager._publish = AsyncMock()
    svc.manager.refresh_ota_cache = AsyncMock()
    svc.manager.note_custom_file = MagicMock()
    svc.hass = MagicMock()
    svc.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    design = PanelDesign(mac="aabbccddeeff")
    design.pages = [DashPage(name="dash_page", title="Bench")]
    design.items = [DashItem(id="it1", page="dash_page", slot=0,
                             entity_id="switch.x", widget="switch")]
    svc._designs = {"aabbccddeeff": design}
    svc._maps = {}
    svc._page_ids = {"aabbccddeeff": [4]}
    svc._delivered = {}
    svc._store = MagicMock()
    svc._store.async_save = AsyncMock()
    svc._store.save = AsyncMock()
    if slot_ts is not None:
        svc._serving = {"mac": "aabbccddeeff", "path": "/nonexistent.bin",
                        "md5": delivered_md5, "ts": slot_ts, "reserving": False}
    else:
        svc._serving = None
    svc._pushed_map = {}  # P361: the send populates it (the audit fix)
    # the "compiled" artifact must exist on disk (the code records its size)
    from pathlib import Path as _P
    _art = _P("/tmp/p323/generated.tft")
    _art.parent.mkdir(parents=True, exist_ok=True)
    _art.write_bytes(b"\x00" * 2048)
    svc.async_generate = AsyncMock(
        return_value=(str(_art), "deadbeef", {}, [4]))
    return svc


def test_expired_slot_is_cleared_and_send_proceeds():
    svc = _svc(slot_ts=time.time() - 700)
    result = _run(DashboardService.async_send_to_panel(svc, "aabbccddeeff"))
    assert result.get("ok") is True, result
    # the stale slot was replaced by the fresh one
    assert svc._serving["md5"] == "deadbeef"


def test_live_slot_still_refuses_concurrent_send():
    svc = _svc(slot_ts=time.time() - 30)  # 30 s old — well within the window
    result = _run(DashboardService.async_send_to_panel(svc, "aabbccddeeff"))
    assert result.get("error", "").startswith("a send is already in progress")
    assert svc._serving["md5"] == "abc123", "the live slot must stay armed"
