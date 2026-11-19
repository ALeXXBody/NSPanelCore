"""P298 — the reusable photo gallery behind the Dashboard studio.

The old upload path stored exactly one file per page
(orig_<mac>_<page>.jpg), so a second photo silently replaced the first and
there was no way to choose between pictures. The gallery stores independent,
path-safe files and exposes list / upload / serve views.
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
from nspanel_core import dashboard as dash  # noqa: E402

MAC = "aa11bb22cc33"


class _Config:
    def path(self, *parts):
        return "/tmp/opencode/fake-config"


class FakeHass:
    def __init__(self):
        self.config = _Config()
        self.add_job = MagicMock()


def _svc():
    # Storage is irrelevant here — only the photo methods are exercised, so
    # keep HA's Store out of the fake hass.
    with patch("nspanel_core.dashboard_manager.Store", return_value=MagicMock()):
        return DashboardService(FakeHass(), MagicMock())


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(buf, format="PNG")
    return buf.getvalue()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# -- the service ----------------------------------------------------------

def test_gallery_stores_several_unique_photos_and_lists_them(tmp_path):
    svc = _svc()
    with patch("nspanel_core.dashboard_manager._dash_dir", return_value=str(tmp_path)):
        a = svc.store_gallery_photo(MAC, _png((255, 0, 0)), "red.png")
        b = svc.store_gallery_photo(MAC, _png((0, 255, 0)), "green.png")
        listed = svc.gallery_photos(MAC)
    assert a.get("ok") and b.get("ok")
    assert a["name"] != b["name"]                 # no overwrite
    for item in (a, b):
        assert svc._GALLERY_RE.match(item["name"])
        assert dd.DashPage(name="dash_x", title="X",
                           background_image=item["name"])  # accepted by model
        dd.DashPage(name="dash_x", title="X",
                    background_image=item["name"]).validate()
    assert {p["name"] for p in listed} == {a["name"], b["name"]}
    assert all(os.path.isfile(tmp_path / p["name"]) for p in listed)


def test_gallery_rejects_bad_panel_and_non_images(tmp_path):
    svc = _svc()
    with patch("nspanel_core.dashboard_manager._dash_dir", return_value=str(tmp_path)):
        assert "error" in svc.store_gallery_photo("../escape", _png((1, 2, 3)))
        assert "error" in svc.store_gallery_photo(MAC, b"not an image")
        assert svc.gallery_photos("../escape") == []
    assert list(tmp_path.iterdir()) == []


def test_gallery_photo_can_back_a_dashboard_page(tmp_path):
    svc = _svc()
    with patch("nspanel_core.dashboard_manager._dash_dir", return_value=str(tmp_path)):
        photo = svc.store_gallery_photo(MAC, _png((30, 60, 90)), "wall.png")
    design = dd.PanelDesign(mac=MAC, pages=[
        dd.DashPage(name="dash_kitchen", title="Kitchen",
                    background_image=photo["name"])
    ])
    design.validate()  # the gallery name satisfies the design's image contract
    assert (tmp_path / photo["name"]).is_file()


# -- the views ------------------------------------------------------------

class _Query(dict):
    def get(self, key, default=""):
        return super().get(key, default)


class _Request:
    def __init__(self, query=None, headers=None):
        self.query = _Query(query or {})
        self.headers = headers or {}


def test_gallery_list_view_uses_the_studio_gate(tmp_path):
    manager = MagicMock()
    manager.dash = _svc()
    with patch("nspanel_core.dashboard_manager._dash_dir", return_value=str(tmp_path)), \
         patch("nspanel_core.dashboard._manager", return_value=manager), \
         patch("nspanel_core.dashboard._nspanel_auth_ok", return_value=False):
        resp = _run(dash.DashboardGalleryView().get(
            _Request({"panel": MAC})))
        assert resp.status == 401
    stored = manager.dash.store_gallery_photo(MAC, _png((9, 9, 9)))
    with patch("nspanel_core.dashboard._manager", return_value=manager), \
         patch("nspanel_core.dashboard._nspanel_auth_ok", return_value=True), \
         patch.object(manager.dash, "gallery_photos", return_value=[
             {"name": stored["name"]}]):
        resp = _run(dash.DashboardGalleryView().get(
            _Request({"panel": MAC})))
    assert resp.status == 200
    assert __import__("json").loads(resp.text)["photos"] == [
        {"name": stored["name"]}]


def test_gallery_image_view_refuses_path_traversal():
    manager = MagicMock()
    manager.dash = _svc()
    manager.dash.origins_dir = MagicMock(return_value="/tmp")
    with patch("nspanel_core.dashboard._manager", return_value=manager), \
         patch("nspanel_core.dashboard._nspanel_auth_ok", return_value=True):
        for photo in ("../../etc/passwd", f"gal_{MAC}_x.jpg",
                      f"gal_aaaaaaaaaaaaaaaaaaaaaaaa.jpg"):
            resp = _run(dash.DashboardGalleryImageView().get(
                _Request({"panel": MAC, "photo": photo})))
            assert resp.status == 404
