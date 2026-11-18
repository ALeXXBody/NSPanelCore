"""NSPanel Core — room background processing (pure, host-testable).

The user uploads a photo per room; the integration processes it to the
panel's standards (P255, the user's design):
  - the SCREENSAVER variant: cover-cropped to 480x320, full brightness —
    the clock sits on it (the clock texts use photo crops as their
    backgrounds, so the digits render seamlessly over the photo);
  - the DASHBOARD variant: the same cover-crop, softly blurred and
    darkened — the widget tiles read over it with strong contrast.
"""

from __future__ import annotations

import os

from PIL import Image, ImageEnhance, ImageFilter

PANEL_W, PANEL_H = 480, 320
DASH_BRIGHTNESS = 0.42   # the dashboard variant's dimming
DASH_BLUR = 2            # px of soft blur at panel scale
DASH_CONTRAST = 0.9


def cover_crop(img: Image.Image, w: int = PANEL_W, h: int = PANEL_H) -> Image.Image:
    """Scale to cover the target and center-crop — no letterboxing."""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = max(w, round(sw * scale)), max(h, round(sh * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def process_background(source_path: str, out_dir: str, stem: str) -> tuple[str, str]:
    """The user's photo -> (screensaver_path, dashboard_path).

    Both written into |out_dir| as <stem>_scr.jpg / <stem>_dash.jpg.
    """
    with Image.open(source_path) as im:
        im = im.convert("RGB")
        base = cover_crop(im)

        scr = os.path.join(out_dir, f"{stem}_scr.jpg")
        base.save(scr, quality=92)

        dash = base.filter(ImageFilter.GaussianBlur(DASH_BLUR))
        dash = ImageEnhance.Brightness(dash).enhance(DASH_BRIGHTNESS)
        dash = ImageEnhance.Contrast(dash).enhance(DASH_CONTRAST)
        dash_path = os.path.join(out_dir, f"{stem}_dash.jpg")
        dash.save(dash_path, quality=92)
    return scr, dash_path


def crop_rect(scr_path: str, rect: tuple[int, int, int, int]) -> Image.Image:
    """The crop behind one clock text component (sta=2 backgrounds)."""
    with Image.open(scr_path) as im:
        x, y, w, h = rect
        return im.crop((x, y, x + w, y + h))
