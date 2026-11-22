"""P321f: the dash_map push is the panel crash trigger — the manager must
not send it.

Both panel crash loops began the moment a dashboard Send armed the
dash_map push (the panel's MQTT task dies processing the post-accept
commands whenever it is live); the same panel binary was stable for
400+ s in the era when the push was absent. Until the panel firmware's
dash_map handling is fixed, the manager must never publish dash_map —
while keeping the page ids stored (so a future fix can re-enable the
flow without a re-Send) and the values push intact.
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


def test_dash_map_is_never_published():
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    for call in svc.manager._publish.await_args_list:
        payload = call.args[1]
        assert "dash_map" not in payload, f"the crash trigger went out: {payload}"


def test_page_ids_stay_stored_for_the_future_fix():
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    # the ids must survive (no re-Send needed when the panel fix ships)
    assert svc._page_ids["e465b849a100"] == [4, 7]


def test_values_push_still_runs():
    svc = _svc([4, 7])
    _run(DashboardService.async_push_config(svc, "e465b849a100"))
    svc.async_push_values.assert_awaited_once_with("e465b849a100")


def test_no_design_means_no_traffic():
    svc = _svc([4, 7])
    svc._designs = {}
    _run(DashboardService.async_push_config(svc, "unknown000000"))
    svc.manager._publish.assert_not_awaited()
    svc.async_push_values.assert_not_awaited()
