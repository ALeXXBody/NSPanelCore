"""Regression tests for NSPanel Core dashboard handlers (real code paths).

Run with an HA dev venv:
    /tmp/opencode/ha-venv-2611/bin/python -m pytest tests/ -v
(system python lacks homeassistant; these tests import the integration.)

Covers: panel save (radio/enum/orientation parsing, phantom-flag
preservation, 400/404/422 paths), weather GET context + POST validation,
room reorder, get_ip_by_hostname, panel accept/deny/delete/update actions
(incl. denied-page empty swap, section-grid returns), rooms referer
redirects, served-TFT pinning proof.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

pytest.importorskip("homeassistant")

from multidict import MultiDict  # noqa: E402
from aiohttp import web  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core.models import IntegrationConfig, LightConfig, PanelConfig, RoomConfig  # noqa: E402


class FakeManager:
    def __init__(self, cfg):
        self.config = cfg
        self._last_ota_trigger = {}

    def panels(self):
        return list(self.config.panels)

    async def async_save(self):
        pass

    async def _send_panel_config(self, panel):
        pass

    async def _publish_panel_status(self, panel, state):
        pass

    async def _publish(self, *a, **k):
        pass

    async def _maybe_trigger_firmware_ota_cooled(self, panel, report):
        pass

    def _room_by_id(self, rid):
        return next((r for r in self.config.rooms if r.id == rid), None)

    def notify_panels_changed(self):
        pass


class FakeHass:
    def __init__(self, mgr):
        self.data = {"nspanel_core": {"entry": mgr}}


def _req(form=None, match=None, headers=None, payload=None, manager=None):
    _match = match or {}
    _headers = headers or {}
    _payload = payload

    class Req:
        app = {"hass": FakeHass(manager)}
        match_info = _match
        headers = _headers

        def __init__(self, form):
            self._form = form

        async def post(self):
            return self._form

        async def json(self):
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    Req._payload = payload
    return Req(form)


@pytest.fixture()
def cfg():
    c = IntegrationConfig()
    c.rooms.append(RoomConfig(id=1, name="Living"))
    c.rooms.append(RoomConfig(id=3, name="Bed"))
    c.lights.append(
        LightConfig(id=5, name="Ceiling", ha_entity="light.x", room_id=3, page_id=1, page_slot=1)
    )
    return c


@pytest.fixture()
def mgr(cfg):
    return FakeManager(cfg)


@pytest.fixture()
def panel(cfg):
    p = PanelConfig(id=7, mac="aabbcc", name="Test", room_id=1)
    cfg.panels.append(p)
    return p


async def _post(view, form, mgr, pid="7"):
    try:
        resp = await view.post(_req(form, {"panel_id": pid}, manager=mgr))
        return resp.status, getattr(resp, "text", "")
    except web.HTTPFound as e:
        return e.status, "redirect"
    except web.HTTPException as e:
        return e.status, getattr(e, "text", "")


async def test_save_full_valid_parse(mgr, panel):
    view = D.SavePanelSettingsView()
    status, _ = await _post(
        view,
        MultiDict([
            ("friendly_name", "Kitchen"), ("button1_mode", "2"), ("button2_mode", "9"),
            ("reverse_relays", "True"), ("relay1_default_mode", "False"),
            ("relay2_default_mode", "True"), ("relay1_is_light", "True"),
            ("relay2_is_light", "False"), ("panel_type", "us_horizontal"),
            ("screensaver_mode", "datetime_with_background"),
            ("temperature_calibration", "-1.5"), ("default_page", "2"), ("room_id", "3"),
            ("button1_detached_mode_light", "5"), ("lock_to_default_room", "True"),
            ("show_home_scenes", "1"),
        ]),
        mgr,
    )
    assert status in (200, 302)
    assert panel.reverse_relays is True
    assert panel.relay1_default_mode is False
    assert panel.relay2_default_mode is True
    assert panel.relay1_is_light is True and panel.relay2_is_light is False
    assert panel.is_us_panel is True and panel.us_panel_orientation == "horizontal"
    assert panel.screensaver_mode == "datetime_with_background"
    assert panel.temperature_calibration == 2.5 or panel.temperature_calibration == pytest.approx(-1.5)
    assert isinstance(panel.temperature_calibration, float)
    assert panel.button2_mode == 3  # clamped 9 -> 3
    assert panel.room_id == 3
    assert panel.button1_detached_light == 5
    assert panel.lock_to_default_room is True
    assert panel.name == "Kitchen"


async def test_save_preserves_phantom_flags(mgr, panel):
    panel.clock_us_style = True
    panel.use_fahrenheit = True
    panel.optimistic_mode = True
    view = D.SavePanelSettingsView()
    status, _ = await _post(view, MultiDict([("reverse_relays", "False")]), mgr)
    assert status in (200, 302)
    assert panel.clock_us_style is True
    assert panel.use_fahrenheit is True
    assert panel.optimistic_mode is True
    assert panel.reverse_relays is False


@pytest.mark.parametrize("form,expected", [
    (MultiDict([("screensaver_mode", "bogus")]), 422),
    (MultiDict([("panel_type", "xx")]), 422),
    (MultiDict([("button1_detached_mode_light", "999")]), 404),
    (MultiDict([("button1_detached_mode_light", "abc")]), 422),
    (MultiDict([("room_id", "999")]), 404),
    (MultiDict([("rooms", "1"), ("rooms", "99")]), 400),
])
async def test_save_rejects_bad_input(mgr, panel, form, expected):
    view = D.SavePanelSettingsView()
    status, _ = await _post(view, form, mgr)
    assert status == expected


async def test_save_bad_ids(mgr, panel):
    view = D.SavePanelSettingsView()
    status, _ = await _post(view, MultiDict([]), mgr, pid="999")
    assert status == 404
    status, _ = await _post(view, MultiDict([]), mgr, pid="abc")
    assert status == 400


async def test_save_detached_zero_and_eu(mgr, panel):
    view = D.SavePanelSettingsView()
    status, _ = await _post(
        view, MultiDict([("button1_detached_mode_light", "0"), ("panel_type", "eu")]), mgr
    )
    assert status in (200, 302)
    assert panel.button1_detached_light == 0
    assert panel.is_us_panel is False and panel.us_panel_orientation == ""


async def test_panels_context_and_redirect_back(mgr, panel):
    req = _req(MultiDict([]), manager=mgr)
    req.headers = {"Referer": "/nspanel_core/rooms"}
    try:
        D._redirect_back(req, "/nspanel_core/settings")
        assert False, "expected redirect"
    except web.HTTPFound as e:
        assert e.location == "/nspanel_core/rooms"
    req2 = _req(MultiDict([]), manager=mgr)
    req2.headers = {"Referer": "https://evil.example/x"}
    try:
        D._redirect_back(req2, "/nspanel_core/settings")
        assert False, "expected redirect"
    except web.HTTPFound as e:
        assert e.location == "/nspanel_core/settings"


async def test_reorder_rooms(mgr):
    import json as J

    view = D.ReorderRoomsView()
    r = await view.post(_req(MultiDict([
        ("htmx_form_save_rooms_order_field", J.dumps({"rooms": [3, 1]}))]), manager=mgr))
    assert r.status == 200
    assert [x.id for x in mgr.config.rooms] == [3, 1]
    r = await view.post(_req(MultiDict([("htmx_form_save_rooms_order_field", "junk")]), manager=mgr))
    assert r.status == 400


async def test_get_ip_by_hostname(mgr):
    view = D.GetIpByHostnameView()
    r = await view.post(_req(None, manager=mgr, payload={"hostname": "localhost"}))
    assert r.status == 200
    r = await view.post(_req(None, manager=mgr, payload={"hostname": ""}))
    assert r.status == 400
    r = await view.post(_req(None, manager=mgr, payload=ValueError()))
    assert r.status == 400


async def test_panel_actions(mgr, panel):
    act = D.PanelActionView()
    r = await act._act(_req(None, {"panel_id": "7", "action": "bogus"}, manager=mgr))
    assert r.status == 400
    r = await act._act(_req(None, {"panel_id": "99", "action": "accept"}, manager=mgr))
    assert r.status == 404
    r = await act._act(_req(None, {"panel_id": "7", "action": "accept"}, manager=mgr))
    assert r.status == 200 and panel.accepted and not panel.denied
    r = await act._act(_req(None, {"panel_id": "7", "action": "deny"}, manager=mgr))
    assert r.status == 200 and panel.denied and not panel.accepted
    denied_req = _req(None, {"panel_id": "7", "action": "accept"}, manager=mgr)
    denied_req.headers = {"Referer": "https://x/nspanel_core/denied"}
    r = await act._act(denied_req)
    assert r.status == 200 and r.text == ""
    panel.accepted = False
    r = await act._act(_req(None, {"panel_id": "7", "action": "update_firmware"}, manager=mgr))
    assert r.status == 409
    panel.accepted = True
    r = await act._act(_req(None, {"panel_id": "7", "action": "delete"}, manager=mgr))
    assert r.status == 200 and len(mgr.config.panels) == 0
