"""P355: the dash_map push is RESTORED — the P321f suppression is lifted.

The P321f isolation pinned the push as the "crash trigger", but P334 later
root-caused the crash (the display write's portMUX critical section across
a blocking uart_write_bytes — removed) and P352 falsified the "display goes
deaf" era entirely. The panel's dash_map handler is a bounded parse into a
fixed array. With the map suppressed, the swipe navigation and dash-page
detection were dead. The manager must publish the map (non-retained, P326)
followed by the values push; no design means no traffic.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
from nspanel_core.dashboard_design import DashItem, DashPage, PanelDesign  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _svc(page_ids):
    svc = object.__new__(DashboardService)
    svc.manager = MagicMock()
    svc.manager._publish = AsyncMock()
    design = PanelDesign(mac="e465b849a100")
    design.pages = [DashPage(name="dash_page", title="Page")]
    design.items = [DashItem(id=1, page="dash_page", slot=0,
                             entity_id="switch.coffee", widget="switch")]
    svc._designs = {"e465b849a100": design}
    svc._page_ids = {"e465b849a100": list(page_ids)}
    svc._maps = {}
    svc.async_push_values = AsyncMock()
    return svc


def test_dash_map_is_published_with_the_stored_page_ids():
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    maps = [json.loads(c.args[1]) for c in svc.manager._publish.await_args_list
            if "dash_map" in c.args[1]]
    assert maps, "the dash_map push must go out again (P355)"
    assert maps[0]["pages"] == [4, 7]
    assert maps[0]["command"] == "dash_map"


def test_dash_map_is_published_non_retained():
    """P326: a retained command replays at every panel boot and killed it."""
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    for call in svc.manager._publish.await_args_list:
        if "dash_map" in call.args[1]:
            retain = call.kwargs.get("retain", call.args[2] if len(call.args) > 2 else False)
            assert not retain, "the dash_map must be non-retained"

def test_values_push_still_runs_after_the_map():
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    svc.async_push_values.assert_awaited_once_with("e465b849a100")


def test_no_design_means_no_traffic():
    svc = _svc([4, 7])
    svc._designs = {}
    _run(DashboardService.async_push_config(svc, "unknown000000"))
    svc.manager._publish.assert_not_awaited()
    svc.async_push_values.assert_not_awaited()
