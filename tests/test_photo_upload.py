"""P291 — the room-photo multipart upload, end to end without HA.

The P270 fix (imghdr removed in 3.13) covered the *image sniff*. This suite
covers the whole POST path the studio actually uses: FormData fields, the
view's executor hop, the MAC/page validation, the stored file, the design
reference, and the authentication gate.

P291 finding: the upload view was left on HA's requires_auth=True while every
other studio endpoint moved to _nspanel_auth_ok in P281/P285/P287. A viewer
admitted by the manager's session cookie has no HA Bearer token, so the POST
died in HA's middleware before this code ever ran. The fix routes the upload
through the same gate as the rest of the studio.
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from nspanel_core.dashboard import (  # noqa: E402
    DashboardBackgroundUploadView,
    DashboardDesignView,
    DashboardEntitiesView,
    DashboardSaveView,
    DashboardSendView,
    SESSION_COOKIE,
)
from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core.dashboard_manager import DashboardService  # noqa: E402
from nspanel_core.models import GlobalSettings  # noqa: E402

MAC = "e465b849a100"
PAGE = "dash_kitchen"


def _jpeg(color=(90, 120, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return buf.getvalue()


class _FileField:
    def __init__(self, data: bytes, filename: str):
        self.file = io.BytesIO(data)
        self.filename = filename


class _UploadRequest:
    """The aiohttp surface the view consumes (post + headers + query)."""

    def __init__(self, fields: dict, cookie: str = ""):
        self._fields = fields
        self.headers = {"Cookie": cookie}
        self.query = {}

    async def post(self):
        return self._fields


def _fields(**overrides):
    f = {"panel": MAC, "page": PAGE, "file": _FileField(_jpeg(), "photo.jpg")}
    f.update(overrides)
    return f


class _Loop:
    """Captures tasks scheduled by store_background (no real loop needed)."""

    def __init__(self):
        self.tasks = []

    def create_task(self, coro):
        self.tasks.append(coro)
        coro.close()  # the test only asserts the save was scheduled
        return coro


def _service(tmp_path, *, with_design=True):
    """A real DashboardService over a temp dir, with Store neutralised."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *p: str(tmp_path.joinpath(*p))
    hass.loop = _Loop()
    # add_job takes a coroutine; close it so the fake doesn't leak a warning
    hass.add_job.side_effect = lambda coro: coro.close()

    class _Store:
        def __init__(self, *a):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            self.saved = data

    import nspanel_core.dashboard_manager as dm

    original = dm.Store
    dm.Store = _Store
    try:
        svc = DashboardService(hass, MagicMock())
    finally:
        dm.Store = original
    if with_design:
        svc._designs[MAC] = dd.PanelDesign(
            mac=MAC,
            pages=[dd.DashPage(name=PAGE, title="Kitchen")],
        )
    return svc


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mgr(svc, *, with_session=False):
    mgr = MagicMock()
    mgr.dash = svc
    mgr.config.settings = GlobalSettings()
    if with_session:
        mgr.config.settings.nspanel_sessions = {"sess": 9e18}
    mgr.hass = MagicMock()
    # the view's executor hop: the job is a plain sync function, run it inline
    async def _exec(fn, *a):
        return fn(*a)

    mgr.hass.async_add_executor_job = _exec
    return mgr


# ------------------------------------------------------------- the view

