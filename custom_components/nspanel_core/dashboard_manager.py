"""NSPanel Core — dashboard service (manager side of the P234 design).

The manager owns everything the panel stores nothing:
  - the designs (one PanelDesign per panel, in HA storage)
  - the generated per-panel TFT + the component map (config dir)
  - touch routing (panel publishes component presses → entity services)
  - state mirroring (HA state changes → sanitized dash commands)
  - send-to-panel (generate → nxwright compile → serve → trigger reflash)
"""

from __future__ import annotations

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

    def tft_override(self) -> str | None:
        """The per-panel TFT being delivered right now (serving slot)."""
        if self._serving and os.path.isfile(self._serving["path"]):
            return self._serving["path"]
        return None

    def serving_info(self) -> dict:
        return dict(self._serving) if self._serving else {}

    async def async_send_to_panel(self, mac: str) -> dict:
        """Generate + compile + arm the serving slot + trigger the reflash."""
        design = self._designs.get(mac)
        if design is None or not (design.pages or design.items):
            return {"error": "no design saved for this panel"}
        if self._serving:
            return {"error": "a send is already in progress (panel %s)" % self._serving["mac"]}
        panel = self.manager.panel_by_mac(mac)
        if panel is None or not panel.accepted:
            return {"error": "panel not found or not accepted"}
        try:
            path, md5, cmap, page_ids = await self.async_generate(design)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("dashboard generate/compile failed for %s", mac)
            return {"error": f"compile failed: {exc}"}
        self._serving = {"mac": mac, "path": path, "md5": md5}
        self._maps[mac] = cmap
        self._page_ids[mac] = list(page_ids)
        await self._save()
        await self.manager._publish(
            const.panel_topic(mac, "command"),
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
        """Push dash_map + current item values to a panel running its TFT."""
        if not self.has_design(mac):
            return
        page_ids = self._page_ids.get(mac)
        if not page_ids:
            return
        await self.manager._publish(
            const.panel_topic(mac, "command"),
            json.dumps({"command": "dash_map", "pages": page_ids}),
        )
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
                    const.panel_topic(mac, "command"),
                    json.dumps({"command": "dash", "payload": stmt}),
                )
            )

    # -- the user's room photos -------------------------------------------

    def store_background(self, mac: str, page: str, file_bytes: bytes,
                         filename: str) -> dict:
        """Store a room photo upload and reference it in the design.

        P255 (the user's design): the photo is kept as-is (the screensaver
        variant) and processed to the dashboard variant at generate time.
        """
        import imghdr

        ext = ".png" if (imghdr.what(None, file_bytes) == "png") else ".jpg"
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
            return {"error": f"page {page} is not in the design"}
        target.background_image = safe
        # the underlying task is async: persist through the running loop
        import asyncio

        self.hass.loop.create_task(self._save())
        return {"ok": True, "stored": safe}

    def origins_dir(self) -> str:
        return _dash_dir(self.hass)

    # -- touch routing -----------------------------------------------------

    @callback
    def on_touch(self, mac: str, page: int, component: int, event: int) -> None:
        """Resolve a panel touch to an action. Releases only."""
        if event != 0:
            return
        design = self._designs.get(mac)
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
                self._run_item(item)
                return

    @callback
    def _dash(self, mac: str, stmt: str) -> None:
        self.hass.async_create_task(
            self.manager._publish(
                const.panel_topic(mac, "command"),
                json.dumps({"command": "dash", "payload": stmt}),
            )
        )

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
        @callback
        def _on_state(event: Event) -> None:
            entity_id = event.data["entity_id"]
            new_state = event.data.get("new_state")
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
            self._unsub_state = self.hass.bus.async_track_state_change_event(
                list(entities), _on_state
            )

    def stop_state_listener(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

