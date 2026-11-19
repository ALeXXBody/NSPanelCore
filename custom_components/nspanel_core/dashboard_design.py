"""NSPanel Core — dashboard DESIGN model (pure, host-testable).

P234: the user's dashboard design per panel — rooms (pages), items
(entity placements), geometry. The manager is the single source of
truth; the panel stores nothing. This module holds the dataclasses,
the validation, and the deterministic component-id map (the contract
between the generated HMI and the touch events the panel publishes).

Component ids are 1-based DECLARATION ORDER per page (verified against
the firmware's HMI map: home 1=bg 2=rel1 3=rel2 4=room 6=scenes).
"""

from __future__ import annotations

from dataclasses import dataclass, field

WIDGET_TYPES = ("switch", "light", "rgb_light", "scene", "sensor", "climate")

# The generated room-menu page replaces the authored "room" page — its
# page id is fixed by the base pages order (page0, screensaver, home,
# mini, ROOM, spare, scenes → id 4).
MENU_PAGE_NAME = "room"
MENU_PAGE_ID = 4

_PAGE_NAME_RE = __import__("re").compile(r"^dash_[a-z0-9_]{1,9}$")
_ENTITY_RE = __import__("re").compile(r"^[a-z_]+\.[a-z0-9_]+$")
_NAME_RE = __import__("re").compile(r"^[A-Za-z0-9_\- ]{1,32}$")
_ITEM_RE = __import__("re").compile(r"^[a-z][a-z0-9_]{0,23}$")
_BGIMG_RE = __import__("re").compile(r"^[a-z0-9_]+\.(jpg|jpeg|png)$")


class DesignError(ValueError):
    """Invalid dashboard design — the message is user-facing."""


@dataclass
class DashItem:
    """One entity placement on one dash page."""

    id: str
    page: str  # dash page name
    widget: str
    entity_id: str
    label: str = ""
    slot: int = 0  # 0..5 — the tile position on the page

    def validate(self) -> None:
        if not _ITEM_RE.match(self.id or ""):
            raise DesignError(f"item id {self.id!r}: use a-z, 0-9, _ (max 24)")
        if self.widget not in WIDGET_TYPES:
            raise DesignError(f"unknown widget type {self.widget!r}")
        if not _ENTITY_RE.match(self.entity_id or ""):
            raise DesignError(f"entity id {self.entity_id!r} is not a HA entity")
        if not 0 <= self.slot <= 5:
            raise DesignError("slot must be 0-5 (6 tiles per page)")
        if len(self.label) > 24:
            raise DesignError("label too long (max 24 chars)")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "page": self.page,
            "widget": self.widget,
            "entity_id": self.entity_id,
            "label": self.label,
            "slot": self.slot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DashItem":
        return cls(
            id=str(d.get("id", "")),
            page=str(d.get("page", "")),
            widget=str(d.get("widget", "")),
            entity_id=str(d.get("entity_id", "")),
            label=str(d.get("label", "")),
            slot=int(d.get("slot", 0)),
        )


@dataclass
class DashPage:
    """One generated dashboard page (a room)."""

    name: str  # dash_<...>
    title: str  # shown in the menu + page header
    background: str = "bg_plain"  # picture resource name from the kit
    background_image: str = ""  # the user's uploaded photo (stored filename)

    def validate(self) -> None:
        if not _PAGE_NAME_RE.match(self.name or ""):
            raise DesignError(f"page name {self.name!r}: dash_ + a-z/0-9/_ (max 25)")
        if not _NAME_RE.match(self.title or ""):
            raise DesignError(f"page title {self.title!r}: too long or invalid")
        if self.background and not __import__("re").compile(
            r"^[a-z][a-z0-9_]{0,13}$"
        ).match(self.background):
            raise DesignError("invalid background picture name")
        if self.background_image and not _BGIMG_RE.match(self.background_image):
            raise DesignError("invalid background image reference")

    def to_dict(self) -> dict:
        return {"name": self.name, "title": self.title, "background": self.background,
                "background_image": self.background_image}

    @classmethod
    def from_dict(cls, d: dict) -> "DashPage":
        return cls(
            name=str(d.get("name", "")),
            title=str(d.get("title", "")),
            background=str(d.get("background", "bg_plain")),
            background_image=str(d.get("background_image", "")),
        )


