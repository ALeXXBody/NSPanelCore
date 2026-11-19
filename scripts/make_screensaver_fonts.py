#!/usr/bin/env python3
"""Regenerate the screensaver font assets (P306, 0.2.7).

The studio's "Build the screensaver" tab offers real font sizes and weights.
Nextion draws text from compiled ``.zi`` fonts, so size/weight are genuine
assets, not runtime labels. ``nxwright`` draws them from Noto Sans TTFs at the
project's rotation (270) and encoding (iso-8859-1); no Nextion Editor needed.

Requirements: ``nxwright`` on PATH, Python 3 (stdlib only), one-time internet
access to fetch the two pinned TTFs (SHA-256 verified).

Installs the fonts into BOTH HMI source trees and rewrites their ``app.toml``
font lists identically:

  hmi/nspanel-core-native/fonts/
  custom_components/nspanel_core/hmi_kit/fonts/

FONT ORDER IS THE WIRE CONTRACT. The native firmware maps the studio's style
keys to these runtime font IDs (position in the list), so NEVER reorder:

  small  -> 0 (24px regular) / 1 (24px bold)
  medium -> 2 (32px regular) / 3 (32px bold)
  large  -> 4 (48px regular) / 5 (48px bold)
  xlarge -> 6 (64px regular) / 7 (64px bold)

If the order changes, update firmware-native/src/screensaver_parse.cpp and
tests/test_screensaver_fonts.py in the same commit.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HMI_TREES = (
    ROOT / "hmi" / "nspanel-core-native",
    ROOT / "custom_components" / "nspanel_core" / "hmi_kit",
)
TTF_PIN = "ffebf8c1ee449e544955a7e813c54f9b73848eac"  # googlefonts/noto-fonts
TTF_BASE = (
    f"https://raw.githubusercontent.com/googlefonts/noto-fonts/{TTF_PIN}"
    "/hinted/ttf/NotoSans"
)
TTFS = {
    "Regular": ("NotoSans-Regular.ttf",
                "b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5"),
    "Bold": ("NotoSans-Bold.ttf",
             "c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a"),
}
# (font name, TTF key, height) — ORDER IS THE FIRMWARE FONT-ID MAP.
FONTS = (
    ("NotoSans24", "Regular", 24),
    ("NotoSans24Bold", "Bold", 24),
    ("NotoSans32", "Regular", 32),
    ("NotoSans32Bold", "Bold", 32),
    ("NotoSans48", "Regular", 48),
    ("NotoSans48Bold", "Bold", 48),
    ("NotoSans64", "Regular", 64),
    ("NotoSans64Bold", "Bold", 64),
)


def _fetch_ttfs(dest: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, (filename, expected) in TTFS.items():
        target = dest / filename
        if not target.exists():
            print(f"fetching {filename} @ {TTF_PIN[:12]}...")
            urllib.request.urlretrieve(f"{TTF_BASE}/{filename}", target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit(f"{filename}: SHA-256 {digest} != pinned {expected}")
        paths[key] = target
    return paths


def _set_font_list(app_toml: Path, names: list[str]) -> None:
    text = app_toml.read_text(encoding="utf-8")
    block = "fonts = [\n" + "".join(f'    "{n}",\n' for n in names) + "]"
    new, count = re.subn(r"fonts = \[[^\]]*\]", block, text)
    if count != 1:
        raise SystemExit(f"{app_toml}: expected exactly one fonts list, found {count}")
    app_toml.write_text(new, encoding="utf-8")


def main() -> int:
    if shutil.which("nxwright") is None:
        raise SystemExit("nxwright is required on PATH (pip install nxwright)")
    work = Path(tempfile.mkdtemp(prefix="nsp_fonts_"))
    try:
        ttfs = _fetch_ttfs(work)
        # Use one tree as the drawing scaffold, then install into both.
        scaffold = work / "scaffold"
        shutil.copytree(HMI_TREES[0], scaffold)
        for zi in (scaffold / "fonts").glob("*.zi"):
            zi.unlink()
        _set_font_list(scaffold / "app.toml", [])
        for name, key, height in FONTS:
            subprocess.run(
                ["nxwright", "font", str(scaffold), str(ttfs[key]), str(height),
                 "--name", name], check=True,
            )
        names = [name for name, _key, _height in FONTS]
        for tree in HMI_TREES:
            fontdir = tree / "fonts"
            fontdir.mkdir(parents=True, exist_ok=True)
            for name in names:
                shutil.copy2(scaffold / "fonts" / f"{name}.zi", fontdir / f"{name}.zi")
            _set_font_list(tree / "app.toml", names)
            print(f"installed {len(names)} fonts into {tree}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
