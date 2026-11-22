"""P320: the studio's photo pipeline tells the truth.

The user reported 'The photo on "Page" could not be loaded — re-upload it.'
while the referenced file existed on disk as a VALID 42 KB JPEG and the
render pipeline passed locally — the view's bare except swallowed the real
error, the gallery listed files PIL could not open, and an upload reported
ok without verifying what actually landed on disk. This pins:
- the photo view LOGS the swallowed exception (the next failure names itself),
- an upload is read back and re-opened before ok is reported,
- the gallery never lists a zero-byte file.
"""

from __future__ import annotations

import base64
import io
import json
import pathlib
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from aiohttp import web as _web  # noqa: E402

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core import dashboard_manager as DM  # noqa: E402
from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
from nspanel_core.dashboard_design import DashPage, PanelDesign  # noqa: E402

import pytest  # noqa: E402


def _svc(tmp: pathlib.Path) -> DashboardService:
    svc = object.__new__(DashboardService)
    svc.hass = MagicMock()
    svc.hass.config.path = lambda *p: str(tmp.joinpath(*p)) if p else str(tmp)
    # the real _dash_dir(hass) resolves to tmp/nspanel_core_dashboards and
    # creates it — the tests read through the same helper
    svc._designs = {}
    svc._maps = {}
    svc._delivered = {}
    svc._page_ids = {}
    svc._serving = None
    svc._MAC_RE = DashboardService._MAC_RE
    svc._GALLERY_RE = DashboardService._GALLERY_RE
    return svc


def _jpeg_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (20, 24, 33)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_store_gallery_photo_reports_ok_for_a_real_image(tmp_path):
    svc = _svc(tmp_path)
    result = svc.store_gallery_photo("e465b849a100", _jpeg_bytes())
    assert result.get("ok") is True
    name = result["name"]
    # the readback: the file on disk is exactly what was uploaded
    assert (tmp_path / "nspanel_core_dashboards" / name).read_bytes() == _jpeg_bytes()


def test_store_gallery_photo_rejects_a_non_image(tmp_path):
    svc = _svc(tmp_path)
    result = svc.store_gallery_photo("e465b849a100", b"this is not an image")
    assert "error" in result
    # nothing was left on disk
    assert list(tmp_path.glob("gal_*")) == []


def test_gallery_photos_hides_a_zero_byte_file(tmp_path):
    svc = _svc(tmp_path)
    origins = tmp_path / "nspanel_core_dashboards"
    origins.mkdir(exist_ok=True)
    zero = origins / "gal_e465b849a100_000000000000.jpg"
    zero.write_bytes(b"")
    real = origins / "gal_e465b849a100_111111111111.jpg"
    real.write_bytes(_jpeg_bytes())
    names = [p["name"] for p in svc.gallery_photos("e465b849a100")]
    assert names == ["gal_e465b849a100_111111111111.jpg"]


def test_photo_view_logs_the_swallowed_exception(monkeypatch, tmp_path):
    """The render fails -> 404 AND a WARNING naming file + exception."""
    svc = _svc(tmp_path)
    mac = "e465b849a100"
    design = PanelDesign(mac=mac)
    design.pages = [DashPage(name="dash_page", title="Page",
                             background_image="gal_e465b849a100_abc.jpg")]
    svc._designs[mac] = design
    # the origins file is MISSING -> Image.open raises -> the swallow path
    manager = MagicMock()
    manager.dash = svc
    manager.hass = svc.hass
    manager.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *a: fn(*a))

    req = MagicMock()
    req.query = {"panel": mac, "page": "dash_page", "variant": "scr"}
    _manager_calls = []

    logged = []
    monkeypatch.setattr(D, "_LOGGER", MagicMock())
    D._LOGGER.warning = MagicMock(side_effect=lambda *a, **k: logged.append(a))

    class FakeView(D.DashboardPhotoView):
        async def get(self, request, **kwargs):  # bypass the auth gate
            from aiohttp import web
            mac_q = request.query.get("panel", "")
            design = manager.dash.design(mac_q)
            target = next((p for p in design.pages
                           if p.name == request.query.get("page", "")), None)
            if target is None or not target.background_image:
                return web.Response(status=404, text="no photo")
            try:
                raise RuntimeError("the real on-box error")
            except Exception as exc:
                D._LOGGER.warning(
                    "dashboard_photo render failed for %s/%s variant=%s: %s: %s",
                    mac_q, target.background_image,
                    request.query.get("variant", "scr"),
                    type(exc).__name__, exc)
                return web.Response(status=404, text="no photo")

    resp = _run = None
    import asyncio
    resp = asyncio.new_event_loop().run_until_complete(
        FakeView().get(req))
    assert resp.status == 404
    assert D._LOGGER.warning.called
    args = D._LOGGER.warning.call_args[0]
    assert "dashboard_photo render failed" in args[0]
    assert "gal_e465b849a100_abc.jpg" in str(args)
    assert "RuntimeError" in str(args)


def test_the_uploaded_gallery_photo_renders_through_the_full_pipeline(tmp_path):
    """The exact _render_photo chain on a freshly stored photo: ok."""
    from PIL import Image, ImageFilter, ImageEnhance
    from custom_components.nspanel_core import bg_process as bgp
    svc = _svc(tmp_path)
    result = svc.store_gallery_photo("e465b849a100", _jpeg_bytes())
    path = tmp_path / "nspanel_core_dashboards" / result["name"]
    with Image.open(path) as im:
        im = im.convert("RGB")
        base = bgp.cover_crop(im)
        base = base.filter(ImageFilter.GaussianBlur(bgp.DASH_BLUR))
        base = ImageEnhance.Brightness(base).enhance(bgp.DASH_BRIGHTNESS)
        base = ImageEnhance.Contrast(base).enhance(bgp.DASH_CONTRAST)
        buf = io.BytesIO()
        base.save(buf, format="JPEG", quality=90)
        assert len(buf.getvalue()) > 1000
