#!/usr/bin/env python3
"""P360: the kit's UI picture set, drawn in the NSPanel Core brand palette.

The user's order: make the panel look like the studio (the app's look).
The old tile pictures were flat blue/green rectangles with no relation to
the brand; the backgrounds were unstyled. This script REGENERATES:

  btn_off / btn_on       the dual-state tiles (210x96) — dark card / cyan lit
  btn_minus / btn_plus   the detail page's -/+ (90x90, RGBA)
  btn_room / btn_scenes  the navigation tiles (210x64) with glyphs
  bg_home / bg_room / bg_plain / bg_scenes  the page backgrounds (480x320)

Palette (branding/make_logo.py): PANEL_BG #0D1016, card #141922, CYAN
#39C8E8, WHITE #F0F4F8, GRAY #8C96A0. Everything is opaque RGB(A) drawn
at the exact resource sizes the kit's pages expect — drop-in replacement.

Usage: python3 branding/make_kit_pictures.py [--out <kit pictures dir>]
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT_PICS = os.path.join(REPO, "custom_components", "nspanel_core", "hmi_kit", "pictures")

PANEL_BG = (13, 16, 22, 255)        # #0D1016 — the brand near-black
CARD = (20, 25, 34, 255)            # #141922 — the card surface
CARD_LIT = (23, 42, 52, 255)        # the on-state card (cyan-tinted dark)
CYAN = (57, 200, 232, 255)          # #39C8E8
CYAN_DIM = (57, 200, 232, 150)      # the off-state border
CYAN_GLOW = (57, 200, 232, 36)
WHITE = (240, 244, 248, 255)        # #F0F4F8
GRAY = (140, 150, 160, 255)         # #8C96A0


def rounded(draw, box, radius, fill=None, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def tile_button(on: bool, w: int = 210, h: int = 96) -> Image.Image:
    """The dual-state tile: a dark card, the cyan accent when ON."""
    s = 4  # supersample for smooth corners
    W, H, R = w * s, h * s, 14 * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if on:
        # the lit card: a cyan-tinted surface + the solid cyan border + a glow
        d.rounded_rectangle((0, 0, W - 1, H - 1), radius=R, fill=CYAN_GLOW)
        d.rounded_rectangle((2 * s, 2 * s, W - 1 - 2 * s, H - 1 - 2 * s),
                            radius=R - 2 * s, fill=CARD_LIT)
        d.rounded_rectangle((2 * s, 2 * s, W - 1 - 2 * s, H - 1 - 2 * s),
                            radius=R - 2 * s, outline=CYAN, width=2 * s)
    else:
        # the off card: the dark surface + the dim cyan border
        d.rounded_rectangle((0, 0, W - 1, H - 1), radius=R, fill=CARD)
        d.rounded_rectangle((2 * s, 2 * s, W - 1 - 2 * s, H - 1 - 2 * s),
                            radius=R - 2 * s, outline=CYAN_DIM, width=2 * s)
    return im.resize((w, h), Image.LANCZOS)


def round_button(glyph: str, w: int = 90, h: int = 90) -> Image.Image:
    """The detail page's -/+ button: a dark disc + a cyan glyph."""
    s = 4
    W, H = w * s, h * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (W // 2, H // 2)
    r = W // 2 - 2 * s
    d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=CARD,
              outline=CYAN_DIM, width=2 * s)
    bar = 5 * s
    d.rounded_rectangle((c[0] - r // 2, c[1] - bar // 2,
                         c[0] + r // 2, c[1] + bar // 2),
                        radius=bar // 2, fill=WHITE)
    if glyph == "plus":
        d.rounded_rectangle((c[0] - bar // 2, c[1] - r // 2,
                             c[0] + bar // 2, c[1] + r // 2),
                            radius=bar // 2, fill=WHITE)
    return im.resize((w, h), Image.LANCZOS)


def studio_card(on: bool | None, w: int = 150, h: int = 110) -> Image.Image:
    """P363: THE STUDIO'S TILE (dashboard.html .studio-tile): a translucent
    dark card (rgba(13,16,22,.82)) over the photo, rounded, a faint cyan
    border, and a small state square top-left (the grey #20242d off / the
    cyan #39c8e8 on — on=None draws no swatch: the menu's tiles)."""
    s = 4
    W, H, R = w * s, h * s, 10 * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # P363e: OPAQUE — the display's alpha handling flattened the cards to
    # light blocks; the studio's 82% dark over a photo IS a dark card.
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=R,
                        fill=(18, 22, 29, 255))
    d.rounded_rectangle((1 * s, 1 * s, W - 1 - 1 * s, H - 1 - 1 * s),
                        radius=R - 1 * s,
                        outline=(57, 200, 232, 110), width=1 * s)
    if on is not None:
        sw = 26 * s
        d.rounded_rectangle((12 * s, 10 * s, 12 * s + sw, 10 * s + sw),
                            radius=8 * s,
                            fill=(57, 200, 232, 255) if on else (32, 36, 45, 255))
    return im


import math as _math

def weather_icon(kind: str, size: int = 64) -> Image.Image:
    """P364: the weather glyphs in the brand style — the cyan/white shapes
    on transparent. kind: sun | cloud | rain | snow."""
    s = 4
    W = H = size * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    WHITE = (240, 244, 248, 255)
    if kind == "sun":
        c = (W // 2, H // 2)
        r = int(W * 0.22)
        for i in range(8):
            ang = _math.pi / 4 * i
            x1 = c[0] + int(r * 1.5 * _math.cos(ang))
            y1 = c[1] + int(r * 1.5 * _math.sin(ang))
            x2 = c[0] + int(r * 1.95 * _math.cos(ang))
            y2 = c[1] + int(r * 1.95 * _math.sin(ang))
            d.line((x1, y1, x2, y2), fill=WHITE, width=3 * s)
        d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=WHITE)
    elif kind in ("cloud", "rain", "snow"):
        # the cloud body
        d.ellipse((int(W * 0.18), int(H * 0.28), int(W * 0.52), int(H * 0.62)), fill=WHITE)
        d.ellipse((int(W * 0.34), int(H * 0.18), int(W * 0.74), int(H * 0.56)), fill=WHITE)
        d.rounded_rectangle((int(W * 0.18), int(H * 0.42), int(W * 0.74), int(H * 0.60)),
                            radius=int(W * 0.09), fill=WHITE)
        if kind == "rain":
            for i, dx in enumerate((0.28, 0.42, 0.56)):
                x = int(W * dx)
                y1 = int(H * 0.66)
                d.line((x, y1, x - int(W * 0.05), y1 + int(H * 0.16)),
                       fill=(57, 200, 232, 255), width=3 * s)
        else:  # snow
            for i, dx in enumerate((0.28, 0.42, 0.56)):
                x = int(W * dx)
                y = int(H * 0.74)
                r = int(W * 0.045)
                d.ellipse((x - r, y - r, x + r, y + r), fill=(57, 200, 232, 255))
    return im.resize((size, size), Image.LANCZOS)


def nav_tile(kind: str, w: int = 210, h: int = 64) -> Image.Image:
    """The home page's navigation tile: a dark card + a cyan glyph.

    kind: "room" (a 2x2 grid glyph) or "scenes" (a star glyph).
    """
    s = 4
    W, H, R = w * s, h * s, 10 * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=R, fill=CARD)
    d.rounded_rectangle((1 * s, 1 * s, W - 1 - 1 * s, H - 1 - 1 * s),
                        radius=R - 1 * s, outline=CYAN_DIM, width=2 * s)
    g = 13 * s  # the glyph size
    if kind == "room":
        gx, gy = W // 2 - g, H // 2 - g
        gap = 5 * s
        cell = (g * 2 - gap) // 2
        for dx in (0, cell + gap):
            for dy in (0, cell + gap):
                d.rounded_rectangle((gx + dx, gy + dy, gx + dx + cell,
                                     gy + dy + cell),
                                    radius=3 * s, fill=CYAN)
    else:  # scenes: a 4-point star
        c = (W // 2, H // 2)
        r1, r2 = g, g // 3
        pts = []
        import math
        for i in range(8):
            ang = math.pi / 2 * (i / 2.0) - math.pi / 2
            rr = r1 if i % 2 == 0 else r2
            pts.append((c[0] + rr * math.cos(ang), c[1] + rr * math.sin(ang)))
        d.polygon(pts, fill=CYAN)
    return im.resize((w, h), Image.LANCZOS)


def page_background(seed: int = 0, w: int = 480, h: int = 320) -> Image.Image:
    """The page background: the brand near-black with a faint cyan corner
    vignette — quiet enough to sit behind content and photos."""
    im = Image.new("RGB", (w, h), (13, 16, 22))
    d = ImageDraw.Draw(im, "RGBA")
    # a soft cyan wash from the top-right, alpha fading to zero
    for i in range(h):
        t = i / h
        alpha = int(14 * (1 - t))
        d.line([(0, i), (w, i)], fill=(57, 200, 232, alpha))
    # the card-edge hint at the bottom (the switch strip zone)
    d.line([(0, h - 1), (w, h - 1)], fill=(57, 200, 232, 26), width=2)
    return im


def main() -> None:
    out = KIT_PICS
    args = sys.argv[1:]
    if "--out" in args:
        out = args[args.index("--out") + 1]
    os.makedirs(out, exist_ok=True)

    def save(im: Image.Image, name: str) -> None:
        p = os.path.join(out, name)
        # the kit's RGB resources: flatten alpha onto the brand bg (the
        # panel's picture rendering of RGBA is compiler-dependent)
        if name in ("btn_room", "btn_scenes", "btn_minus", "btn_plus",
                    "sw_red", "sw_warm", "sw_white", "sw_blue", "sw_green",
                    "sw_purple"):
            im.save(p)
        else:
            bg = Image.new("RGB", im.size, (13, 16, 22))
            if im.mode == "RGBA":
                bg.paste(im, (0, 0), im)
            else:
                bg = im.convert("RGB")
            bg.save(p)
        print("wrote", p)

    save(tile_button(False), "btn_off.png")
    save(tile_button(True), "btn_on.png")
    # P363: the studio-card tiles for the dashboard + the menu
    save(studio_card(False), "card_off.png")
    save(studio_card(True), "card_on.png")
    save(studio_card(None), "card_plain.png")
    # P364: the weather glyphs
    for wkind in ("sun", "cloud", "rain", "snow"):
        save(weather_icon(wkind), f"wx_{wkind}.png")
    save(round_button("minus"), "btn_minus.png")
    save(round_button("plus"), "btn_plus.png")
    save(nav_tile("room"), "btn_room.png")
    save(nav_tile("scenes"), "btn_scenes.png")
    for name in ("bg_home", "bg_room", "bg_plain", "bg_scenes"):
        save(page_background(), name + ".png")
    print("the kit's UI pictures regenerated in the brand palette")


if __name__ == "__main__":
    main()
