#!/usr/bin/env python3
"""
Flat render of the USER'S EXACT artwork shape:
- Extract the neon-N silhouette (cyan mask) from the reference image and fill
  it with flat cyan — the exact N shape, zero glow, zero gradient.
- Extract the wordmark/tagline masks and fill flat white/gray.
- Compose the splash (EU 455x320, US 320x455) and the logo/icons from these
  flattened crops. Nothing is drawn by hand — only the user's own shapes.
"""
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_from_reference as b  # noqa  (provides REF paths + save_icons)

REPO = b.REPO
FLAT_CYAN = (57, 200, 232)
FLAT_WHITE = (240, 244, 248)
FLAT_GRAY = (176, 184, 192)
BG = (13, 16, 22)

ref = b.load_reference()
W, H = ref.size  # 395x395
a = np.asarray(ref).astype(int)
R, G, B = a[..., 0], a[..., 1], a[..., 2]

cyan_m = (B > 150) & (G > 150) & (R < 150) & ((G + B) - 2 * R > 80)
white_m = (R > 150) & (G > 150) & (B > 150) & ~cyan_m

# regions
ICON = np.s_[20:255, 80:320]
WORD = np.s_[262:308, 28:372]
TAG = np.s_[320:346, 78:320]


def flatten(region_mask, region, color, w, h, smooth=1.2):
    """Region mask -> solid color shape, smoothed, scaled to (w, h)."""
    m = region_mask[region].astype(np.uint8) * 255
    mi = Image.fromarray(m).filter(ImageFilter.GaussianBlur(smooth))
    mi = mi.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    solid = Image.new("RGBA", (w, h), color + (255,))
    out.paste(solid, (0, 0), mi)
    return out


def compose(w, h):
    canvas = Image.new("RGB", (w, h), BG)

    # icon silhouette — scaled to fit
    icon_w = int(w * (0.55 if w < h else 0.46))
    icon_h = int(icon_w * (236 / 241))
    icon = flatten(cyan_m, ICON, FLAT_CYAN, icon_w, icon_h)
    canvas.paste(icon, ((w - icon_w) // 2, int(h * 0.06)), icon)

    # wordmark + tagline silhouettes
    word_w = int(w * (0.86 if w < h else 0.76))
    word = flatten(white_m | cyan_m, WORD, FLAT_WHITE, word_w, int(word_w * 46 / 344))
    y_word = int(h * 0.60)
    canvas.paste(word, ((w - word_w) // 2, y_word), word)

    tag_w = int(word_w * 0.68)
    tag = flatten(white_m, TAG, FLAT_GRAY, tag_w, int(tag_w * 26 / 242))
    canvas.paste(tag, ((w - tag_w) // 2, y_word + int(word.height * 1.25)), tag)
    return canvas


def main():
    eu = compose(455, 320)
    eu.save(os.path.join(REPO, "branding", "splash-preview-eu.png"))
    us = compose(320, 455)
    us.save(os.path.join(REPO, "branding", "splash-preview-us.png"))

    for variant, sp in (("eu", eu), ("us", us)):
        for t in range(1, 5):
            sp.save(os.path.join(REPO, "docker", "HMI_files", "hmi_pictures",
                                 variant, f"tft{t}", "6.png"))

    # Logo + icons: flat icon silhouette on flat panel
    icon_w = 512
    icon_h = int(icon_w * 236 / 241)
    icon = flatten(cyan_m, ICON, FLAT_CYAN, icon_w, icon_h)
    side = max(icon_w, icon_h)
    panel = Image.new("RGB", (side, side), BG)
    panel.paste(icon, ((side - icon_w) // 2, (side - icon_h) // 2), icon)

    docker_dir = os.path.join(REPO, "docker")
    panel.resize((512, 512), Image.LANCZOS).save(os.path.join(docker_dir, "icon.png"))
    panel.resize((128, 128), Image.LANCZOS).save(os.path.join(docker_dir, "icon128.png"))
    panel.resize((64, 64), Image.LANCZOS).save(os.path.join(docker_dir, "icon64.png"))
    panel.resize((256, 256), Image.LANCZOS).save(os.path.join(docker_dir, "logo.png"))
    ui_dir = os.path.join(REPO, "docker", "web-ui", "public")
    if os.path.isdir(ui_dir):
        panel.resize((512, 512), Image.LANCZOS).save(os.path.join(ui_dir, "icon-512.png"))
        panel.resize((192, 192), Image.LANCZOS).save(os.path.join(ui_dir, "icon-192.png"))
    static_dir = os.path.join(REPO, "docker", "web", "nspanelmanager", "web", "static")
    if os.path.isdir(static_dir):
        panel.resize((128, 128), Image.LANCZOS).save(os.path.join(static_dir, "favicon.png"))

    # master logo: flat composition 1024x1024
    master = Image.new("RGB", (1024, 1024), BG)
    iw = int(1024 * 0.52)
    ih = int(iw * 236 / 241)
    icon = flatten(cyan_m, ICON, FLAT_CYAN, iw, ih)
    master.paste(icon, ((1024 - iw) // 2, int(1024 * 0.08)), icon)
    word_w = int(1024 * 0.78)
    word = flatten(white_m, WORD, FLAT_WHITE, word_w, int(word_w * 46 / 344))
    master.paste(word, ((1024 - word_w) // 2, int(1024 * 0.62)), word)
    tag_w = int(word_w * 0.68)
    tag = flatten(white_m, TAG, FLAT_GRAY, tag_w, int(tag_w * 26 / 242))
    master.paste(tag, ((1024 - tag_w) // 2, int(1024 * 0.76)), tag)
    master.save(os.path.join(OUT := os.path.join(REPO, "branding"),
                             "nspanel-core-logo.png"))
    print("flat render of the user's exact shapes complete")


if __name__ == "__main__":
    main()
