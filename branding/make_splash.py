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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    ref = Image.open(REF).convert("RGB")

    # Background: the artwork's own bottom-edge color (matches seamlessly)
    bg_bottom = ref.getpixel((w // 2 if w < ref.width else ref.width - 10, ref.height - 8))
    bg_top = ref.getpixel((ref.width - 10, 8))
    canvas = Image.new("RGB", (w, h))
    # subtle vertical gradient from top color to bottom color
    for y in range(h):
        t = y / max(1, h - 1)
        col = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        d = ImageDraw.Draw(canvas)
        d.line([(0, y), (w, y)], fill=col)

    icon = ref.crop(ICON_BOX)
    word = ref.crop(WORD_BOX)
    tag = ref.crop(TAG_BOX)

    # Layout: icon top-center, wordmark + tagline below
    icon_w = int(w * (0.52 if w < h else 0.46))
    th_icon = feather_paste(canvas, icon, ((w - icon_w) // 2, int(h * 0.055), icon_w))

    y_after_icon = int(h * 0.055) + th_icon
    gap = int(h * 0.045)
    word_w = int(w * (0.80 if w < h else 0.72))
    y_word = y_after_icon + gap
    feather_paste(canvas, word, ((w - word_w) // 2, y_word, word_w))

    tag_w = int(word_w * 0.66)
    y_tag = y_word + int(th_icon * 0.32) + gap
    feather_paste(canvas, tag, ((w - tag_w) // 2, y_tag, tag_w))

    return canvas


def main():
    splash_eu = make_splash(455, 320)
    splash_eu.save(os.path.join(REPO, "branding", "splash-preview-eu.png"))
    splash_us = make_splash(320, 455)
    splash_us.save(os.path.join(REPO, "branding", "splash-preview-us.png"))
    for variant, sp in (("eu", splash_eu), ("us", splash_us)):
        for t in range(1, 5):
            sp.save(os.path.join(REPO, "docker", "HMI_files", "hmi_pictures",
                                 variant, f"tft{t}", "6.png"))
    print("splash composed from the user's own artwork pixels (crops only)")


if __name__ == "__main__":
    main()
