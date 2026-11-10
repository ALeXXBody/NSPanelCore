#!/usr/bin/env python3
"""
Builds all NSPanel Core brand assets from the original reference artwork
(branding/uploads/image_*.jpg — the user-supplied design).

Outputs:
  branding/nspanel-core-logo.png          1024x1024 master (upscaled from reference)
  docker/icon.png, icon128.png, icon64.png, logo.png    HA add-on icons
  docker/web-ui/public/icon-512.png, icon-192.png       web UI icons
  docker/web/nspanelmanager/web/static/favicon.png      manager favicon
  docker/web/nspanelmanager/web/static/logo.svg         manager lockup (embeds the artwork)
  branding/splash-preview-eu.png / -us.png              panel startup splash previews
  docker/HMI_files/hmi_pictures/{eu,us}/tft{1..4}/6.png regenerated
"""
from PIL import Image, ImageDraw, ImageFilter
import base64
import glob
import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_PATH = sorted(glob.glob(os.path.join(REPO, "branding", "uploads", "image_*")))[0]
OUT = os.path.join(REPO, "branding")

# Icon region in the reference (measured: cyan bbox x104-293, y45-235 + margin)
ICON_BOX = (86, 27, 312, 253)  # x0, y0, x1, y1 — includes glow falloff

PICS = os.path.join(REPO, "docker", "HMI_files", "hmi_pictures")


def load_reference():
    return Image.open(REF_PATH).convert("RGB")


def icon_crop():
    ref = load_reference()
    crop = ref.crop(ICON_BOX)
    # pad to square on the artwork's own dark bg
    side = max(crop.size)
    bg = Image.new("RGB", (side, side), (16, 20, 29))
    bg.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return bg


def save_icons():
    icon = icon_crop()
    docker_dir = os.path.join(REPO, "docker")
    icon.resize((512, 512), Image.LANCZOS).save(os.path.join(docker_dir, "icon.png"))
    icon.resize((128, 128), Image.LANCZOS).save(os.path.join(docker_dir, "icon128.png"))
    icon.resize((64, 64), Image.LANCZOS).save(os.path.join(docker_dir, "icon64.png"))
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(docker_dir, "logo.png"))
    ui_dir = os.path.join(REPO, "docker", "web-ui", "public")
    if os.path.isdir(ui_dir):
        icon.resize((512, 512), Image.LANCZOS).save(os.path.join(ui_dir, "icon-512.png"))
        icon.resize((192, 192), Image.LANCZOS).save(os.path.join(ui_dir, "icon-192.png"))
    static_dir = os.path.join(REPO, "docker", "web", "nspanelmanager", "web", "static")
    if os.path.isdir(static_dir):
        icon.resize((128, 128), Image.LANCZOS).save(os.path.join(static_dir, "favicon.png"))

    # logo.svg with the exact artwork embedded as data URI
    buf = io.BytesIO()
    icon.resize((256, 256), Image.LANCZOS).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 256 256" width="128" height="128">'
        f'<image width="256" height="256" xlink:href="data:image/png;base64,{b64}"/></svg>'
    )
    with open(os.path.join(static_dir, "logo.svg"), "w") as f:
        f.write(svg)
    for p in [
        os.path.join(REPO, "docker", "web", "nspanelmanager", "web", "react-components", "public", "favicon.svg"),
        os.path.join(REPO, "docker", "web", "nspanelmanager", "web", "react-components", "dist", "favicon.svg"),
    ]:
        try:
            with open(p, "w") as f:
                f.write(svg)
        except OSError:
            pass


def splash(square_size, w, h):
    """Backdrop = blurred stretched reference; sharp lockup centered, feathered edges."""
    ref = load_reference()
    # ambient backdrop
    backdrop = ref.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    # darken it so the lockup pops
    backdrop = Image.eval(backdrop, lambda v: int(v * 0.55))

    lockup = ref.resize((square_size, square_size), Image.LANCZOS)

    # feathered rounded-rect mask for the paste
    mask = Image.new("L", (square_size, square_size), 0)
    md = ImageDraw.Draw(mask)
    m = int(square_size * 0.02)
    md.rounded_rectangle([m, m, square_size - m, square_size - m],
                         radius=int(square_size * 0.1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(square_size * 0.012))

    canvas = backdrop.convert("RGB")
    x = (w - square_size) // 2
    y = (h - square_size) // 2
    canvas.paste(lockup, (x, y), mask)
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    save_icons()

    # master logo: reference upscaled
    load_reference().resize((1024, 1024), Image.LANCZOS).save(
        os.path.join(OUT, "nspanel-core-logo.png"))

    splash_eu = splash(296, 455, 320)
    splash_eu.save(os.path.join(OUT, "splash-preview-eu.png"))
    splash_us = splash(272, 320, 455)
    splash_us.save(os.path.join(OUT, "splash-preview-us.png"))

    for variant, sp in (("eu", splash_eu), ("us", splash_us)):
        for t in range(1, 5):
            sp.save(os.path.join(PICS, variant, f"tft{t}", "6.png"))
    print("assets built from reference artwork")


if __name__ == "__main__":
    main()