@dataclass
class PanelDesign:
    """The dashboard design for one panel."""

    mac: str  # lowercase, no separators — matches PanelConfig.mac
    pages: list[DashPage] = field(default_factory=list)
    items: list[DashItem] = field(default_factory=list)
    screensaver_page: str = ""  # the room whose photo backs the screensaver

    def validate(self) -> None:
        if not self.mac or not isinstance(self.mac, str):
            raise DesignError("missing panel mac")
        names = set()
        for p in self.pages:
            p.validate()
            if p.name in names:
                raise DesignError(f"duplicate page name {p.name}")
            names.add(p.name)
        item_ids = set()
        for it in self.items:
            it.validate()
            if it.page not in names:
                raise DesignError(f"item {it.id}: page {it.page} is not in pages")
            slot_owner = [
                x for x in self.items if x.page == it.page and x.slot == it.slot
            ]
            if len(slot_owner) > 1:
                raise DesignError(f"page {it.page}: two items on slot {it.slot}")
            if it.id in item_ids:
                raise DesignError(f"duplicate item id {it.id}")
            item_ids.add(it.id)
        if len(self.pages) > 6:
            raise DesignError("max 6 dashboard pages (the menu grid is 3x2)")
        if self.screensaver_page and self.screensaver_page not in names:
            raise DesignError("the screensaver room must be one of the pages")

    # -- persistence -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "pages": [p.to_dict() for p in self.pages],
            "items": [i.to_dict() for i in self.items],
            "screensaver_page": self.screensaver_page,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PanelDesign":
        design = cls(
            mac=str(d.get("mac", "")),
            pages=[DashPage.from_dict(x) for x in d.get("pages", [])],
            items=[DashItem.from_dict(x) for x in d.get("items", [])],
            screensaver_page=str(d.get("screensaver_page", "")),
        )
        return design


# -- layout (single source of truth for the generator AND the id map) ----

# 3x2 tile grid shared by the menu page and dash pages (480x320 screen).
GRID_SLOTS = [
    (10, 60), (165, 60), (320, 60),
    (10, 190), (165, 190), (320, 190),
]
TILE_W, TILE_H = 150, 110
BTN_H = 88
LBL_H = 20

_TEXT_SAFETY = {**{c: " " for c in range(32)}, ord('"'): "'", ord("\\"): "/"}


def clean_text(value: str, max_len: int) -> str:
    """Text safe for a Nextion .txt= assignment (control chars, quotes out)."""
    return (value or "").translate(_TEXT_SAFETY)[:max_len]


def menu_components(design: PanelDesign) -> list[dict]:
    """The generated menu page (replaces the authored 'room' page)."""
    comps: list[dict] = [
        {"name": "bg", "type": "picture", "x": 0, "y": 0, "w": 480, "h": 320,
         "pic": "bg_room"},
    ]
    for n, page in enumerate(design.pages):
        x, y = GRID_SLOTS[n]
        comps.append({"name": f"m{n}", "type": "hotspot",
                      "x": x, "y": y, "w": TILE_W, "h": BTN_H, "sendkey": 3})
        comps.append({"name": f"ml{n}", "type": "text",
                      "x": x, "y": y + BTN_H, "w": TILE_W, "h": LBL_H,
                      "text": clean_text(page.title, 24), "font": "NotoSans24"})
    comps.append({"name": "back", "type": "hotspot",
                  "x": 165, "y": 290, "w": TILE_W, "h": 24, "sendkey": 3})
    comps.append({"name": "back_pic", "type": "picture",
                  "x": 165, "y": 290, "w": TILE_W, "h": 24, "pic": "btn_scenes"})
    return comps


def dash_components(design: PanelDesign, page: DashPage) -> list[dict]:
    """One generated dash page: bg, title, per-item comps, back."""
    comps: list[dict] = [
        {"name": "bg", "type": "picture", "x": 0, "y": 0, "w": 480, "h": 320,
         "pic": page.background if page.background else "bg_plain"},
        {"name": "title", "type": "text", "x": 10, "y": 20, "w": 300, "h": 30,
         "text": clean_text(page.title, 24), "font": "NotoSans24"},
    ]
    page_items = sorted(
        (i for i in design.items if i.page == page.name), key=lambda x: x.slot
    )
    for it in page_items:
        x, y = GRID_SLOTS[it.slot]
        if it.widget in ("switch", "light", "rgb_light"):
            comps.append({"name": f"b{it.slot}", "type": "dual-state-button",
                          "x": x, "y": y, "w": TILE_W, "h": BTN_H,
                          "pic": "btn_off", "pic2": "btn_on", "sendkey": 3})
        elif it.widget == "scene":
            comps.append({"name": f"b{it.slot}", "type": "picture",
                          "x": x, "y": y, "w": TILE_W, "h": BTN_H,
                          "pic": "btn_scenes", "sendkey": 3})
        else:  # sensor / climate — a value text (txt= updated at runtime)
            comps.append({"name": f"b{it.slot}", "type": "text",
                          "x": x, "y": y, "w": TILE_W, "h": BTN_H,
                          "text": "--", "font": "NotoSans64"})
        comps.append({"name": f"l{it.slot}", "type": "text",
                      "x": x, "y": y + BTN_H, "w": TILE_W, "h": LBL_H,
                      "text": clean_text(it.label, 24), "font": "NotoSans24"})
    comps.append({"name": "back", "type": "hotspot",
                  "x": 395, "y": 20, "w": 75, "h": 30, "sendkey": 3})
    comps.append({"name": "back_pic", "type": "picture",
                  "x": 395, "y": 20, "w": 75, "h": 30, "pic": "btn_scenes"})
    return comps


