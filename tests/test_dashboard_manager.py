"""P234 Phase 1 tests — the dashboard wire format + the manager-side service."""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core import dashboard_wire as wire  # noqa: E402


# -- wire format ----------------------------------------------------------

class _State:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


def _item(widget, entity, slot=0):
    return dd.DashItem(id=f"i{slot}", page="dash_x", widget=widget,
                       entity_id=entity, label="L", slot=slot)


def test_switch_on_off():
    it = _item("switch", "switch.plug")
    assert wire.item_statement(it, _State("on")) == "b0.val=1"
    assert wire.item_statement(it, _State("off")) == "b0.val=0"


def test_switch_unavailable_not_sent():
    it = _item("light", "light.x")
    assert wire.item_statement(it, _State("unavailable")) is None


def test_sensor_value_with_unit():
    it = _item("sensor", "sensor.temp", slot=3)
    stmt = wire.item_statement(it, _State("21.5", {"unit_of_measurement": "°C"}))
    assert stmt == 'b3.txt="21.5°C"'


def test_sensor_unknown_not_sent():
    it = _item("sensor", "sensor.temp", slot=1)
    assert wire.item_statement(it, _State("unknown")) is None


def test_climate_current_temperature():
    it = _item("climate", "climate.thermostat", slot=2)
    stmt = wire.item_statement(it, _State("heat", {"current_temperature": 21.5}))
    assert stmt == 'b2.txt="21.5"'


def test_scene_no_state():
    it = _item("scene", "scene.movie", slot=4)
    assert wire.item_statement(it, _State("scening")) is None


# -- manager service (fake hass, no HA import needed beyond storage-free paths)

from nspanel_core.dashboard_manager import DashboardService  # noqa: E402


class FakeHass:
    def __init__(self):
        self.states = _States()
        self.services = _Services()
        self.tasks = []
        self.config_path = "/tmp/opencode/fake-config"

    def config(self, *a):
        return "/tmp/opencode/fake-config/x"

    class _Config:
        def path(self, *parts):
            import tempfile
            d = tempfile.mkdtemp(prefix="nspdash-fake")
            return d

    def __init__(self):
        self.states = _States()
        self.services = _Services()
        self.config = self._Config()
        self._tasks = []

    def async_create_task(self, coro):
        import asyncio
        self._tasks.append(coro)
        # run inline — the tests assert on side effects
        asyncio.new_event_loop().run_until_complete(coro)


class _States:
    def __init__(self):
        self._s = {}

    def get(self, eid):
        return self._s.get(eid)

    def set(self, eid, state):
        self._s[eid] = state


class _Services:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))


def _svc(hass=None):
    hass = hass or FakeHass()

    class FakeManager:
        pass

    class _MgrConfig:
        panels = []

    class FakeStore:
        def __init__(self, hass, v, k):
            pass

        async def async_load(self):
            return None

        async def async_save(self, d):
            self.saved = d

    # patch the Store import inside dashboard_manager
    import nspanel_core.dashboard_manager as dm

    orig = dm.Store
    dm.Store = FakeStore
    try:
        mgr = FakeManager()
        mgr.hass = hass
        mgr.config = _MgrConfig()
        mgr._publish = _publish_capture(mgr)
        svc = dm.DashboardService(hass, mgr)
        svc._designs["e465b849a100"] = _make_design()
        svc._maps["e465b849a100"] = dd.component_map(svc._designs["e465b849a100"])
        svc._page_ids["e465b849a100"] = dd.page_ids(svc._designs["e465b849a100"])
        return svc, mgr
    finally:
        dm.Store = orig


def _publish_capture(mgr):
    import json
    mgr.published = []

    async def pub(topic, payload, retain=False):
        mgr.published.append((topic, json.loads(payload)))

    return pub


def _make_design():
    return dd.PanelDesign(
        mac="e465b849a100",
        pages=[dd.DashPage(name="dash_kitchen", title="Kitchen")],
        items=[
            dd.DashItem(id="l1", page="dash_kitchen", widget="light",
                        entity_id="light.kitchen", label="Ceiling", slot=0),
        ],
    )


