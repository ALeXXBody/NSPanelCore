#!/usr/bin/env python3
"""
NSPanel Core brand asset generator.

Generates the master logo (neon circuit-N in a rounded square + wordmark +
'SMART WALL OS' tagline) and all derived sizes:
  branding/nspanel-core-logo.png        1024x1024 master
  docker/icon.png / icon128.png / icon64.png / logo.png   (HA add-on icons)
  docker/web-ui/public icons (icon-512.png, icon-192.png)
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_DIR = os.path.join(REPO, "branding")

# Brand palette
PANEL_BG = (13, 16, 22, 255)      # near-black blue
CYAN = (57, 200, 232, 255)        # brand cyan
CYAN_GLOW = (57, 200, 232, 90)
WHITE = (240, 244, 248, 255)
GRAY = (140, 150, 160, 255)

FONT_VAR = os.path.join(BRAND_DIR, "fonts", "Montserrat.ttf")


def font(size, weight="Light"):
    f = ImageFont.truetype(FONT_VAR, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def rounded_rect(draw, cx, cy, s, radius_ratio, width_ratio, fill):
    draw.rounded_rectangle(
        [cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2],
        radius=int(s * radius_ratio),
        outline=fill,
        width=max(2, int(s * width_ratio)),
    )


def draw_circuit_n(draw, cx, cy, s, color, trace_ratio=0.024, node_r_ratio=1.0):
    """Circuit-style N matching the reference topology, drawn in the simple
    line style: two left verticals, two parallel diagonals converging on a
    junction at the foot of the right vertical, ring nodes at the left
    terminals and on the right branch, dots at the remaining terminals.
    """
    w = max(3, int(s * trace_ratio))
    r = int(w * node_r_ratio)

    # Geometry measured from the reference artwork (fractions of icon size s)
    xL = cx - s * 0.25          # outer left vertical
    xB = cx - s * 0.14          # inner left vertical (short, right of xL)
    xR = cx + s * 0.135         # right vertical
    yTop = cy - s * 0.24        # top ring of left vertical
    yBot = cy + s * 0.27        # bottom ring of left vertical
    jy = cy + s * 0.09          # junction height (59% on screen)

    bright = (xB, cy - s * 0.02)  # bright node: origin of inner diagonal

    # --- Traces ---
    # left outer vertical: bottom ring -> top ring
    draw.line([(xL, yBot), (xL, yTop)], fill=color, width=w)
    # inner left vertical: bright node -> dot terminal above
    draw.line([bright, (xB, cy - s * 0.18)], fill=color, width=w)
    # diagonal 1 (long): top-left ring -> junction
    draw.line([(xL, yTop), (xR, jy)], fill=color, width=w)
    # diagonal 2 (steeper, converging): bright node -> junction
    draw.line([bright, (xR, jy)], fill=color, width=w)
    # right vertical: junction -> top, then 45-degree branch up-right to a ring
    draw.line([(xR, jy), (xR, cy - s * 0.23)], fill=color, width=w)
    bx, by = cx + s * 0.29, cy - s * 0.37
    draw.line([(xR, cy - s * 0.23), (bx, by)], fill=color, width=w)

    # --- Ring nodes (donut: circle outline + small center dot) ---
    def ring(x, y, radius):
        rr = int(w * radius)
        draw.ellipse([x - rr, y - rr, x + rr, y + rr], outline=color, width=max(2, w // 2))
        cd = max(2, w // 3)
        draw.ellipse([x - cd, y - cd, x + cd, y + cd], fill=color)

    ring(xL, yBot, 1.6)   # bottom-left terminal ring
    ring(xL, yTop, 1.6)   # top-left: diagonal origin ring
    ring(bx, by, 1.4)     # branch terminal ring

    # --- Bright junction node (where diagonals meet the right vertical) ---
    jr = int(w * 1.5)
    draw.ellipse([xR - jr, jy - jr, xR + jr, jy + jr], fill=color)
    jr2 = int(jr * 0.5)
    draw.ellipse([xR - jr2, jy - jr2, xR + jr2, jy + jr2],
                 fill=(215, 246, 252, color[3]))

    # --- Simple dot terminals ---
    dots = [
        bright,                          # bright node on the left
        (xB, cy - s * 0.18),             # inner vertical top terminal
        (xR, cy - s * 0.16),             # right vertical top before branch
    ]
    for (dx, dy) in dots:
        draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=color)
        rd = int(r * 0.5)
        draw.ellipse([dx - rd, dy - rd, dx + rd, dy + rd],
                     fill=(215, 246, 252, color[3]))


def _icon_layers(px, icon_cx, icon_cy, icon_size):
    """Returns (base_rgba, glow_rgba) drawings of panel + icon."""
    base = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    m = int(px * 0.055)
    d.rounded_rectangle([m, m, px - m, px - m], radius=int(px * 0.15), fill=PANEL_BG)

    glow = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    rounded_rect(gd, icon_cx, icon_cy, icon_size, 0.18, 0.03, CYAN_GLOW)
    draw_circuit_n(gd, icon_cx, icon_cy, icon_size, CYAN_GLOW, 0.03)
    return base, glow


def _compose_with_glow(base, glow, px):
    """Composite two glow passes, then return a fresh ImageDraw on the result."""
    for blur in (int(px * 0.022), int(px * 0.008)):
        base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(blur)))
    return base, ImageDraw.Draw(base)


def make_logo(size=1024, with_text=True):
    """Master logo: rounded square panel + neon circuit-N + wordmark + tagline."""
    S = 4  # supersample
    px = size * S
    base, glow = _icon_layers(px, px / 2, px * 0.355, px * 0.44)
    img, d = _compose_with_glow(base, glow, px)

    icon_cx, icon_cy = px / 2, px * 0.355
    icon_size = px * 0.44
    rounded_rect(d, icon_cx, icon_cy, icon_size, 0.18, 0.022, CYAN)
    draw_circuit_n(d, icon_cx, icon_cy, icon_size, CYAN)

    if with_text:
        f_word = font(int(px * 0.105), "SemiBold")
        t1, t2 = "NSPanel ", "Core"
        w1 = d.textlength(t1, font=f_word)
        w2 = d.textlength(t2, font=f_word)
        x = (px - (w1 + w2)) / 2
        y = px * 0.66
        d.text((x, y), t1, font=f_word, fill=WHITE)
        d.text((x + w1, y), t2, font=f_word, fill=CYAN)

        f_tag = font(int(px * 0.042), "Light")
        tag = "SMART WALL OS"
        tracking = px * 0.008
        total = sum(d.textlength(ch, font=f_tag) for ch in tag) + tracking * (len(tag) - 1)
        x = (px - total) / 2
        y = px * 0.80
        for ch in tag:
            d.text((x, y), ch, font=f_tag, fill=GRAY)
            x += d.textlength(ch, font=f_tag) + tracking

    return img.resize((size, size), Image.LANCZOS)


def make_icon_only(size=512):
    """App icon: rounded dark panel + neon icon, no text."""
    S = 4
    px = size * S
    base, glow = _icon_layers(px, px / 2, px / 2, px * 0.62)
    img, d = _compose_with_glow(base, glow, px)
    icon_cx, icon_cy, icon_size = px / 2, px / 2, px * 0.62
    rounded_rect(d, icon_cx, icon_cy, icon_size, 0.18, 0.028, CYAN)
    draw_circuit_n(d, icon_cx, icon_cy, icon_size, CYAN)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(BRAND_DIR, exist_ok=True)
    logo = make_logo(1024)
    logo.convert("RGB").save(os.path.join(BRAND_DIR, "nspanel-core-logo.png"))

    docker_dir = os.path.join(REPO, "docker")
    make_icon_only(512).convert("RGB").save(os.path.join(docker_dir, "icon.png"))
    make_icon_only(128).convert("RGB").save(os.path.join(docker_dir, "icon128.png"))
    make_icon_only(64).convert("RGB").save(os.path.join(docker_dir, "icon64.png"))
    make_icon_only(256).convert("RGB").save(os.path.join(docker_dir, "logo.png"))

    ui_dir = os.path.join(REPO, "docker", "web-ui", "public")
    if os.path.isdir(ui_dir):
        make_icon_only(512).convert("RGB").save(os.path.join(ui_dir, "icon-512.png"))
        make_icon_only(192).convert("RGB").save(os.path.join(ui_dir, "icon-192.png"))
    print("brand assets written")


if __name__ == "__main__":
    main()
