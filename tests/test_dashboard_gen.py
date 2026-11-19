"""P234 Phase 1 tests — dashboard design model + HMI generator + compile."""

import os
import sys
import tempfile
import tomllib

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core import hmi_generate as hg  # noqa: E402

KIT = os.path.join(REPO, "custom_components", "nspanel_core", "hmi_kit")


def _design(**overrides) -> dd.PanelDesign:
    pages = overrides.get("pages") or [
        dd.DashPage(name="dash_kitchen", title="Kitchen"),
        dd.DashPage(name="dash_bath", title="Bath"),
    ]
    items = overrides.get("items") or [
        dd.DashItem(id="light1", page="dash_kitchen", widget="light",
                    entity_id="light.kitchen_ceiling", label="Ceiling", slot=0),
        dd.DashItem(id="temp1", page="dash_kitchen", widget="sensor",
                    entity_id="sensor.kitchen_temp", label="Temp", slot=1),
        dd.DashItem(id="rgb1", page="dash_bath", widget="rgb_light",
                    entity_id="light.bath_rgb", label="Bath RGB", slot=2),
    ]
    return dd.PanelDesign(mac="e465b849a100", pages=pages, items=items)


# -- design model --------------------------------------------------------

def test_design_roundtrip():
    d = _design()
    d.validate()
    again = dd.PanelDesign.from_dict(d.to_dict())
    assert again == d or (again.to_dict() == d.to_dict())


def test_design_rejects_bad_entity():
    with pytest.raises(dd.DesignError):
        _design(items=[dd.DashItem(id="x", page="dash_kitchen", widget="light",
                                   entity_id="kitchen_ceiling")]).validate()


def test_design_rejects_bad_widget():
    with pytest.raises(dd.DesignError):
        _design(items=[dd.DashItem(id="x", page="dash_kitchen", widget="vacuum",
                                   entity_id="vacuum.roomba")]).validate()


def test_design_rejects_bad_page_name():
    with pytest.raises(dd.DesignError):
        _design(pages=[dd.DashPage(name="kitchen", title="K")]).validate()


def test_design_rejects_double_slot():
    a = dd.DashItem(id="a", page="dash_kitchen", widget="light",
                    entity_id="light.a", label="A", slot=0)
    b = dd.DashItem(id="b", page="dash_kitchen", widget="light",
                    entity_id="light.b", label="B", slot=0)
    with pytest.raises(dd.DesignError):
        _design(items=[a, b]).validate()


def test_design_rejects_orphan_item():
    orphan = dd.DashItem(id="o", page="dash_nope", widget="light",
                         entity_id="light.o")
    with pytest.raises(dd.DesignError):
        _design(items=_design().items + [orphan]).validate()


def test_design_rejects_seven_pages():
    pages = [dd.DashPage(name=f"dash_p{i}", title=f"P{i}") for i in range(7)]
    with pytest.raises(dd.DesignError):
        _design(pages=pages).validate()


def test_clean_text_neuters_quotes_and_control():
    assert dd.clean_text('a"b\\c\x1bd', 10) == "a'b/c d"


# -- component map (the touch contract) ----------------------------------

def test_component_map_matches_firmware_conventions():
    cmap = dd.component_map(_design())
    # menu page: bg=1, then hotspot/label pairs in page order
    menu = cmap["room"]
    assert menu["bg"] == 1
    assert menu["m0"] == 2
    assert menu["ml0"] == 3
    assert menu["m1"] == 4
    assert menu["ml1"] == 5
    assert "back" in menu
    # dash page: bg=1, title=2, slot items b<n>/l<n>, back last
    k = cmap["dash_kitchen"]
    assert k["bg"] == 1
    assert k["title"] == 2
    assert k["b0"] == 3  # light1's button (slot 0)
    assert k["l0"] == 4
    assert k["b1"] == 5  # temp1's value text (slot 1)
    assert k["l1"] == 6
    assert k["back"] == 7


def test_page_ids_are_base_seven_plus_dash():
    # the room menu (4) + two dash pages (7, 8) + the light detail page (9:
    # the design's single light item gets an entity-card detail page)
    ids = dd.page_ids(_design())
    # the two light-type items (light + RGB) get two detail pages
    assert ids == [4, 7, 8, 9, 10]


# -- generator ------------------------------------------------------------

def test_generate_source_structure():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        cmap = hg.generate_source(d, KIT, wd)
        src = os.path.join(wd, "hmi")
        # base pages copied unchanged
        for page in hg.BASE_PAGES:
            assert os.path.isfile(os.path.join(src, "pages", page + ".page.toml"))
        # dash pages written
        assert os.path.isfile(os.path.join(src, "pages", "dash_kitchen.page.toml"))
        # app.toml lists base seven + dash pages, in order
        app = tomllib.load(open(os.path.join(src, "app.toml"), "rb"))
        # P279: the light detail pages are IN app.toml (nxwright derives the
        # page ids from this list — without them every dp=<id> no-oped)
        assert app["pages"] == (list(hg.BASE_PAGES) + ["dash_kitchen", "dash_bath"]
                                + ["det0", "det1"])  # two light-type items: light1 + rgb1
        assert app["screen"] == "NX4832F035"
        # map file written and equals the computed map
        import json
        assert json.load(open(os.path.join(wd, "component_map.json"))) == cmap


def test_generated_tomls_parse_and_match_the_map():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        cmap = hg.generate_source(d, KIT, wd)
        src = os.path.join(wd, "hmi")
        for page_name, expected in cmap.items():
            toml = tomllib.load(
                open(os.path.join(src, "pages", page_name + ".page.toml"), "rb")
            )
            names = [c["name"] for c in toml["component"]]
            assert names == list(expected.keys()), page_name
            assert sorted(toml["component"], key=lambda c: names.index(c["name"]))
            # every picture resource the page uses exists in the kit
            app = tomllib.load(open(os.path.join(src, "app.toml"), "rb"))
            for c in toml["component"]:
                for key in ("pic", "pic2"):
                    if key in c:
                        assert c[key] in app["pictures"]


def test_generated_menu_and_dash_pages_declare_back_last():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, KIT, wd)
        src = os.path.join(wd, "hmi")
        for name in ("room", "dash_kitchen"):
            toml = tomllib.load(open(os.path.join(src, "pages", name + ".page.toml"), "rb"))
            comps = toml["component"]
            assert comps[-2]["name"] == "back"
            assert comps[-1]["name"] == "back_pic"


# -- the real compile (the pipeline proof) --------------------------------

def test_real_compile_produces_tft():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, KIT, wd)
        out = os.path.join(wd, "panel.tft")
        hg.compile_tft(wd, out)
        size = os.path.getsize(out)
        assert size > 200_000, f"TFT suspiciously small: {size}"
