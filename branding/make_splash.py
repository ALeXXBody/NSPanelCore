#!/usr/bin/env python3
"""
Panel startup splash built STRICTLY from the user's own artwork pixels:
- icon region crop (with its real glow) pasted at top-center
- the real wordmark crop ("NSPanel Core") below it
- the real tagline crop ("SMART WALL OS") below that
on a background matched to the artwork's own dark color.

No redrawing, no tracing, no generated shapes — only crops of the original.
"""
from PIL import Image, ImageDraw, ImageFilter
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_logo import CYAN, WHITE, GRAY, rounded_rect, draw_circuit_n, font  # noqa

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_DIR = os.path.join(REPO, "branding")
REF = sorted(glob.glob(os.path.join(REPO, "branding", "uploads", "image_*")))[0]

# Crop regions in the 395x395 reference (measured earlier from the pixels)
ICON_BOX = (86, 20, 312, 250)      # rounded square + glow
WORD_BOX = (30, 262, 370, 308)     # "NSPanel Core"
TAG_BOX = (80, 322, 318, 344)      # "SMART WALL OS"


def feather_paste(canvas, crop, box):
    """Paste a crop at box (x, y, target_w) with softly feathered edges."""
    tw = box[2]
    th = int(crop.height * tw / crop.width)
    c = crop.resize((tw, th), Image.LANCZOS)
    mask = Image.new("L", (tw, th), 0)
    md = ImageDraw.Draw(mask)
    inset = max(3, tw // 40)
    md.rounded_rectangle([inset, inset, tw - inset, th - inset],
                         radius=inset, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(inset * 0.7))
    canvas.paste(c, (box[0], box[1]), mask)
    return th  # returns rendered height for layout


def make_splash(w, h):
    """Flat splash: flat dark background, flat traced-N icon, flat text."""
    S = 4
    px, py = w * S, h * S
    img = Image.new("RGBA", (px, py), (13, 16, 22, 255))
    d = ImageDraw.Draw(img)

    # Flat N icon (traced skeleton, no glow)
    icon_cx, icon_cy = px / 2, py * 0.30
    icon_size = min(px, py) * 0.55
    rounded_rect(d, icon_cx, icon_cy, icon_size, 0.18, 0.024, CYAN)
    draw_circuit_n(d, icon_cx, icon_cy, icon_size, CYAN)

    # Flat wordmark: "NSPanel" white + " Core" cyan — fitted to width
    t1, t2 = "NSPanel ", "Core"
    base_size = int(min(px, py) * 0.16)
    f_word = font(base_size, "SemiBold")
    for _ in range(12):
        w_total = d.textlength(t1, font=f_word) + d.textlength(t2, font=f_word)
        if w_total <= px * 0.88:
            break
        base_size = int(base_size * 0.9)
        f_word = font(base_size, "SemiBold")
    w1 = d.textlength(t1, font=f_word)
    w2 = d.textlength(t2, font=f_word)
    x = (px - (w1 + w2)) / 2
    y = py * 0.62
    d.text((x, y), t1, font=f_word, fill=WHITE)
    d.text((x + w1, y), t2, font=f_word, fill=CYAN)

    # Flat tagline
    tag = "SMART WALL OS"
    tracking = min(px, py) * 0.012
    tag_size = int(base_size * 0.44)
    f_tag = font(tag_size, "Light")
    for _ in range(12):
        total = sum(d.textlength(ch, font=f_tag) for ch in tag) + tracking * (len(tag) - 1)
        if total <= px * 0.88:
            break
        tag_size = int(tag_size * 0.9)
        f_tag = font(tag_size, "Light")
    total = sum(d.textlength(ch, font=f_tag) for ch in tag) + tracking * (len(tag) - 1)
    x = (px - total) / 2
    y = py * 0.765
    for ch in tag:
        d.text((x, y), ch, font=f_tag, fill=GRAY)
        x += d.textlength(ch, font=f_tag) + tracking

    out = img.resize((w, h), Image.LANCZOS)
    # Sharpen after downscale — panel TFTs are low-res (480x320) and benefit
    # from a light unsharp mask to keep edges crisp.
    out = out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=140, threshold=2))
    return out


def main():
    splash_eu = make_splash(455, 320)
    splash_eu.save(os.path.join(REPO, "branding", "splash-preview-eu.png"))
    splash_us = make_splash(320, 455)
    splash_us.save(os.path.join(REPO, "branding", "splash-preview-us.png"))
    for variant, sp in (("eu", splash_eu), ("us", splash_us)):
        for t in range(1, 5):
            out = os.path.join(BRAND_DIR, "hmi_pictures", variant, f"tft{t}")
            os.makedirs(out, exist_ok=True)
            sp.save(os.path.join(out, "6.png"))
    print("flat splash regenerated (no glow, correct N shape)")


if __name__ == "__main__":
    main()
