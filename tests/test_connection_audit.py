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


def test_long_entity_label_truncates_never_fails_the_save():
    """P312 studio analysis: an entity's friendly_name can exceed the
    panel's 24-char label standard — the save must TRUNCATE the label,
    never fail (the user's 'changes are not saving' was one long name
    failing the whole design)."""
    from nspanel_core.dashboard_design import PanelDesign
    design = {"design": {"mac": "e465b849a100",
        "pages": [{"name": "dash_kitchen", "title": "Kitchen",
                   "background": "bg_plain", "background_image": ""}],
        "items": [{"id": "item1737412345678", "page": "dash_kitchen", "slot": 0,
                   "widget": "light", "entity_id": "light.kitchen_ceiling_main_light",
                   "label": "Kitchen Ceiling Main Light Group"}],
        "screensaver_page": "dash_kitchen"}}
    mgr = _mgr()
    mgr.dash = MagicMock()
    mgr.dash.async_save_design = AsyncMock(side_effect=lambda d: d.validate())
    with patch.object(D, "_manager", return_value=mgr):
        with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
            class _B:
                async def json(self):
                    return design
            resp = _run(D.DashboardSaveView().post(_B()))
    assert resp.status == 200, resp.text
    saved = mgr.dash.async_save_design.await_args.args[0]
    assert saved.items[0].label == "Kitchen Ceiling Main Lig"[:24] or \
           len(saved.items[0].label) <= 24


def test_studio_page_waits_for_auth_and_renders_gallery():
    """The studio's boot waits for the established session (or an immediate
    no-frontend verdict), and re-renders the gallery once auth lands — the
    <img> URLs embed the credential at render time."""
    html = (REPO / "custom_components/nspanel_core/ui/templates/dashboard.html").read_text()
    assert "function studioBoot()" in html
    assert "_nspanelBootstrapDone" in html
    assert "setTimeout(loadGallery, 800)" in html
    assert "nspanelFrontendHass" in html  # the no-frontend early boot


def test_settings_page_renders_zero_empty_alerts():
    """P312 (user: 'a lot of circled ! signs with no text'): the alert slots
    were the old add-on's server-warning slots — never fed in the new
    integration. The component renders NOTHING without a text, and the dead
    includes are out of the settings tabs."""
    import jinja2
    from nspanel_core import dashboard as D
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(D.TEMPLATES_DIR)),
                             undefined=jinja2.ChainableUndefined)
    out = env.get_template("settings.html").render(
        request=type("R", (), {"path": "/nspanel_core/settings"})(),
        active_tab="general", nspanels=[], ignored=[],
        manager_address="x", manager_port=8123,
        panel_broker_host="", panel_broker_port=1883, panel_broker_user="",
        panel_broker_pass_placeholder="", rooms=[], themes={}, theme="",
    )
    assert 'role="alert"' not in out, "empty alert boxes are back on the settings page"
    # the error TOAST template is separate (JS-driven, hidden until a real
    # runtime error) — only the static empty alert slots were the problem


def test_alert_component_still_works_with_a_real_message():
    import jinja2
    from nspanel_core import dashboard as D
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(D.TEMPLATES_DIR)),
                             undefined=jinja2.ChainableUndefined)
    # no text -> nothing (the fix)
    assert env.get_template("components/alert.html").render() == ""
    # a real message -> the alert renders with the text
    out = env.get_template("components/alert.html").render(
        level="warning", style="my-style", text="Broker unreachable")
    assert "Broker unreachable" in out
    assert "alert-warning" in out
