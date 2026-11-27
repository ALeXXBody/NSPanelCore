"""P367 (user: "AGAIN.... the panel has a black background and unresponsive
touchscreen"). The root cause: _pushed_map was (a) memory-only and (b) POPPED
on delivery completion - so after every successful send the register's
auto-TFT evaluation forgot what the glass carries, fell through to the STOCK
md5 comparison, mismatched, and triggered the stock flash over the design.
The two kept fighting until the display's flash wore out: black glass,
unresponsive touch, every recurrence.

The contract now:
  1. A panel with a design NEVER falls through to the stock comparison.
  2. An empty pushed_map falls back to the stored dashboard TFT's md5.
  3. An empty/unknown reported md5 with a design on the books: leave the
     glass alone (never the stock).
  4. The reported STOCK md5 with a design: re-deliver the DASHBOARD.
  5. pushed_map survives a restart (persisted in the store).
  6. A completed delivery KEEPS the map (no pop)."""
import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import custom_components.nspanel_core.manager as M  # noqa: E402
from custom_components.nspanel_core.models import PanelConfig  # noqa: E402

STOCK_MD5 = "b2b6a2e3e53ab56405d2202d51c98a29"


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _design_dash(tmp, mac, pushed=None):
    """A MagicMock dash whose panel really has a design + a stored TFT."""
    from unittest.mock import MagicMock
    dash = MagicMock()
    dash.has_design = MagicMock(return_value=True)
    tft = os.path.join(tmp, f"{mac}.tft")
    payload = b"DESIGN-TFT-BYTES" * 1024
    with open(tft, "wb") as f:
        f.write(payload)
    dash.stored_tft_path = MagicMock(return_value=tft)
    dash._pushed_map = dict(pushed or {})
    dash.rearm_serving = MagicMock(return_value={"ok": True})
    return dash, hashlib.md5(payload).hexdigest()


def _mgr(tmp, mac, dash):
    from unittest.mock import MagicMock
    mgr = MagicMock()
    mgr.config.settings.auto_tft_updates = True
    mgr.ota_md5 = MagicMock(side_effect=lambda kind, name: {
        ("tft", "gui.tft"): STOCK_MD5,
    }.get((kind, name), ""))
    mgr._ota_md5 = {"tft/gui.tft": "x"}
    mgr.dash = dash
    mgr._last_telemetry = {mac: {"warnings": []}}
    published = []

    async def _publish(topic, payload, retain=False):
        published.append(payload)

    mgr._publish = _publish
    return mgr, published


MAC = "e465b849a100"
PANEL = None


def _panel():
    return PanelConfig(id=7, mac=MAC, name="KitchenPanel", accepted=True)


def test_design_panel_with_empty_map_never_gets_the_stock(tmp_path):
    """THE AGAIN: restart wiped the map, the panel reports the design md5.
    The old code skipped the whole dashboard branch and flashed the stock."""
    dash, design_md5 = _design_dash(str(tmp_path), MAC, pushed={})
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": design_md5}))
    assert not any('"tft_update"' in p for p in published), published


def test_design_panel_falls_back_to_the_stored_tft_md5(tmp_path):
    """No map at all -> the stored dashboard TFT's md5 is the expectation."""
    dash, design_md5 = _design_dash(str(tmp_path), MAC, pushed={})
    dash.stored_tft_path = MagicMock(return_value=os.path.join(
        str(tmp_path), f"{MAC}.tft"))
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": design_md5}))
    assert not any('"tft_update"' in p for p in published), published


def test_design_panel_with_stock_md5_gets_the_dashboard_redelivered(tmp_path):
    """Wiped by a stock push -> re-deliver the DASHBOARD, never the stock."""
    dash, _ = _design_dash(str(tmp_path), MAC, pushed={})
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": STOCK_MD5}))
    assert any('"tft_update"' in p for p in published), published
    dash.rearm_serving.assert_called_once_with(MAC)