def test_design_roundtrip_through_service():
    svc, mgr = _svc()
    d = _make_design()
    import asyncio

    asyncio.get_event_loop_policy()
    # async_save_design requires a running loop:
    import anyio

    async def go():
        await svc.async_save_design(d)
        assert svc.has_design("e465b849a100")
        assert svc.design("e465b849a100").pages[0].name == "dash_kitchen"

    anyio.run(go)


def test_touch_routes_to_service_call():
    svc, mgr = _svc()
    svc.on_touch("e465b849a100", dd.MENU_PAGE_ID,
                 svc._maps["e465b849a100"]["room"]["m0"], 0)
    # menu hotspot m0 → navigate to dash_kitchen (published dash command)
    import json as _json
    topics = [t for t, p in mgr.published]
    assert any("command" in t for t in topics)
    nav = [p for t, p in mgr.published if "dash" in str(p.get("command", ""))]
    assert any(p.get("payload") == "page dash_kitchen" for p in nav)


def test_touch_on_light_item_opens_detail():
    # P274: the light/RGB tiles open the entity card (the detail page) —
    # the on/off, the intensity, the color live there
    svc, mgr = _svc()
    comp = svc._maps["e465b849a100"]["dash_kitchen"]["b0"]
    svc.on_touch("e465b849a100", 7, comp, 0)
    import json as _json
    nav = [p for t, p in mgr.published if p.get("command") == "dash"]
    assert any(p.get("payload") == "dp=8" for p in nav), nav


def test_touch_on_switch_item_toggles():
    svc, mgr = _svc()
    design = svc._designs["e465b849a100"]
    design.items[0].widget = "switch"
    design.items[0].entity_id = "switch.plug"
    comp = svc._maps["e465b849a100"]["dash_kitchen"]["b0"]
    svc.on_touch("e465b849a100", 7, comp, 0)
    assert any(
        d == ("switch", "toggle", {"entity_id": "switch.plug"})
        for d in svc.hass.services.calls
    )


def test_detail_brightness_minus_plus():
    svc, mgr = _svc()
    dmap = svc._maps["e465b849a100"]["det0"]
    svc.on_touch("e465b849a100", 8, dmap["minus"], 0)
    assert any(
        d == ("light", "turn_on", {"entity_id": "light.kitchen", "brightness_step": -64})
        for d in svc.hass.services.calls
    )
    svc.on_touch("e465b849a100", 8, dmap["plus"], 0)
    assert any(
        d == ("light", "turn_on", {"entity_id": "light.kitchen", "brightness_step": 64})
        for d in svc.hass.services.calls
    )


def test_detail_color_preset():
    # the swatches exist on RGB items only — the plain light detail has none
    svc, mgr = _svc()
    svc._designs["e465b849a100"].items[0].widget = "rgb_light"
    svc._maps["e465b849a100"] = dd.component_map(svc._designs["e465b849a100"])
    dmap = svc._maps["e465b849a100"]["det0"]
    svc.on_touch("e465b849a100", 8, dmap["c2"], 0)  # the red preset
    assert any(
        d == ("light", "turn_on",
              {"entity_id": "light.kitchen", "rgb_color": [255, 60, 60]})
        for d in svc.hass.services.calls
    )


def test_touch_press_ignored_releases_only():
    svc, mgr = _svc()
    comp = svc._maps["e465b849a100"]["dash_kitchen"]["b0"]
    svc.on_touch("e465b849a100", 7, comp, 1)
    assert svc.hass.services.calls == []


def test_touch_back_goes_to_menu():
    svc, mgr = _svc()
    comp = svc._maps["e465b849a100"]["dash_kitchen"]["back"]
    svc.on_touch("e465b849a100", 7, comp, 0)
    import json as _json
    nav = [p for t, p in mgr.published if p.get("command") == "dash"]
    assert any(p.get("payload") == "page room" for p in nav)


def test_send_rejects_unknown_panel():
    svc, mgr = _svc()

    class P:
        accepted = True
        name = "KitchenPanel"

    mgr.panel_by_mac = lambda mac: None
    import anyio

    async def go():
        r = await svc.async_send_to_panel("deadbeef")
        assert r.get("error")

    anyio.run(go)
