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


def draw_circuit_n(draw, cx, cy, s, color, trace_ratio=0.026, core=True, with_stub=True):
    """Circuit-style N inside an icon of size s centered at (cx, cy).

    Matches the reference: full-height left vertical, a KINKED diagonal
    (steep segment from top-left down to a junction, then a 45-degree
    segment to the bottom of the right vertical), full-height right
    vertical, a 45-degree branch stub off the junction, and small
    rectangular pads sitting on two of the traces.
    """
    w = max(3, int(s * trace_ratio))
    nw, nh = s * 0.30, s * 0.34
    top, bot = cy - nh, cy + nh
    x1, x2 = cx - nw, cx + nw

    # Junction on the diagonal, slightly right of and below center
    jx = cx + s * 0.02
    jy = cy + s * 0.03

    traces = [
        [(x1, bot), (x1, top)],           # left vertical
        [(x1, top), (jx, jy)],            # steep diagonal segment
        [(jx, jy), (x2, bot)],            # 45-degree diagonal segment
        [(x2, bot), (x2, top)],           # right vertical
    ]
    if with_stub:
        stub = s * 0.115
        traces.append([(jx, jy), (jx - stub, jy + stub)])

    for pts in traces:
        draw.line(pts, fill=color, width=w)

    r = int(w * 0.95)
    # Nodes: cyan dot with a hot pale center (the neon "bulb" look)
    nodes = [(x1, top), (x1, bot), (x2, bot), (x2, top)]
    if with_stub:
        stub = s * 0.115
        nodes.append((jx - stub, jy + stub))
    nodes.append((jx, jy))
    for (nxp, nyp) in nodes:
        draw.ellipse([nxp - r, nyp - r, nxp + r, nyp + r], fill=color)
        rr = int(r * 0.55)
        draw.ellipse([nxp - rr, nyp - rr, nxp + rr, nyp + rr],
                     fill=(205, 242, 250, color[3]))

    # One small rectangular pad on the left vertical (SMD pad look)
    pad_w, pad_l = int(w * 1.7), int(w * 0.9)
    py = bot - int(nh * 2 * 0.55)
    draw.rectangle([x1 - pad_w / 2, py - pad_l / 2, x1 + pad_w / 2, py + pad_l / 2], fill=color)


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