def test_upload_view_stores_a_valid_multipart_photo(tmp_path):
    svc = _service(tmp_path)
    mgr = _mgr(svc, with_session=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(
            DashboardBackgroundUploadView().post(
                _UploadRequest(_fields(), cookie=f"{SESSION_COOKIE}=sess")
            )
        )
    assert resp.status == 200
    body = resp.text  # json_response body -> str
    assert '"ok": true' in body or '"ok":true' in body
    assert svc.design(MAC).pages[0].background_image.startswith("orig_")
    assert (tmp_path / "nspanel_core_dashboards" /
            svc.design(MAC).pages[0].background_image).exists()
    # P291: the save is marshalled thread-safely, not via loop.create_task
    svc.hass.add_job.assert_called_once()


def test_upload_view_rejects_a_non_image(tmp_path):
    svc = _service(tmp_path)
    mgr = _mgr(svc, with_session=True)
    bad = _FileField(b"not an image", "x.jpg")
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(
            DashboardBackgroundUploadView().post(
                _UploadRequest(_fields(file=bad), cookie=f"{SESSION_COOKIE}=sess")
            )
        )
    assert resp.status == 400
    assert "not a readable image" in resp.text


def test_upload_view_rejects_missing_fields(tmp_path):
    svc = _service(tmp_path)
    mgr = _mgr(svc, with_session=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(
            DashboardBackgroundUploadView().post(
                _UploadRequest({"panel": MAC, "page": PAGE},
                               cookie=f"{SESSION_COOKIE}=sess")
            )
        )
    assert resp.status == 400
    assert "required" in resp.text


def test_upload_view_admits_the_manager_session_cookie(tmp_path):
    """P291: the studio's session cookie must satisfy the upload gate.

    The studio is reached by a plain navbar link (no ?ha_token=) and on a
    remote browser there is no Bearer token in localStorage. P287's 24h
    httponly session cookie is the credential — the upload must honour it.
    """
    svc = _service(tmp_path)
    mgr = _mgr(svc, with_session=True)
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(
            DashboardBackgroundUploadView().post(
                _UploadRequest(_fields(), cookie=f"{SESSION_COOKIE}=sess")
            )
        )
    assert resp.status == 200, resp.text


def test_upload_view_denies_an_unauthenticated_post(tmp_path):
    svc = _service(tmp_path)
    mgr = _mgr(svc)  # no session, no HA token
    mgr.hass.auth = MagicMock()
    mgr.hass.auth.async_validate_token = None  # no token store on the fake
    with patch("nspanel_core.dashboard._manager", return_value=mgr):
        resp = _run(DashboardBackgroundUploadView().post(_UploadRequest(_fields())))
    assert resp.status == 401


# --------------------------------------------------------- the store

@pytest.mark.parametrize(
    "view,method",
    [
        (DashboardDesignView, "get"),
        (DashboardSaveView, "post"),
        (DashboardSendView, "post"),
        (DashboardEntitiesView, "get"),
        (DashboardBackgroundUploadView, "post"),
    ],
)
def test_every_studio_endpoint_uses_the_session_gate(tmp_path, view, method):
    """P291: no studio endpoint may fall back to Bearer-only HA auth.

    Every one admits the manager session cookie and rejects a stranger —
    the same gate the studio's GET pages have used since P281/P287.
    """
    svc = _service(tmp_path)
    handler = getattr(view(), method)

    class _BareRequest:
        headers = {}
        query = {}

        async def post(self):
            return _fields()

        async def json(self):
            return {"mac": MAC, "design": {"mac": MAC, "pages": [], "items": []}}

    stranger = _mgr(svc)  # no cookie, no token
    with patch("nspanel_core.dashboard._manager", return_value=stranger):
        resp = _run(handler(_BareRequest()))
    assert resp.status == 401, f"{view.__name__} let a stranger through"

    member = _mgr(svc, with_session=True)
    member.hass.states = MagicMock()
    member.hass.states.async_all.return_value = []

    class _MemberRequest(_BareRequest):
        headers = {"Cookie": f"{SESSION_COOKIE}=sess"}

    with patch("nspanel_core.dashboard._manager", return_value=member):
        resp = _run(handler(_MemberRequest()))
    assert resp.status != 401, f"{view.__name__} rejected its own session"


def test_store_background_rejects_a_bad_mac_and_a_traversal_page(tmp_path):
    svc = _service(tmp_path)
    assert svc.store_background("E4:65:B8:49:A1:00", PAGE, _jpeg(), "x.jpg")["error"]
    assert svc.store_background(MAC, "../../etc/passwd", _jpeg(), "x.jpg")["error"]
    assert not list((tmp_path / "nspanel_core_dashboards").glob("orig_*"))


def test_store_background_auto_creates_an_unknown_page(tmp_path):
    svc = _service(tmp_path)
    result = svc.store_background(MAC, "dash_new", _jpeg(), "x.jpg")
    assert result["ok"]
    assert any(p.name == "dash_new" for p in svc.design(MAC).pages)
