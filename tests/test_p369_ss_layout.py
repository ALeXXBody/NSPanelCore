"""P369 (user request): the screensaver preview's items are selectable and
movable with the mouse, and the layout is sent to the panel.

The contract:
  - the model's SS_LAYOUT_GROUPS mirror the kit's screensaver.page.toml
    (every group's comps exist there, at the box-relative deltas)
  - every kit default is LEGAL under its own clamp (the normalizer must
    never move an unset group)
  - generate_source(ss_layout=...) bakes the moved positions into the
    generated toml — component ORDER untouched, both the photo and the
    no-photo paths
  - the screensaver_save endpoint persists the layout (+ reset), and a
    partial body (layout only) leaves the other fields alone"""
import asyncio
import os
import sys
import tempfile
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402
pytest.importorskip("homeassistant")

from nspanel_core import hmi_generate as hg  # noqa: E402
from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.models import (  # noqa: E402
    IntegrationConfig, PanelConfig, SS_LAYOUT_GROUPS, normalize_ss_layout)

KIT = os.path.join(REPO, "custom_components", "nspanel_core", "hmi_kit")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _design():
    from nspanel_core import dashboard_design as dd
    return dd.PanelDesign(
        mac="e465b849a100",
        pages=[dd.DashPage(name="dash_kitchen", title="Kitchen")],
        items=[
            dd.DashItem(id="light1", page="dash_kitchen", widget="light",
                        entity_id="light.kitchen_ceiling", label="Ceiling", slot=0),
        ],
    )


# ---------------------------------------------------------------- the spec

def test_spec_matches_the_kit_toml():
    """Every group's components exist in the kit's screensaver page and sit
    at their stated deltas from the box origin."""
    kit = tomllib.load(open(os.path.join(
        KIT, "pages", "screensaver.page.toml"), "rb"))
    by_name = {c["name"]: c for c in kit["component"]}
    for group, spec in SS_LAYOUT_GROUPS.items():
        bx, by, bw, bh = spec["box"]
        for name, (dx, dy) in spec["comps"].items():
            comp = by_name.get(name)
            assert comp is not None, f"{group}.{name} missing from the kit"
            assert (comp["x"], comp["y"]) == (bx + dx, by + dy), \
                f"{group}.{name}: the kit is at {(comp['x'], comp['y'])}," \
                f" the spec says {(bx + dx, by + dy)}"


def test_every_kit_default_is_legal_under_its_own_clamp():
    for group, spec in SS_LAYOUT_GROUPS.items():
        bx, by, bw, bh = spec["box"]
        assert 0 <= bx <= 480 - bw and 0 <= by <= 320 - bh, group
        assert normalize_ss_layout({group: {"x": bx, "y": by}})[group] == \
            {"x": bx, "y": by}, group


def test_normalizer_filters_and_clamps():
    out = normalize_ss_layout({
        "clock": {"x": 999, "y": -50},      # clamped
        "bogus": {"x": 1, "y": 2},          # dropped
        "date": {"x": "30", "y": "200"},    # int-ish strings accepted
        "ampm": {"x": "junk", "y": 1},      # dropped (not ints)
        "outside": "garbage",               # dropped
    })
    assert out["clock"] == {"x": 80, "y": 0}
    assert out["date"] == {"x": 30, "y": 200}
    assert "bogus" not in out and "ampm" not in out and "outside" not in out


def test_model_roundtrip():
    p = PanelConfig(id=1, mac="a" * 12, name="t",
                    ss_layout={"clock": {"x": 10, "y": 20}})
    assert PanelConfig.from_dict(p.to_dict()).ss_layout == \
        {"clock": {"x": 10, "y": 20}}


# ------------------------------------------------------------- the generate