# -- component-id map (the touch-routing contract) ----------------------

def component_map(design: PanelDesign) -> dict[str, dict[str, int]]:
    """page name → component name → Nextion component id (1-based).

    Derived from the SAME layout functions the generator renders, so the
    map and the HMI cannot drift apart.
    """
    out: dict[str, dict[str, int]] = {}
    for page_name, comps in (
        (MENU_PAGE_NAME, menu_components(design)),
        *[(p.name, dash_components(design, p)) for p in design.pages],
    ):
        out[page_name] = {c["name"]: n for n, c in enumerate(comps, start=1)}
    # P274: the light detail pages — the entity cards on the panel
    for i, item in enumerate(light_items(design)):
        out[detail_name(i)] = {
            c["name"]: cid for cid, c in enumerate(
                detail_components(design, item, i), start=1)
        }
    return out


def page_ids(design: PanelDesign) -> list[int]:
    """Nextion page ids for the dash-enabled pages (menu + dash pages +
    the light detail pages).

    Base page order (fixed by the kit): page0=0, screensaver=1, home=2,
    mini=3, room=4, spare=5, scenes=6, then dash pages from 7, then the
    light detail pages (P274: the entity cards on the panel).
    """
    ids = [MENU_PAGE_ID]
    for i, _p in enumerate(design.pages):
        ids.append(7 + i)
    ids += detail_page_ids(design)
    return ids


# -- the detail pages (P274): the entity cards ON the panel ---------------

COLOR_PRESETS = [
    ("white", (255, 255, 255)), ("warm", (255, 180, 100)),
    ("red", (255, 60, 60)), ("green", (70, 230, 90)),
    ("blue", (70, 140, 255)), ("purple", (190, 90, 255)),
]


def light_items(design: PanelDesign) -> list[DashItem]:
    """The light/RGB items in the design order — each gets a detail page."""
    return [i for i in design.items if i.widget in ("light", "rgb_light")]


def detail_name(n: int) -> str:
    return f"det{n}"


def detail_components(design: PanelDesign, item: DashItem, n: int) -> list[dict]:
    """The entity card ON the panel: the on/off tile, the brightness
    minus/percent/plus, the RGB color swatches, back."""
    rgb = item.widget == "rgb_light"
    comps: list[dict] = [
        {"name": "bg", "type": "picture", "x": 0, "y": 0, "w": 480, "h": 320,
         "pic": "bg_plain"},
        {"name": "title", "type": "text", "x": 10, "y": 20, "w": 380, "h": 30,
         "text": clean_text(item.label, 24), "font": "NotoSans24"},
        {"name": "pwr", "type": "dual-state-button", "x": 165, "y": 60,
         "w": 150, "h": 88, "pic": "btn_off", "pic2": "btn_on", "sendkey": 3},
        {"name": "minus", "type": "hotspot", "x": 30, "y": 150, "w": 90, "h": 90,
         "sendkey": 3},
        {"name": "minus_pic", "type": "picture", "x": 30, "y": 150, "w": 90, "h": 90,
         "pic": "btn_minus"},
        {"name": "pct", "type": "text", "x": 165, "y": 150, "w": 150, "h": 90,
         "text": "--", "font": "NotoSans64"},
        {"name": "plus", "type": "hotspot", "x": 360, "y": 150, "w": 90, "h": 90,
         "sendkey": 3},
        {"name": "plus_pic", "type": "picture", "x": 360, "y": 150, "w": 90, "h": 90,
         "pic": "btn_plus"},
    ]
    if rgb:
        for k, (cname, _rgbv) in enumerate(COLOR_PRESETS):
            x = 30 + k * 75
            comps.append({"name": f"c{k}", "type": "picture", "x": x, "y": 255,
                          "w": 60, "h": 60, "pic": f"sw_{cname}", "sendkey": 3})
    comps.append({"name": "back", "type": "hotspot", "x": 400, "y": 20, "w": 70, "h": 30,
                  "sendkey": 3})
    comps.append({"name": "back_pic", "type": "picture", "x": 400, "y": 20, "w": 70, "h": 30,
                  "pic": "btn_scenes"})
    return comps


def detail_page_ids(design: PanelDesign) -> list[int]:
    """The detail pages' ids — after the dash pages (7..7+n-1)."""
    n = len(design.pages)
    return [7 + n + i for i in range(len(light_items(design)))]
