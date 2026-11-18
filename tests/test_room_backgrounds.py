"""P255 tests — the room background upload pipeline: the processing
standards, the photo-backed generation, and the photo screensaver."""

import os
import sys
import tempfile
import tomllib
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core import bg_process as bgp  # noqa: E402
from nspanel_core import hmi_generate as hg  # noqa: E402

KIT = REPO / "custom_components" / "nspanel_core" / "hmi_kit"


def _photo(path, color=(90, 120, 150), size=(800, 600)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _design(mac="e465b849a100"):
    return dd.PanelDesign(
        mac=mac,
        pages=[dd.DashPage(name="dash_kitchen", title="Kitchen")],
        items=[dd.DashItem(id="l1", page="dash_kitchen", widget="light",
                           entity_id="light.kitchen", label="Ceiling", slot=0)],
    )


# -- the processing standards ---------------------------------------------

def test_process_background_makes_both_variants():
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
        photo = _photo(os.path.join(src, "kitchen.jpg"))
        scr, dash = bgp.process_background(photo, out, "p0")
        assert os.path.isfile(scr) and os.path.isfile(dash)
        assert Image.open(scr).size == (480, 320)
        assert Image.open(dash).size == (480, 320)


def test_dashboard_variant_is_darker():
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
        photo = _photo(os.path.join(src, "kitchen.jpg"))
        scr, dash = bgp.process_background(photo, out, "p0")
        s = Image.open(scr).convert("L")
        d = Image.open(dash).convert("L")
        s_mean = sum(s.getdata()) / (480 * 320)
        d_mean = sum(d.getdata()) / (480 * 320)
        assert d_mean < s_mean * 0.6, "the dashboard variant must be markedly darker"


def test_cover_crop_no_letterbox():
    tall = Image.new("RGB", (400, 1200), (10, 10, 10))
    out = bgp.cover_crop(tall)
    assert out.size == (480, 320)


# -- the generation with the user's photo ----------------------------------

def test_generate_uses_the_photo_for_the_dashboard():
    d = _design()
    d.pages[0].background_image = "kitchen.jpg"
    with tempfile.TemporaryDirectory() as origins, tempfile.TemporaryDirectory() as wd:
        _photo(os.path.join(origins, "kitchen.jpg"))
        hg.generate_source(d, str(KIT), wd, origins_dir=origins)
        src = os.path.join(wd, "hmi")
        # the processed resources exist in the source pictures
        assert os.path.isfile(os.path.join(src, "pictures", "p0_scr.jpg"))
        assert os.path.isfile(os.path.join(src, "pictures", "p0_dash.jpg"))
        # the dash page's bg points at the darkened variant
        page = tomllib.load(open(os.path.join(src, "pages", "dash_kitchen.page.toml"), "rb"))
        bg = next(c for c in page["component"] if c["name"] == "bg")
        assert bg["pic"] == "p0_dash"
        # the resources are declared in app.toml
        app = tomllib.load(open(os.path.join(src, "app.toml"), "rb"))
        assert "p0_dash" in app["pictures"] and "p0_scr" in app["pictures"]


def test_photo_screensaver_regenerates_with_photo_crop_texts():
    d = _design()
    d.pages[0].background_image = "kitchen.jpg"
    d.screensaver_page = "dash_kitchen"
    with tempfile.TemporaryDirectory() as origins, tempfile.TemporaryDirectory() as wd:
        _photo(os.path.join(origins, "kitchen.jpg"))
        hg.generate_source(d, str(KIT), wd, origins_dir=origins)
        src = os.path.join(wd, "hmi")
        page = tomllib.load(open(os.path.join(src, "pages", "screensaver.page.toml"), "rb"))
        names = [c["name"] for c in page["component"]]
        # the component order is UNTOUCHED (the firmware's wake logic depends on it)
        assert names == ["bg", "curTime", "curDay", "curAMPM", "wake"]
        by_name = {c["name"]: c for c in page["component"]}
        assert by_name["bg"]["pic"] == "p0_scr"
        for text_name, crop in (("curTime", "sct"), ("curDay", "scd"), ("curAMPM", "sca")):
            assert by_name[text_name]["sta"] == 2
            assert by_name[text_name]["pic"] == crop
            assert os.path.isfile(os.path.join(src, "pictures", crop + ".png"))
        app = tomllib.load(open(os.path.join(src, "app.toml"), "rb"))
        for res in ("p0_scr", "sct", "scd", "sca"):
            assert res in app["pictures"]


def test_no_photo_keeps_the_authored_screensaver():
    d = _design()
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, str(KIT), wd)
        src = os.path.join(wd, "hmi")
        page = tomllib.load(open(os.path.join(src, "pages", "screensaver.page.toml"), "rb"))
        by_name = {c["name"]: c for c in page["component"]}
        assert by_name["bg"]["pic"] == "bg_plain"      # the authored background
        assert "sta" not in by_name["curTime"]          # no photo-crop trick


def test_compile_with_the_photo_succeeds():
    d = _design()
    d.pages[0].background_image = "kitchen.jpg"
    d.screensaver_page = "dash_kitchen"
    with tempfile.TemporaryDirectory() as origins, tempfile.TemporaryDirectory() as wd:
        _photo(os.path.join(origins, "kitchen.jpg"))
        hg.generate_source(d, str(KIT), wd, origins_dir=origins)
        out = os.path.join(wd, "panel.tft")
        hg.compile_tft(wd, out)
        assert os.path.getsize(out) > 200_000
