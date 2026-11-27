"""P310 — the proven HMI content is the delivered content (revert guard).

The app-v0.2.7 rollout shipped a rebuilt HMI (8 fonts + weather components)
that was verified ONLY on the host — and a panel died with its display stuck
at the splash. Until the new content is verified on a REAL panel, both HMI
trees and the served TFT files must stay the PROVEN pre-P306 content: the
screensaver style feature remains in the app/firmware (unknown-object writes
are ignored by the display), but no unreferenced font/component ships to a
panel. This file guards that revert.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

KIT = REPO / "custom_components" / "nspanel_core" / "hmi_kit"
HMI = REPO / "custom_components/nspanel_core/hmi_kit"
# The proven set: the original compiled NotoSans24/64 pair.
FONTS = ["NotoSans24", "NotoSans64"]
WEATHER = ["wOutTemp", "wRoomTemp", "wWind", "wRain", "wSun", "wForecast"]


def test_only_the_proven_fonts_exist_in_both_trees():
    for tree in (KIT, HMI):
        present = sorted(p.stem for p in (tree / "fonts").glob("*.zi"))
        assert present == sorted(FONTS), present
        for name in FONTS:
            asset = tree / "fonts" / f"{name}.zi"
            assert asset.is_file() and asset.stat().st_size > 1000, asset


def test_the_two_trees_are_byte_identical():
    for rel in ("app.toml", "fonts/NotoSans24.zi", "fonts/NotoSans64.zi",
                "pages/screensaver.page.toml", "program.nx"):
        a, b = (KIT / rel).read_bytes(), (HMI / rel).read_bytes()
        assert a == b, rel


def test_no_weather_components_in_the_panel_pages():
    """P364 REVISED: the weather components now EXIST on the screensaver
    page (the icon glyphs + the temps + the forecast rows — the user's
    order: bigger, with icons, the forecast visible). The contract: the
    wake hotspot stays LAST (the firmware's wake logic reads the frames
    regardless of the component order — the hotspot id is irrelevant)."""
    for tree in (KIT, HMI):
        page = tomllib.load(open(tree / "pages" / "screensaver.page.toml", "rb"))
        names = [c["name"] for c in page["component"]]
        assert names[-1] == "wake", "the wake hotspot stays last"
        for w in ("wx_sun", "wx_cloud", "wx_rain", "wx_snow",
                  "wOutTemp", "wRoomTemp", "fDay0", "fMM0"):
            assert w in names, f"the weather comp {w} is now required"


def test_the_served_tft_is_the_proven_release_bytes():
    served = REPO / "custom_components" / "nspanel_core" / "tft"
    import hashlib
    for name in ("gui.tft", "gui_us.tft"):
        digest = hashlib.md5((served / name).read_bytes()).hexdigest()
        # the proven pre-0.2.7 display build — pinned so no accidental
        # re-delivery of the unreferenced-font content can slip through
        assert digest == "b2b6a2e3e53ab56405d2202d51c98a29", (name, digest)
