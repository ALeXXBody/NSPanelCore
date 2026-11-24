#!/usr/bin/env python3
"""The NSP Core boot animation generator.

The logo fades in over the dark background. Restyle it by editing the
PARAMETERS below (or replace splash_boot.png with your own design) and run:

    python3 scripts/make_boot_animation.py

It writes the frames to BOTH HMI sets; recompile after:

    nxwright compile --overwrite custom_components/nspanel_core/hmi_kit /tmp/epoch/nspanel-core-ui.tft

Requirements: Pillow. The logo must be 480x320 (full screen).
"""
from PIL import Image
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- PARAMETERS (the branding knobs) -------------------------------------
N_FRAMES = 10          # how many fade frames (more = smoother, bigger TFT)
FRAME_MS = 150         # ms per frame (set in page0's timer too — keep in sync)
FADE = "ease"          # "linear" | "ease" (fast start, slow settle)
BACKGROUND = (13, 16, 22)  # #0d1016
LOGO = os.path.join(REPO, "custom_components/nspanel_core/hmi_kit/pictures/splash_boot.png")
SETS = (os.path.join(REPO, "custom_components/nspanel_core/hmi_kit/pictures"),
        os.path.join(REPO, "custom_components/nspanel_core/hmi_kit/pictures"))
# --------------------------------------------------------------------------

def curve(t: float) -> float:
    if FADE == "ease":
        return t * t * (3 - 2 * t)  # smoothstep
    return t

logo = Image.open(LOGO).convert("RGB")
assert logo.size == (480, 320), f"the logo must be 480x320, got {logo.size}"
base = Image.new("RGB", logo.size, BACKGROUND)

for directory in SETS:
    for i in range(N_FRAMES):
        frame = Image.blend(base, logo, curve(i / (N_FRAMES - 1)))
        frame.save(os.path.join(directory, f"boot_f{i}.png"))
print(f"{N_FRAMES} frames written to both HMI sets "
      f"({FRAME_MS} ms each = {N_FRAMES * FRAME_MS / 1000:.1f} s)")
print("remember: page0's timer `tim` should match FRAME_MS")