def test_generate_bakes_the_layout_no_photo():
    d = _design()
    layout = {"clock": {"x": 10, "y": 30}, "forecast0": {"x": 40, "y": 100}}
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, KIT, wd, ss_layout=layout)
        src = os.path.join(wd, "hmi", "pages", "screensaver.page.toml")
        comps = {c["name"]: c for c in
                 tomllib.load(open(src, "rb"))["component"]}
        # the clock moved; the box-relative deltas preserved
        assert (comps["curTime"]["x"], comps["curTime"]["y"]) == (10, 30)
        # forecast0 box at (40,100): the glyph at the box origin, the day
        # text at +48, the min/max at +24 down
        assert (comps["fSun0"]["x"], comps["fSun0"]["y"]) == (40, 100)
        assert (comps["fDay0"]["x"], comps["fDay0"]["y"]) == (88, 100)
        assert (comps["fMM0"]["x"], comps["fMM0"]["y"]) == (88, 124)
        # the untouched groups keep the kit positions
        assert (comps["curDay"]["x"], comps["curDay"]["y"]) == (40, 210)
        assert (comps["wOutTemp"]["x"], comps["wOutTemp"]["y"]) == (100, 240)
        # the ORDER is untouched
        names = [c["name"] for c in tomllib.load(open(src, "rb"))["component"]]
        assert names.index("curTime") < names.index("curDay") < names.index("curAMPM")


def test_generate_without_layout_keeps_the_kit():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, KIT, wd)
        src = os.path.join(wd, "hmi", "pages", "screensaver.page.toml")
        comps = {c["name"]: c for c in tomllib.load(open(src, "rb"))["component"]}
        assert (comps["curTime"]["x"], comps["curTime"]["y"]) == (40, 80)


# -------------------------------------------------------------- the endpoint

def _world(**panel_overrides):
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    base = dict(id=7, mac="aabbcc", name="Kitchen", accepted=True)
    base.update(panel_overrides)
    panel = PanelConfig(**base)
    cfg.panels.append(panel)
    manager = MagicMock()
    manager.config = cfg
    manager.hass = SimpleNamespace(
        auth=SimpleNamespace(async_validate_token=AsyncMock(return_value=False)))
    manager.async_save = AsyncMock()
    manager._publish_screensaver = AsyncMock()
    manager.notify_panels_changed = MagicMock()
    return cfg, panel, manager


class _Req:
    def __init__(self, manager, body=None, cookie=True):
        self.app = {"hass": SimpleNamespace(
            data={f"{DOMAIN}_entry_id": "e", DOMAIN: {"e": manager}})}
        self.query = {}
        self.match_info = {"panel_id": "7"}
        self.headers = ({"Cookie": "nspanel_session=sess",
                         "Content-Type": "application/json"} if cookie else {})
        self._body = body

    async def json(self):
        return self._body


def test_save_view_persists_the_layout():
    cfg, panel, manager = _world()
    resp = _run(D.DashboardScreensaverSaveView().post(
        _Req(manager, body={"ss_layout": {"clock": {"x": 5, "y": 6}}})))
    assert resp.status == 200, resp.text
    assert panel.ss_layout == {"clock": {"x": 5, "y": 6}}
    manager._publish_screensaver.assert_awaited_once()


def test_save_view_reset_and_validation():
    cfg, panel, manager = _world(
        ss_layout={"clock": {"x": 5, "y": 6}})
    # the reset
    resp = _run(D.DashboardScreensaverSaveView().post(
        _Req(manager, body={"ss_layout": {}})))
    assert resp.status == 200 and panel.ss_layout == {}
    # the garbage -> 422, the stored value untouched
    resp = _run(D.DashboardScreensaverSaveView().post(
        _Req(manager, body={"ss_layout": "not json"})))
    assert resp.status == 422
    # a partial body (no ss_layout key) leaves the layout alone
    panel.ss_layout = {"date": {"x": 1, "y": 2}}
    resp = _run(D.DashboardScreensaverSaveView().post(
        _Req(manager, body={"clock_font": "large"})))
    assert resp.status == 200
    assert panel.ss_layout == {"date": {"x": 1, "y": 2}}
