#!/usr/bin/env python3
"""
NSPanel Core brand asset generator.

Generates the master logo (neon circuit-N in a rounded square + wordmark +
'SMART WALL OS' tagline) and all derived sizes:
  branding/nspanel-core-logo.png        1024x1024 master
  branding/assets/icon.png / icon128.png / icon64.png / logo.png
  branding/assets/web-ui icons (icon-512.png, icon-192.png)
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


COMFORTAA = os.path.join(BRAND_DIR, "fonts", "Comfortaa.ttf")


def tube_font(size):
    """Comfortaa Bold — rounded, tube-like letterforms (resembles the user's
    neon-tube artwork lettering)."""
    f = ImageFont.truetype(COMFORTAA, size)
    try:
        f.set_variation_by_axes([700])
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


def draw_circuit_n(draw, cx, cy, s, color, trace_ratio=0.075):
    """The letter C — Comfortaa Bold (rounded tube look like the artwork),
    same size and stroke treatment as the previous N. Flat, no decoration."""
    f = tube_font(int(s * 0.80))
    sw = max(2, int(s * 0.022))  # extra thickness
    bbox = draw.textbbox((0, 0), "C", font=f, stroke_width=sw)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = cx - w / 2 - bbox[0]
    y = cy - h / 2 - bbox[1]
    draw.text((x, y), "C", font=f, fill=color, stroke_width=sw, stroke_fill=color)


def _compose_with_glow(base, glow, px):
    """Flat style: no glow passes — just the base layer, crisp."""
    return base, ImageDraw.Draw(base)


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

    return img.resize((size, size), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=2))


def make_icon_only(size=512):
    """App icon: rounded dark panel + neon icon, no text."""
    S = 4
    px = size * S
    base, glow = _icon_layers(px, px / 2, px / 2, px * 0.70)
    img, d = _compose_with_glow(base, glow, px)
    icon_cx, icon_cy, icon_size = px / 2, px / 2, px * 0.62
    rounded_rect(d, icon_cx, icon_cy, icon_size, 0.18, 0.028, CYAN)
    draw_circuit_n(d, icon_cx, icon_cy, icon_size, CYAN)
    return img.resize((size, size), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=2))


def _icon_svg_data(size):
    """PNG bytes of the approved icon, base64-encoded for SVG embedding."""
    import base64
    import io
    buf = io.BytesIO()
    make_icon_only(size).convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _write_icon_svg(path, size=512):
    """SVG wrapping the approved raster icon (exact approved look)."""
    data = _icon_svg_data(size)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {size} {size}">'
        f'<image href="data:image/png;base64,{data}" '
        f'xlink:href="data:image/png;base64,{data}" '
        f'width="{size}" height="{size}"/></svg>\n'
    )
    with open(path, "w") as f:
        f.write(svg)


def main():
    os.makedirs(BRAND_DIR, exist_ok=True)
    logo = make_logo(1024)
    logo.convert("RGB").save(os.path.join(BRAND_DIR, "nspanel-core-logo.png"))

    docker_dir = os.path.join(BRAND_DIR, "assets")
    os.makedirs(docker_dir, exist_ok=True)
    make_icon_only(512).convert("RGB").save(os.path.join(docker_dir, "icon.png"))
    make_icon_only(128).convert("RGB").save(os.path.join(docker_dir, "icon128.png"))
    make_icon_only(64).convert("RGB").save(os.path.join(docker_dir, "icon64.png"))
    make_icon_only(256).convert("RGB").save(os.path.join(docker_dir, "logo.png"))

    ui_dir = os.path.join(BRAND_DIR, "assets", "web-ui")
    os.makedirs(ui_dir, exist_ok=True)
    make_icon_only(512).convert("RGB").save(os.path.join(ui_dir, "icon-512.png"))
    make_icon_only(192).convert("RGB").save(os.path.join(ui_dir, "icon-192.png"))
    _write_icon_svg(os.path.join(ui_dir, "favicon.svg"), 512)

    # Django web app static assets (header logo, favicon, icon)
    dj_static = os.path.join(BRAND_DIR, "assets", "manager-static")
    os.makedirs(dj_static, exist_ok=True)
    if True:
        make_icon_only(128).convert("RGB").save(os.path.join(dj_static, "favicon.png"))
        _write_icon_svg(os.path.join(dj_static, "logo.svg"), 512)
        _write_icon_svg(os.path.join(dj_static, "icon.svg"), 512)
    print("brand assets written")


if __name__ == "__main__":
    main()
