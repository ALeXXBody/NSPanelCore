#!/usr/bin/env python3
"""
Regenerates the panel startup splash (picture 6) for all theme/variant
picture sets in docker/HMI_files/hmi_pictures/ using the NSPanel Core brand:
neon circuit-N icon + 'NSPanel Core' + 'SMART WALL OS' tagline on near-black.

EU picture sets are 455x320 (landscape project), US sets are 320x455
(portrait project - US panels are mounted vertically).
"""
from PIL import Image, ImageDraw, ImageFilter
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_logo import CYAN, CYAN_GLOW, WHITE, GRAY, rounded_rect, draw_circuit_n, font  # noqa

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICS = os.path.join(REPO, "docker", "HMI_files", "hmi_pictures")

BG = (10, 13, 18, 255)


def make_splash(w, h):
    S = 4
    px, py = w * S, h * S
    img = Image.new("RGBA", (px, py), BG)
    d = ImageDraw.Draw(img)

    icon_cx, icon_cy = px / 2, py * 0.30
    icon_size = min(px, py) * 0.42

    glow = Image.new("RGBA", (px, py), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    rounded_rect(gd, icon_cx, icon_cy, icon_size, 0.18, 0.03, CYAN_GLOW)
    draw_circuit_n(gd, icon_cx, icon_cy, icon_size, CYAN_GLOW, 0.03)
    for blur in (int(min(px, py) * 0.025), int(min(px, py) * 0.008)):
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(blur)))
    d = ImageDraw.Draw(img)

    rounded_rect(d, icon_cx, icon_cy, icon_size, 0.18, 0.024, CYAN)
    draw_circuit_n(d, icon_cx, icon_cy, icon_size, CYAN)

    # Wordmark: "NSPanel" white + " Core" cyan
    f_word = font(int(min(px, py) * 0.16), "SemiBold")
    t1, t2 = "NSPanel ", "Core"
    w1 = d.textlength(t1, font=f_word)
    w2 = d.textlength(t2, font=f_word)
    x = (px - (w1 + w2)) / 2
    y = py * 0.62
    d.text((x, y), t1, font=f_word, fill=WHITE)
    d.text((x + w1, y), t2, font=f_word, fill=CYAN)

    # Tagline
    f_tag = font(int(min(px, py) * 0.07), "Light")
    tag = "SMART WALL OS"
    tracking = min(px, py) * 0.012
    total = sum(d.textlength(ch, font=f_tag) for ch in tag) + tracking * (len(tag) - 1)
    x = (px - total) / 2
    y = py * 0.765
    for ch in tag:
        d.text((x, y), ch, font=f_tag, fill=GRAY)
        x += d.textlength(ch, font=f_tag) + tracking

    return img.resize((w, h), Image.LANCZOS)


def main():
    splash_eu = make_splash(455, 320)
    splash_us = make_splash(320, 455)
    splash_eu.save(os.path.join(REPO, "branding", "splash-preview-eu.png"))
    splash_us.save(os.path.join(REPO, "branding", "splash-preview-us.png"))

    count = 0
    for variant, splash in (("eu", splash_eu), ("us", splash_us)):
        for t in range(1, 5):
            dst = os.path.join(PICS, variant, f"tft{t}")
            splash.save(os.path.join(dst, "6.png"))
            count += 1
    print(f"splash regenerated in {count} picture sets")


if __name__ == "__main__":
    main()