def test_design_panel_with_empty_report_is_left_alone(tmp_path):
    """An empty reported md5 with a design on the books used to fall
    through and trigger the stock flash. Never again."""
    dash, _ = _design_dash(str(tmp_path), MAC, pushed={})
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": ""}))
    assert not any('"tft_update"' in p for p in published), published


def test_design_panel_with_unknown_md5_is_left_alone(tmp_path):
    dash, design_md5 = _design_dash(str(tmp_path), MAC, pushed={})
    dash._pushed_map[MAC] = design_md5
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": "deadbeef" * 4}))
    assert not any('"tft_update"' in p for p in published), published


def test_current_dashboard_is_left_alone(tmp_path):
    dash, design_md5 = _design_dash(str(tmp_path), MAC, pushed={})
    dash._pushed_map[MAC] = design_md5
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": design_md5}))
    assert not any('"tft_update"' in p for p in published), published


def test_stock_panel_without_design_still_gets_the_stock_update(tmp_path):
    """No design on the books -> the stock auto-update behavior is kept."""
    from unittest.mock import MagicMock
    dash = MagicMock()
    dash.has_design = MagicMock(return_value=False)
    mgr, published = _mgr(str(tmp_path), MAC, dash)
    _run(M.NSPanelCoreManager._maybe_trigger_firmware_ota(
        mgr, _panel(), {"md5_tft_file": ""}))
    assert any('"tft_update"' in p for p in published), published


# ---- the persistence + the no-pop (the DashboardService side) ------------

def _fake_hass():
    import tempfile

    class _Config:
        def path(self, *parts):
            return tempfile.mkdtemp(prefix="nspdash-p367")

    class H:
        def __init__(self):
            self.config = _Config()
            self._tasks = []

        def async_create_task(self, coro):
            # real-HA semantics: schedule on the running loop if there is
            # one, else run inline
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop:
                loop.create_task(coro)
            else:
                asyncio.new_event_loop().run_until_complete(coro)

    return H()


class _FakeStore:
    def __init__(self, hass, v, k):
        self.saved = None

    async def async_load(self):
        return getattr(self, "_data", None)

    async def async_save(self, d):
        self.saved = d


def _service(store_data=None):
    import nspanel_core.dashboard_manager as dm
    from unittest.mock import MagicMock

    orig = dm.Store
    dm.Store = _FakeStore
    try:
        svc = dm.DashboardService(_fake_hass(), MagicMock())
    finally:
        dm.Store = orig
    if store_data is not None:
        svc._store._data = store_data
    return svc


def test_pushed_map_survives_a_restart():
    """(a) the map is persisted and reloaded - the AGAIN trigger was the
    restart wiping it."""
    import anyio

    async def go():
        svc = _service()
        svc._pushed_map[MAC] = "abc123"
        svc._store.saved = None
        await svc._save()
        blob = svc._store.saved
        assert blob["pushed_map"] == {MAC: "abc123"}, blob.keys()
        # the reload path
        svc2 = _service(store_data=blob)
        await svc2.async_load()
        assert svc2._pushed_map == {MAC: "abc123"}

    anyio.run(go)


def test_completed_delivery_keeps_the_pushed_map():
    """(b) the completion KEPT the map - the old pop emptied the books the
    moment a delivery completed, so the next register forgot the glass."""
    import anyio

    async def go():
        svc = _service()
        svc._pushed_map[MAC] = "expectedmd5"
        svc._serving = {"mac": MAC, "md5": "expectedmd5", "pre_seq": 0}
        out = svc.on_tft_md5(MAC, "expectedmd5", seq=5)
        await asyncio.sleep(0)  # drain the scheduled save
        assert out.get("delivered") is True
        assert svc._serving is None
        # THE CONTRACT: the map survives the completion
        assert svc._pushed_map.get(MAC) == "expectedmd5"

    anyio.run(go)
