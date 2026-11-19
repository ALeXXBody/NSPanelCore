"""P306 Step 3 — the Build-the-screensaver endpoints serve the REAL template.

These exercise the registered aiohttp views, the real Jinja env and the real
PanelConfig values. No reimplemented parser, no hand-written markup fixture.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

pytest.importorskip("homeassistant")

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.const import DOMAIN  # noqa: E402
from nspanel_core.manager import build_panel_screensaver_config  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402

PARTIAL = (REPO / "custom_components" / "nspanel_core" / "ui" /
           "templates" / "_screensaver_fields.html")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _State:
    def __init__(self, entity_id, **attrs):
        self.entity_id = entity_id
        self.attributes = attrs


def _world(**overrides):
    cfg = IntegrationConfig()
    cfg.settings.nspanel_sessions = {"sess": 9e18}
    cfg.rooms.append(RoomConfig(id=1, name="Living"))
    base = dict(id=7, mac="aabbcc", name="Kitchen", room_id=1, accepted=True,
                clock_font="large", clock_weight="regular", clock_color="#c8cbce",
                clock_align="center", date_font="small", date_weight="regular",
                date_color="#8b93a1", date_align="center")
    base.update(overrides)
    panel = PanelConfig(**base)
    cfg.panels.append(panel)

    manager = MagicMock()
    manager.config = cfg
    manager.panels.return_value = list(cfg.panels)
    manager.hass = SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: [
            _State("sensor.outside", friendly_name="Outside Temperature"),
            _State("sensor.inside", friendly_name="Inside Temperature"),
            _State("light.kitchen", friendly_name="Kitchen Light"),
        ]),
        auth=SimpleNamespace(async_validate_token=AsyncMock(return_value=False)),
    )
    manager.async_save = AsyncMock()
    manager._publish_screensaver = AsyncMock()
    manager.notify_panels_changed = MagicMock()
    return cfg, panel, manager


class _Req:
    """The same app/manager/session shape the other studio views are given."""

    def __init__(self, manager, query=None, match_info=None, body=None, cookie=True):
        self.app = {"hass": SimpleNamespace(data={f"{DOMAIN}_entry_id": "entry",
                                                  DOMAIN: {"entry": manager}})}
        self.query = query or {}
        self.match_info = match_info or {}
        self.headers = {"Cookie": "nspanel_session=sess"} if cookie else {}
        if self.headers.get("Cookie"):
            self.headers["Content-Type"] = "application/json"
        self._body = body

    async def json(self):
        return self._body


# ---------------------------------------------------------------- the GET view

def test_get_view_renders_real_stored_values_and_real_entity_options():
    cfg, panel, manager = _world(
        clock_font="xlarge", clock_weight="bold", clock_color="#39c8e8",
        clock_align="right", date_font="medium", show_ss_wind=True,
        show_ss_sunrise_sunset=True, ss_outside_temp_entity="sensor.outside")
    resp = _run(D.DashboardScreensaverSettingsView().get(
        _Req(manager, query={"panel_id": "7"})))
    assert resp.status == 200
    html = resp.text

    # The values are the panel's stored ones, not the first option in markup.
    assert 'value="xlarge" selected' in html
    assert 'value="bold" selected' in html
    assert 'value="#39c8e8"' in html
    assert 'value="right" selected' in html
    assert 'value="medium" selected' in html
    for flag in ("show_ss_wind", "show_ss_sunrise_sunset"):
        assert re.search(r'name="%s"[^>]*\bchecked\b' % flag, html), flag
    # P308: the entity choice is a type-to-filter box — the stored value lives
    # in the hidden input, the options in the hidden source select.
    assert 'name="ss_outside_temp_entity" id="ss_outside_temp_entity" value="sensor.outside"' in html
    assert 'name="ss_room_temp_entity" id="ss_room_temp_entity" value=""' in html
    assert re.search(r'<option value="sensor\.outside">Outside Temperature</option>', html)
    assert re.search(r'<option value="sensor\.inside">Inside Temperature</option>', html)
    assert 'value="light.kitchen"' not in html      # only temp-capable domains

    # All fifteen persisted fields are editable, and the form targets the
    # matching save endpoint for this panel.
    for field in ("clock_font", "clock_weight", "clock_color", "clock_align",
                  "date_font", "date_weight", "date_color", "date_align",
                  "show_ss_outside_temp", "show_ss_room_temp", "show_ss_forecast",
                  "show_ss_wind", "show_ss_rain", "show_ss_sunrise_sunset",
                  "ss_outside_temp_entity", "ss_room_temp_entity"):
        assert 'name="%s"' % field in html, field
    assert 'action="/nspanel_core/api/screensaver_save/7"' in html
    assert "Undefined" not in html


def test_get_view_degrades_gracefully_without_a_panel():
    _, _, manager = _world()
    for query in ({}, {"panel_id": "not-a-number"}, {"panel_id": "99"}):
        resp = _run(D.DashboardScreensaverSettingsView().get(
            _Req(manager, query=query)))
        assert resp.status == 200
        assert "panel" in resp.text.lower()


def test_partial_compiles_in_the_real_jinja_env():
    env = D._get_env()
    tpl = env.get_template("_screensaver_fields.html")
    assert tpl is not None
    assert PARTIAL.is_file()


# --------------------------------------------------------------- the POST view

_FULL_BODY = {
    "clock_font": "medium", "clock_weight": "bold", "clock_color": "#39C8E8",
    "clock_align": "left", "date_font": "large", "date_weight": "bold",
    "date_color": "#8B93A1", "date_align": "right",
    "show_ss_outside_temp": True, "show_ss_room_temp": False,
    "show_ss_forecast": True, "show_ss_wind": True, "show_ss_rain": False,
    "show_ss_sunrise_sunset": True,
    "ss_outside_temp_entity": "sensor.outside", "ss_room_temp_entity": "",
}


def test_post_view_validates_persists_and_publishes_the_real_payload():
    cfg, panel, manager = _world()
    resp = _run(D.DashboardScreensaverSaveView().post(_Req(
        manager, match_info={"panel_id": "7"}, body=_FULL_BODY)))
    assert resp.status == 200
    assert json.loads(resp.text) == {"ok": True, "panel_id": 7}

    assert panel.clock_font == "medium" and panel.clock_weight == "bold"
    assert panel.clock_color == "#39c8e8" and panel.clock_align == "left"
    assert panel.date_font == "large" and panel.date_weight == "bold"
    assert panel.date_color == "#8b93a1" and panel.date_align == "right"
    assert panel.show_ss_outside_temp is True and panel.show_ss_rain is False
    assert panel.ss_outside_temp_entity == "sensor.outside"

    manager.async_save.assert_awaited_once_with()
    manager._publish_screensaver.assert_awaited_once_with(panel)
    manager.notify_panels_changed.assert_called_once_with()

    # The builder consumes the very same stored fields the firmware will get.
    payload = build_panel_screensaver_config(panel, cfg.settings)
    assert payload["clock"] == {"font": "medium", "weight": "bold",
                                "color": "#39c8e8", "align": "left"}
    assert payload["weather"]["outside_temp"] is True
    assert payload["weather"]["wind"] is True
    assert payload["weather"]["rain"] is False


def test_post_view_rejects_every_bad_field_without_touching_the_panel():
    _, panel, manager = _world()
    before = dict(panel.__dict__)
    body = dict(_FULL_BODY)
    body.update({"clock_font": "huge", "clock_color": "red;drop",
                 "show_ss_wind": "yes", "ss_room_temp_entity": "../../etc/passwd"})
    resp = _run(D.DashboardScreensaverSaveView().post(_Req(
        manager, match_info={"panel_id": "7"}, body=body)))
    assert resp.status == 422
    fields = json.loads(resp.text)["fields"]
    assert set(fields) == {"clock_font", "clock_color", "show_ss_wind",
                           "ss_room_temp_entity"}
    assert panel.__dict__ == before
    manager.async_save.assert_not_awaited()
    manager._publish_screensaver.assert_not_awaited()
    manager.notify_panels_changed.assert_not_called()


def test_post_view_accepts_a_partial_payload_without_wiping_other_fields():
    _, panel, manager = _world(clock_font="xlarge", show_ss_rain=True)
    resp = _run(D.DashboardScreensaverSaveView().post(_Req(
        manager, match_info={"panel_id": "7"},
        body={"clock_align": "right", "show_ss_wind": True})))
    assert resp.status == 200
    assert panel.clock_align == "right" and panel.show_ss_wind is True
    assert panel.clock_font == "xlarge" and panel.show_ss_rain is True
    manager._publish_screensaver.assert_awaited_once_with(panel)


def test_auth_gate_blocks_the_save_before_any_write():
    _, _, manager = _world()
    resp = _run(D.DashboardScreensaverSaveView().post(_Req(
        manager, match_info={"panel_id": "7"}, body=_FULL_BODY, cookie=False)))
    assert resp.status == 401
    manager.async_save.assert_not_awaited()
    manager._publish_screensaver.assert_not_awaited()


def test_views_are_registered_with_the_studio_urls():
    assert D.DashboardScreensaverSettingsView.url == (
        "/nspanel_core/dashboard/screensaver_settings")
    assert D.DashboardScreensaverSaveView.url == (
        "/nspanel_core/api/screensaver_save/{panel_id}")
    src = (REPO / "custom_components" / "nspanel_core" / "dashboard.py").read_text()
    assert "DashboardScreensaverSettingsView," in src
    assert "DashboardScreensaverSaveView," in src
