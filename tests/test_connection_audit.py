"""P311 CONNECTION AUDIT — regression tests for the stale-connection sweep.

Covers the failures the audit found and fixed:
- /edit/{id} rendered NOTHING for a valid panel (the duplicate-removal had
  truncated the view body) — the authenticated render must return 200 with
  the panel's name.
- The weather form posted to a GET-only route (405) and its sensor field
  name didn't match the validator key (values silently dropped) — the form
  must post to save_settings and the field must validate.
- _redirect_back defaulted to /denied_nspanels — a path with NO view —
  the fallback must be a live route.
- /coming-soon (PlaceholderPageView) is deleted — the catch-all covers it.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.models import GlobalSettings, PanelConfig, RoomConfig  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr():
    mgr = MagicMock()
    s = GlobalSettings()
    mgr.config.settings = s
    mgr.config.rooms = [RoomConfig(id=1, name="Living")]
    mgr.config.panels = [
        PanelConfig(id=7, mac="e465b849a100", name="KitchenPanel", room_id=1, accepted=True)
    ]
    mgr.panels = lambda: list(mgr.config.panels)
    mgr.hass = MagicMock()
    mgr.hass.auth = MagicMock()
    return mgr


def _req(path, match=None, headers=None):
    r = MagicMock()
    r.path = path
    r.headers = dict(headers or {"Cookie": "", "Authorization": "Bearer good"})
    r.cookies = {}
    r.query = {}
    r.match_info = match or {}
    return r


def test_edit_panel_renders_for_authenticated_user():
    """The view must RENDER (200, panel name visible) for a valid panel —
    a truncated get() returning None breaks the page with a server error."""
    mgr = _mgr()
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            resp = _run(D.EditPanelView().get(
                _req("/nspanel_core/edit/7", match={"panel_id": "7"})))
    assert resp.status == 200
    assert "KitchenPanel" in resp.text
    assert "edit_nspanel" not in resp.text or "Error" not in resp.text[:200]


def test_edit_panel_401_without_credential():
    mgr = _mgr()
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=False)):
            resp = _run(D.EditPanelView().get(
                _req("/nspanel_core/edit/7", match={"panel_id": "7"})))
    assert resp.status == 401


def test_weather_form_fields_validate_through_save_settings():
    """The weather tab's form fields must all be accepted by the real
    validator — including outside_temp_sensor_entity (the form previously
    posted a name the validator ignored)."""
    clean, errors = M_validator = None, None
    from nspanel_core import manager as M
    clean, errors = M.NSPanelCoreManager.validate_settings({
        "date_format": "%d/%m",
        "clock_us_style": "False",
        "location_latitude": "45.9",
        "location_longitude": "25.7",
        "outside_temp_provider": "ha_sensor",
        "outside_temp_sensor_entity": "sensor.outdoor_temp",
        "weather_update_interval": "30",
        "use_fahrenheit": "False",
        "wind_speed_format": "kmh",
        "precipitation_format": "mm",
    })
    assert not errors, errors
    assert clean["outside_temp_sensor_entity"] == "sensor.outdoor_temp"


def test_weather_tab_posts_to_save_settings():
    """The form's action must be a route that ACCEPTS the POST
    (the old /settings/weather was GET-only -> 405)."""
    tpl = (REPO / "custom_components/nspanel_core/ui/templates/_tab_weather.html").read_text()
    assert 'action="/nspanel_core/save_settings"' in tpl
    assert 'action="/nspanel_core/settings/weather"' not in tpl
    # and the sensor input's NAME matches the validator key
    assert 'name="outside_temp_sensor_entity"' in tpl


def test_denied_nspanels_path_is_not_a_redirect_target():
    """_redirect_back must never target a path with no view."""
    src = (REPO / "custom_components/nspanel_core/dashboard.py").read_text()
    assert 'f"{URL_BASE}/denied_nspanels"' not in src
    assert 'f"{URL_BASE}/settings?tab=denied"' in src


def test_coming_soon_placeholder_removed():
    """/coming-soon had zero references — the catch-all covers unported
    links; the dead view (and its stale titles dict) is deleted."""
    src = (REPO / "custom_components/nspanel_core/dashboard.py").read_text()
    assert "PlaceholderPageView" not in src
    assert "ComingSoonView" in src  # the catch-all remains
