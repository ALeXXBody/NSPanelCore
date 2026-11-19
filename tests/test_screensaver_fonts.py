"""P306 Step 1 — the real screensaver fonts + HMI weather components.

Locks the font ORDER (the native firmware's runtime font-ID map), proves both
HMI trees are identical, checks the weather components the firmware writes,
and compiles a real per-panel TFT so no asset is claimed that cannot render.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core import hmi_generate as hg  # noqa: E402

KIT = REPO / "custom_components" / "nspanel_core" / "hmi_kit"
HMI = REPO / "hmi" / "nspanel-core-native"
# The firmware maps small/medium/large/xlarge (regular/bold) to these ids.
FONTS = [
    "NotoSans24", "NotoSans24Bold",
    "NotoSans32", "NotoSans32Bold",
    "NotoSans48", "NotoSans48Bold",
    "NotoSans64", "NotoSans64Bold",
]
WEATHER = ["wOutTemp", "wRoomTemp", "wWind", "wRain", "wSun", "wForecast"]


def test_fonts_present_in_both_trees_and_byte_identical():
    for tree in (HMI, KIT):
        for name in FONTS:
            asset = tree / "fonts" / f"{name}.zi"
            assert asset.is_file() and asset.stat().st_size > 1000, asset
    for name in FONTS:
        assert (HMI / "fonts" / f"{name}.zi").read_bytes() == (
            KIT / "fonts" / f"{name}.zi").read_bytes(), f"font drift: {name}"


def test_app_toml_font_lists_match_the_pinned_order():
    for tree in (HMI, KIT):
        app = tomllib.load(open(tree / "app.toml", "rb"))
        assert app["fonts"] == FONTS, tree


def test_generator_script_pins_the_font_order():
    """FONTS in make_screensaver_fonts.py IS the wire contract; a reorder
    silently remaps every panel's clock font, so guard the source order."""
    src = (REPO / "scripts" / "make_screensaver_fonts.py").read_text()
    positions = [src.index(f'("{name}", "') for name in FONTS]
    assert positions == sorted(positions), "font order changed — update the firmware map"


def test_screensaver_page_has_weather_components_in_both_trees():
    for tree in (HMI, KIT):
        page = tomllib.load(open(tree / "pages" / "screensaver.page.toml", "rb"))
        by_name = {c["name"]: c for c in page["component"]}
        for name in WEATHER:
            assert name in by_name, (tree, name)
            assert by_name[name]["type"] == "text"
            # the firmware writes full strings (forecast/times) at runtime
            assert by_name[name]["txt_maxl"] >= 24
            assert by_name[name]["font"] in FONTS
        names = [c["name"] for c in page["component"]]
        assert names[:4] == ["bg", "curTime", "curDay", "curAMPM"]
        assert names[-1] == "wake"   # wake stays last; page-id wake logic unaffected
        # every runtime-written clock component can hold the sanitised string
        for name in ("curTime", "curDay", "curAMPM"):
            assert by_name[name]["txt_maxl"] >= 24


def test_generator_reads_fonts_from_the_kit():
    """The old generator hardcoded NotoSans24/64 — a custom kit must flow
    into the generated app.toml unchanged."""
    with tempfile.TemporaryDirectory() as td:
        kit = Path(td) / "kit"
        shutil.copytree(KIT, kit)
        app = (kit / "app.toml").read_text(encoding="utf-8")
        app = re.sub(r"fonts = \[[^\]]*\]", 'fonts = ["CustomA", "CustomB"]', app)
        (kit / "app.toml").write_text(app, encoding="utf-8")
        with tempfile.TemporaryDirectory() as wd:
            hg.generate_source(dd.PanelDesign(mac="e465b849a100"), str(kit), wd)
            generated = tomllib.load(open(Path(wd) / "hmi" / "app.toml", "rb"))
            assert generated["fonts"] == ["CustomA", "CustomB"]


def test_photo_screensaver_keeps_text_style_attributes():
    """Regression: the photo rewrite used to drop txt/pco/xcen — the clock,
    date and new weather text must stay styled on a user's background."""
    from PIL import Image

    d = dd.PanelDesign(
        mac="e465b849a100",
        pages=[dd.DashPage(name="dash_kitchen", title="Kitchen")],
        items=[],
    )
    d.pages[0].background_image = "kitchen.jpg"
    d.screensaver_page = "dash_kitchen"
    with tempfile.TemporaryDirectory() as origins, tempfile.TemporaryDirectory() as wd:
        Image.new("RGB", (800, 600), (90, 120, 150)).save(
            Path(origins) / "kitchen.jpg")
        hg.generate_source(d, str(KIT), wd, origins_dir=origins)
        page = tomllib.load(
            open(Path(wd) / "hmi" / "pages" / "screensaver.page.toml", "rb"))
        by_name = {c["name"]: c for c in page["component"]}
        for name in ("curTime", "curDay", "curAMPM") + tuple(WEATHER):
            comp = by_name[name]
            assert comp["pco"].startswith("#") and comp["bco"].startswith("#"), name
            assert comp["xcen"] in (0, 1, 2) and comp["txt_maxl"] >= 24, name
            assert comp["txt"], name
        assert [c["name"] for c in page["component"]][-1] == "wake"


def test_real_compile_with_new_fonts_and_weather():
    """No font is claimed unless a real nxwright compile accepts it."""
    d = dd.PanelDesign(
        mac="e465b849a100",
        pages=[dd.DashPage(name="dash_kitchen", title="Kitchen")],
        items=[],
    )
    with tempfile.TemporaryDirectory() as wd:
        hg.generate_source(d, str(KIT), wd)
        out = str(Path(wd) / "panel.tft")
        hg.compile_tft(wd, out)
        assert Path(out).stat().st_size > 200_000
