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


def draw_circuit_n(draw, cx, cy, s, color, trace_ratio=0.052):
    """The N, traced from the reference artwork's own skeleton (pixel-extracted
    polylines, normalized to the icon square) drawn in the clean line style.

    Structure (y down, fractions of s):
      N-path outer: left vertical x0.196 (y0.847->0.221), 45-deg jog, diagonal
      (0.312,0.184)->(0.635,0.500), right vertical x0.64 (y0.500->0.258), top zigzag
      N-path inner: left vertical x0.344 (y0.826->0.542) with bottom jog,
      diagonal (0.381,0.505)->(0.683,0.805), jog, right vertical x0.79
      (y0.800->0.274), top zigzag
      inner long diagonal with 45-deg bends at both ends:
      (0.280,0.258)->(0.344,0.342)->(0.677,0.684)->(0.730,0.705)->(0.730,0.753)
      thin decoration verticals: x0.725 (y0.332..0.632), x0.275 (y0.379..0.684)
      with a 45-deg bend, plus ring/dot nodes at the measured positions.
    """
    w = max(3, int(s * 0.052))   # THICK strokes (user request)
    r = int(w * 0.9)

    paths = [
        # N-path outer
        [(0.196, 0.847), (0.206, 0.221), (0.312, 0.184), (0.635, 0.500),
         (0.640, 0.258), (0.619, 0.216), (0.651, 0.184)],
        # N-path inner
        [(0.328, 0.805), (0.349, 0.742), (0.344, 0.542), (0.381, 0.505),
         (0.683, 0.805), (0.788, 0.800), (0.794, 0.274), (0.751, 0.226),
         (0.788, 0.168)],
        # inner long diagonal (both-end 45-deg bends)
        [(0.280, 0.258), (0.344, 0.342), (0.677, 0.684), (0.730, 0.705),
         (0.730, 0.753)],
        # thin decoration verticals (with bends into the long diagonal)
        [(0.725, 0.332), (0.725, 0.632)],
        [(0.275, 0.379), (0.275, 0.684), (0.323, 0.316)],
    ]

    def P(fx, fy):
        return (cx + (fx - 0.5) * s, cy + (fy - 0.5) * s)

    for pts in paths:
        pp = [P(*pt) for pt in pts]
        draw.line(pp, fill=color, width=w, joint="curve")

    # Node dots at all stroke endpoints (simple style: bright-center dots)
    endpoints = []
    for pts in paths:
        endpoints.append(pts[0])
        endpoints.append(pts[-1])
    seen = set()
    for pt in endpoints:
        key = (round(pt[0], 2), round(pt[1], 2))
        if key in seen:
            continue
        seen.add(key)
        x, y = P(*pt)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        rd = int(r * 0.5)
        draw.ellipse([x - rd, y - rd, x + rd, y + rd], fill=(215, 246, 252, color[3]))

    # Rings where the reference has them (bottom-left terminal of the outer
    # path and the two right-side top zigzag terminals)
    for (fx, fy, k) in [(0.196, 0.847, 1.5), (0.651, 0.184, 1.2), (0.788, 0.168, 1.2)]:
        x, y = P(fx, fy)
        rr = int(w * k)
        draw.ellipse([x - rr, y - rr, x + rr, y + rr], outline=color, width=max(2, w // 2))
        cd = max(2, w // 3)
        draw.ellipse([x - cd, y - cd, x + cd, y + cd], fill=color)


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
    """Flat style: no glow passes — just the base layer, crisp."""
    return base, ImageDraw.Draw(base)


def make_logo(size=1024, with_text=True):
    """Master logo: rounded square panel + neon circuit-N + wordmark + tagline."""
    S = 4  # supersample
    px = size * S
    base, glow = _icon_layers(px, px / 2, px * 0.355, px * 0.48)
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
    base, glow = _icon_layers(px, px / 2, px / 2, px * 0.70)
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
