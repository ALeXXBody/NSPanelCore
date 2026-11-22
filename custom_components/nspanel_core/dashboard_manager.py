"""NSPanel Core — dashboard service (manager side of the P234 design).

The manager owns everything the panel stores nothing:
  - the designs (one PanelDesign per panel, in HA storage)
  - the generated per-panel TFT + the component map (config dir)
  - touch routing (panel publishes component presses → entity services)
  - state mirroring (HA state changes → sanitized dash commands)
  - send-to-panel (generate → nxwright compile → serve → trigger reflash)
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.storage import Store

from . import const
from . import dashboard_design as dd
from . import hmi_generate as hg

_LOGGER = logging.getLogger(__name__)

STORE_KEY = "nspanel_core_dashboard_designs"
STORE_VERSION = 1
KIND = os.path.join(os.path.dirname(__file__), "hmi_kit")

# widgets that toggle (dual-state buttons carry on/off state as .val)
_TOGGLE_WIDGETS = ("switch", "light", "rgb_light")


def _dash_dir(hass: HomeAssistant) -> str:
    d = hass.config.path("nspanel_core_dashboards")
    os.makedirs(d, exist_ok=True)
    return d


class DashboardService:
    """All manager-side dashboard logic. One per manager."""

    def __init__(self, hass: HomeAssistant, manager) -> None:
        self.hass = hass
        self.manager = manager
        self._store = Store(hass, STORE_VERSION, STORE_KEY)
        self._designs: dict[str, dd.PanelDesign] = {}
        self._maps: dict[str, dict] = {}          # mac → component map (delivered)
        self._page_ids: dict[str, list[int]] = {}  # mac → dash page ids
        self._delivered: dict[str, dd.PanelDesign] = {}  # P279: the design the DELIVERED TFT matches
        self._serving: dict | None = None          # the send-to-panel slot
        self._pushed_map: dict[str, str] = {}      # mac → tft md5 the map rode on
        self._unsub_state = None

    # -- persistence ---------------------------------------------------

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._designs = {
            mac: dd.PanelDesign.from_dict(d) for mac, d in data.get("designs", {}).items()
        }
        self._maps = data.get("maps", {})
        self._page_ids = {m: v for m, v in data.get("page_ids", {}).items()}

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "designs": {m: d.to_dict() for m, d in self._designs.items()},
                "maps": self._maps,
                "page_ids": self._page_ids,
            }
        )

    # -- design access ---------------------------------------------------

    def design(self, mac: str) -> dd.PanelDesign:
        return self._designs.get(mac) or dd.PanelDesign(mac=mac)

    def has_design(self, mac: str) -> bool:
        d = self._designs.get(mac)
        return bool(d and (d.pages or d.items))

    async def async_save_design(self, design: dd.PanelDesign) -> None:
        design.validate()
        self._designs[design.mac] = design
        # the design changed → the delivered map/TFT are stale until sent
        self._page_ids.pop(design.mac, None)
        await self._save()

    def component_map(self, mac: str) -> dict:
        return self._maps.get(mac, {})

    # -- generate + compile ----------------------------------------------

    def _generate_and_compile(self, design: dd.PanelDesign) -> tuple[str, str, dict, list]:
        """Blocking: design → TFT path + md5 + component map + page ids."""
        with tempfile.TemporaryDirectory(prefix="nspdash") as wd:
            origins = _dash_dir(self.hass)
            cmap = hg.generate_source(design, KIND, wd, origins_dir=origins)
            tft_tmp = os.path.join(wd, "panel.tft")
            hg.compile_tft(wd, tft_tmp)
            data = open(tft_tmp, "rb").read()
            out = os.path.join(_dash_dir(self.hass), f"{design.mac}.tft")
            with open(out, "wb") as f:
                f.write(data)
            md5 = hashlib.md5(data).hexdigest()
            # keep the map + page ids beside the TFT (atomic-ish with it)
            with open(os.path.join(_dash_dir(self.hass), f"{design.mac}.map.json"), "w") as f:
                json.dump({"map": cmap, "page_ids": dd.page_ids(design), "md5": md5}, f)
            return out, md5, cmap, dd.page_ids(design)

    async def async_generate(self, design: dd.PanelDesign) -> tuple[str, str, dict, list]:
        return await self.hass.async_add_executor_job(
            self._generate_and_compile, design
        )

    # -- send to panel -----------------------------------------------------

    def tft_override(self, requesting_mac: str | None = None) -> str | None:
        """The per-panel TFT being delivered right now (serving slot).

        P279 HIGH fix: the slot is per-mac and EXPIRES — a global, never
        expiring slot served the WRONG panel's dashboard TFT to every
        other panel and wedged all future sends when the target was
        offline. Only the triggered panel's download is honored; the slot
        ages out after 10 minutes."""
        if not self._serving:
            return None
        import time as _t

        if _t.time() - self._serving.get("ts", 0) > 600:
            self._serving = None
            return None
        if requesting_mac and self._serving["mac"] != requesting_mac:
            return None  # the other panels keep their stock TFT
        if os.path.isfile(self._serving["path"]):
            return self._serving["path"]
        return None

    def serving_info(self) -> dict:
        # P312: the slot EXPIRES after 10 minutes (the download window) —
        # an expired slot must not be reported as an in-progress send, or
        # every later send is refused with "already in progress" forever
        # (the user's Send wedged after one delivery that never completed).
        if self._serving:
            import time as _t
            if _t.time() - self._serving.get("ts", 0) > 600:
                self._serving = None
        return dict(self._serving) if self._serving else {}

    def stored_tft_path(self, mac: str) -> str | None:
        """The panel's compiled dashboard TFT on disk, if any."""
        p = os.path.join(_dash_dir(self.hass), f"{mac}.tft")
        return p if os.path.isfile(p) else None

    def rearm_serving(self, mac: str) -> dict:
        """Re-arm the serving slot for a panel whose dashboard was wiped
        (the stock auto-push overwrote it) — no recompile needed."""
        design = self._designs.get(mac)
        if design is None or not (design.pages or design.items):
            return {"error": "no design"}
        path = self.stored_tft_path(mac)
        if not path:
            return {"error": "no stored dashboard TFT"}
        md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
        self._serving = {"mac": mac, "path": path, "md5": md5}
        return {"ok": True}

    async def async_send_to_panel(self, mac: str) -> dict:
        """Generate + compile + arm the serving slot + trigger the reflash."""
        design = self._designs.get(mac)
        if design is None or not (design.pages or design.items):
            return {"error": "no design saved for this panel"}
        if self._serving:
            return {"error": "a send is already in progress (panel %s)" % self._serving["mac"]}
        panel = self.manager._panel_by_mac(mac)
        if panel is None or not panel.accepted:
            return {"error": "panel not found or not accepted"}
        # P312: a panel whose display is not answering CANNOT take a TFT
        # stream — the delivery wedges it (the stall watchdog restarts it,
        # and the restart dropped the user's panel off the network). Refuse
        # with the action that fixes it instead of killing the panel.
        telemetry = self.manager._last_telemetry.get(mac, {}) or {}
        warning = " ".join(
            str(w.get("text", "")) if isinstance(w, dict) else str(w)
            for w in telemetry.get("warnings", []))
        if "no response from the display" in warning.lower():
            return {"error":
                    "the panel's display is not responding — on the panel's "
                    "web UI press Display restart (or reseat the display "
                    "ribbon), then Send again"}
        # P279 MEDIUM fix: reserve the slot BEFORE the await — two concurrent
        # sends both passed the check and both published tft_update
        self._serving = {"mac": mac, "path": "", "md5": "", "ts": 0, "reserving": True}
        try:
            path, md5, cmap, page_ids = await self.async_generate(design)
        except Exception as exc:  # noqa: BLE001
            self._serving = None
            _LOGGER.exception("dashboard generate/compile failed for %s", mac)
            return {"error": f"compile failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("dashboard generate/compile failed for %s", mac)
            return {"error": f"compile failed: {exc}"}
        import time as _t

        self._serving = {"mac": mac, "path": path, "md5": md5, "ts": _t.time()}
        self._maps[mac] = cmap
        self._page_ids[mac] = list(page_ids)
        # P279 HIGH fix: route the touches/mirroring against the design the
        # DELIVERED TFT matches — the edited design desynced the routing and
        # a press toggled the WRONG entity after a slot swap
        self._delivered[mac] = copy.deepcopy(design)
        await self._save()
        await self.manager._publish(
            self._cmd_topic(mac),
            json.dumps({"command": "tft_update"}),
        )
        _LOGGER.info("Dashboard send started for panel %s (md5 %s…)", panel.name, md5[:12])
        return {"ok": True, "md5": md5, "bytes": os.path.getsize(path)}

    @callback
    def on_tft_md5(self, mac: str, md5_tft_file: str) -> dict:
        """Completion check from a status_report: did the panel take the TFT?"""
        if not self._serving or self._serving["mac"] != mac:
            return {}
        sent = self._serving["md5"]
        info = {"expected": sent}
        if md5_tft_file == sent:
            self._serving = None
            self._pushed_map.pop(mac, None)  # re-push the map for the fresh UI
            info["delivered"] = True
            _LOGGER.info("Dashboard TFT delivered to panel %s", mac)
        return info

    @callback
    def clear_serving(self, mac: str | None = None) -> None:
        if self._serving and (mac is None or self._serving["mac"] == mac):
            self._serving = None

    # -- push config to a (freshly booted) panel ---------------------------

    async def async_push_config(self, mac: str) -> None:
        """Push dash_map + current item values to a panel running its TFT.

        P321f: the dash_map push is DISABLED — it is the crash trigger.
        Both panel crash loops (0.1.10 era and the current one) began the
        moment a Send armed this push, and the panel's MQTT task dies
        processing the post-accept commands whenever it is live; the same
        binary was stable for 400+ s in the era when the push was absent.
        The page ids stay stored; the values push below is unchanged. The
        touch routing degrades to the stock base chains until the panel
        firmware's dash_map handling is fixed (0.1.14, after the coredump
        verdict names the exact bug).
        """
        if not self.has_design(mac):
            return
        page_ids = self._page_ids.get(mac)
        if not page_ids:
            return
        # P321f: the push itself is disabled — the page ids are kept so a
        # future firmware fix can re-enable the flow without a re-Send.
        _LOGGER.warning(
            "dash_map push to %s suppressed (P321f: the push is the panel "
            "crash trigger; re-enabled with the 0.1.14 panel fix)",
            mac)
        await self.async_push_values(mac)

    async def async_push_values(self, mac: str) -> None:
        """Mirror the current HA states into the panel's items."""
        design = self._designs.get(mac)
        cmap = self._maps.get(mac)
        if design is None or not cmap:
            return
        for item in design.items:
            state = self.hass.states.get(item.entity_id)
            if state is None:
                continue
            await self._send_item_state(mac, item, state)

    @callback
    def _send_item_state(self, mac: str, item: dd.DashItem, state) -> None:
        from . import dashboard_wire as wire

        stmt = wire.item_statement(item, state)
        if stmt:
            self.hass.async_create_task(
                self.manager._publish(
                    self._cmd_topic(mac),
                    json.dumps({"command": "dash", "payload": stmt}),
                )
            )
        # P274: the light items also mirror the brightness into their
        # detail page's percent text, and the on/off into its tile
        if item.widget in ("light", "rgb_light"):
            cmap = self._maps.get(mac) or {}
            lights = dd.light_items(self._designs.get(mac) or dd.PanelDesign(mac=mac))
            idx = lights.index(item) if item in lights else -1
            if idx < 0:
                return
            page_map = cmap.get(dd.detail_name(idx)) or {}
            pct = page_map.get("pct")
            pwr = page_map.get("pwr")
            bright = state.attributes.get("brightness")
            if pct is not None:
                on = (state.state or "").lower() == "on"
                shown = "--" if not on else (
                    f"{round(int(bright) * 100 / 255)}%" if bright else "0%")
                self.hass.async_create_task(self.manager._publish(
                    self._cmd_topic(mac),
                    json.dumps({"command": "dash",
                                "payload": f'pct.txt="{dd.clean_text(shown, 8)}"'})))
            if pwr is not None:
                self.hass.async_create_task(self.manager._publish(
                    self._cmd_topic(mac),
                    json.dumps({"command": "dash",
                                "payload": f"pwr.val={1 if (state.state or '').lower() == 'on' else 0}"})))

    # -- the user's room photos -------------------------------------------

    _MAC_RE = __import__("re").compile(r"^[a-f0-9]{12}$")
    _PAGE_RE = __import__("re").compile(r"^dash_[a-z0-9_]{1,9}$")

    def store_background(self, mac: str, page: str, file_bytes: bytes,
                         filename: str) -> dict:
        """..."""
        # P279 HIGH fix: the raw mac/page built the file path — a crafted
        # page ("../..") wrote attacker files OUTSIDE the origins dir.
        if not self._MAC_RE.match(mac or ""):
            return {"error": "invalid panel"}
        if not self._PAGE_RE.match(page or ""):
            return {"error": "invalid page name"}
        """Store a room photo upload and reference it in the design.

        P255 (the user's design): the photo is kept as-is (the screensaver
        variant) and processed to the dashboard variant at generate time.
        """
        # P270: imghdr was REMOVED in Python 3.13 (the user's HA) — the
        # sniff is PIL's job now (already a dependency).
        import io
        from PIL import Image

        reject = dd.image_reject_error(file_bytes)
        if reject:
            return {"error": reject}
        ext = ".png" if Image.open(io.BytesIO(file_bytes)).format == "PNG" else ".jpg"
        origins = _dash_dir(self.hass)
        safe = f"orig_{mac}_{page}{ext}"
        with open(os.path.join(origins, safe), "wb") as f:
            f.write(file_bytes)
        design = self._designs.get(mac)
        if design is None:
            design = dd.PanelDesign(mac=mac)
            self._designs[mac] = design
        target = next((p for p in design.pages if p.name == page), None)
        if target is None:
            target = dd.DashPage(name=page, title=page)
            design.pages.append(target)
        target.background_image = safe
        try:
            design.validate()
        except dd.DesignError as exc:
            design.pages.remove(target)
            return {"error": str(exc)}
        # P291: this method runs INSIDE hass.async_add_executor_job (a worker
        # thread). loop.create_task() from a foreign thread is not thread-safe
        # — the save could be dropped or raise on HA's debug loop. add_job()
        # marshals the coroutine onto the loop via call_soon_threadsafe.
        self.hass.add_job(self._save())
        return {"ok": True, "stored": safe}

    # -- the reusable photo gallery (P298) ---------------------------------

    _GALLERY_RE = __import__("re").compile(
        r"^gal_[a-f0-9]{12}_[a-f0-9]{12}\.(jpg|png)$")

    def store_gallery_photo(self, mac: str, file_bytes: bytes,
                            filename: str = "") -> dict:
        """Keep an uploaded photo once, reusable on any page of this panel.

        The per-page store_background() above deliberately overwrites one
        orig_<mac>_<page> file. A gallery needs many pictures, so each upload
        gets its own random, path-safe name matching dashboard_design's
        _BGIMG_RE (which is the same reference a page's background_image uses).
        """
        if not self._MAC_RE.match(mac or ""):
            return {"error": "invalid panel"}
        import io
        import secrets
        from PIL import Image

        reject = dd.image_reject_error(file_bytes)
        if reject:
            return {"error": reject}
        ext = ".png" if Image.open(io.BytesIO(file_bytes)).format == "PNG" else ".jpg"
        safe = f"gal_{mac}_{secrets.token_hex(6)}{ext}"
        path = os.path.join(_dash_dir(self.hass), safe)
        with open(path, "wb") as f:
            f.write(file_bytes)
        # P320: an upload that does not survive the disk must not report ok —
        # read it back and re-open before the studio ever references it.
        try:
            with open(path, "rb") as f:
                written = f.read()
            if len(written) != len(file_bytes):
                os.remove(path)
                return {"error": "the upload did not survive the disk — try again"}
            with Image.open(io.BytesIO(written)) as im:
                im.verify()
        except Exception as exc:  # noqa: BLE001
            try:
                os.remove(path)
            except OSError:
                pass
            return {"error": f"the uploaded image failed verification: {exc}"}
        return {"ok": True, "name": safe}

    def gallery_photos(self, mac: str) -> list[dict]:
        """List this panel's stored gallery photos, newest first."""
        if not self._MAC_RE.match(mac or ""):
            return []
        origins = _dash_dir(self.hass)
        prefix = f"gal_{mac}_"
        out = []
        for name in os.listdir(origins):
            if not name.startswith(prefix) or not self._GALLERY_RE.match(name):
                continue
            path = os.path.join(origins, name)
            # P320: an empty file can never render — listing it only feeds
            # the studio a thumbnail grid that cannot load.
            try:
                if os.path.getsize(path) <= 0:
                    continue
            except OSError:
                continue
            out.append({"name": name, "modified": os.path.getmtime(path)})
        out.sort(key=lambda p: p["modified"], reverse=True)
        return [{"name": p["name"]} for p in out]

    def origins_dir(self) -> str:
        return _dash_dir(self.hass)

    # -- touch routing -----------------------------------------------------

    @callback
    def on_touch(self, mac: str, page: int, component: int, event: int) -> None:
        """Resolve a panel touch to an action. Releases only."""
        if event != 0:
            return
        # P279 HIGH fix: route against the DELIVERED design — the edited
        # one desynced from the TFT on the panel (wrong-entity presses)
        design = self._delivered.get(mac) or self._designs.get(mac)
        cmap = self._maps.get(mac)
        if design is None or not cmap:
            return
        ids = self._page_ids.get(mac) or []
        dash_pages = {p.name: i for p, i in zip(design.pages, ids[1:])} if ids else {}

        # menu page: room id 4 → hotspots navigate
        if page == dd.MENU_PAGE_ID:
            for n, p in enumerate(design.pages):
                if (cmap.get("room") or {}).get(f"m{n}") == component:
                    self._dash(mac, f"page {p.name}")
                    return
            menu_back = (cmap.get("room") or {}).get("back")
            if menu_back == component:
                self._dash(mac, "page home")
            return

        # a DETAIL page (P274): the component -> the entity's action
        detail = self._detail_context(mac, page, cmap, design)
        if detail is not None:
            item, dmap = detail
            if dmap.get("back") == component:
                self._dash(mac, "page room")
            elif dmap.get("minus") == component:
                self._light_call(item, {"brightness_step": -64})
            elif dmap.get("plus") == component:
                self._light_call(item, {"brightness_step": 64})
            else:
                for k, (cname, rgbv) in enumerate(dd.COLOR_PRESETS):
                    if dmap.get(f"c{k}") == component:
                        self._light_call(item, {"rgb_color": list(rgbv)})
                        return
                if dmap.get("pwr") == component:
                    self._run_item(item)  # the dual-state toggle
            return

        # a dash page
        page_name = next((n for n, i in dash_pages.items() if i == page), None)
        if page_name is None:
            return
        page_map = cmap.get(page_name) or {}
        if page_map.get("back") == component:
            self._dash(mac, "page room")
            return
        for item in design.items:
            if item.page != page_name:
                continue
            if page_map.get(f"b{item.slot}") == component:
                # P274: the light/RGB tiles open their DETAIL page (the
                # entity card: the on/off, the intensity, the color) —
                # the switch tiles keep the direct toggle.
                if item.widget in ("light", "rgb_light"):
                    self._open_detail(mac, item)
                else:
                    self._run_item(item)
                return

    @callback
    def _dash(self, mac: str, stmt: str) -> None:
        self.hass.async_create_task(
            self.manager._publish(
                self._cmd_topic(mac),
                json.dumps({"command": "dash", "payload": stmt}),
            )
        )

    # -- the topic identity (P279 CRITICAL): the firmware subscribes to
    # nspanel/<wifi_hostname>/command — the MAC-based topic black-holes
    # everything. Resolve the panel once, publish on ITS command topic.
    def _cmd_topic(self, mac: str) -> str:
        panel = next(
            (p for p in self.manager.config.panels
             if const.topic_safe(p.mac) == mac), None)
        if panel is None:
            return const.panel_topic(mac, "command")
        return self.manager._panel_cmd_topic(panel, "command")

    def _design_key(self, mac: str) -> str:
        """The topic segment -> the design key (the panel's real mac)."""
        panel = next(
            (p for p in self.manager.config.panels
             if const.topic_safe(p.mac) == mac), None)
        return topic_safe(panel.mac) if panel else mac

    # -- P274: the light detail pages (the entity cards on the panel) -----

    def _detail_context(self, mac: str, page: int, cmap: dict, design):
        """The (item, component map) for a light detail page, if |page| is one."""
        n_dash = len(design.pages)
        lights = dd.light_items(design)
        idx = page - (7 + n_dash)
        if idx < 0 or idx >= len(lights):
            return None
        item = lights[idx]
        return item, (cmap.get(dd.detail_name(idx)) or {})

    def _open_detail(self, mac: str, item: dd.DashItem) -> None:
        """Navigate the panel to the item's detail page (dp=<id>)."""
        design = self._designs.get(mac)
        lights = dd.light_items(design)
        idx = lights.index(item) if item in lights else -1
        if idx < 0:
            return
        page_id = (7 + len(design.pages)) + idx
        self._dash(mac, f"dp={page_id}")

    @callback
    def _light_call(self, item: dd.DashItem, data: dict) -> None:
        self.hass.async_create_task(
            self.hass.services.async_call(
                "light", "turn_on", {"entity_id": item.entity_id, **data},
                blocking=False))

    @callback
    def _run_item(self, item: dd.DashItem) -> None:
        domain, _ = item.entity_id.split(".", 1)
        if item.widget in _TOGGLE_WIDGETS and domain in ("light", "switch"):
            service = f"{domain}.toggle"
        elif item.widget == "scene":
            service = "scene.turn_on"
        else:
            return  # sensors/climates: nothing to act on yet
        self.hass.async_create_task(
            self.hass.services.async_call(domain, service.split(".", 1)[1],
                                          {"entity_id": item.entity_id}, blocking=False)
        )

    # -- HA state mirroring ------------------------------------------------

    def start_state_listener(self) -> None:
        self.stop_state_listener()  # P279 HIGH fix: no duplicate listeners
        @callback
        def _on_state(event: Event) -> None:
            entity_id = event.data["entity_id"]
            new_state = event.data.get("new_state")
            if new_state is None:
                return  # P279 MEDIUM fix: a removed entity crashed the listener
            for mac, design in self._designs.items():
                cmap = self._maps.get(mac)
                if not cmap or not self._page_ids.get(mac):
                    continue
                for item in design.items:
                    if item.entity_id != entity_id:
                        continue
                    page_map = cmap.get(item.page) or {}
                    if f"b{item.slot}" not in page_map:
                        continue
                    self._send_item_state(mac, item, new_state)

        entities = {
            i.entity_id
            for d in self._designs.values()
            for i in d.items
            if i.widget not in ("scene",)
        }
        if entities:
            from homeassistant.helpers.event import async_track_state_change_event

            self._unsub_state = async_track_state_change_event(
                self.hass, list(entities), _on_state
            )

    def stop_state_listener(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

