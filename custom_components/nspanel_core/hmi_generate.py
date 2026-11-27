"""NSPanel Core — HMI generator: a PanelDesign → a compiled TFT.

P234 (the user's architecture): the integration keeps the HMI kit; the
manager generates the per-panel source folder (base pages copied
UNCHANGED — the firmware's hardcoded behavior on them stays aligned —
the authored 'room' page regenerated as the dash menu, dash pages
appended), compiles with nxwright, and serves the TFT per panel.

Pure except compile(): everything writes into a caller-owned workdir.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib

from . import dashboard_design as dd
from .models import SS_LAYOUT_GROUPS, normalize_ss_layout

# Base page order — the FIRMWARE's positional ids depend on it
# (page0=0, screensaver=1, home=2, mini=3, room=4, spare=5, scenes=6).
# Dash pages append AFTER scenes; ids 7+.
BASE_PAGES = ("page0", "screensaver", "home", "mini", "room", "spare", "scenes")
KIT_PAGE_FILES = (".page.toml", ".nx")


def _write_toml(path: str, page_name: str, comps: list[dict]) -> None:
    lines = [
        "[page]",
        f'name = "{page_name}"',
        'type = "page"',
        "x = 0",
        "y = 0",
        "w = 480",
        "h = 320",
        "",
    ]
    for c in comps:
        lines += ["[[component]]", f'name = "{c["name"]}"', f'type = "{c["type"]}"']
        for key in ("x", "y", "w", "h"):
            lines.append(f"{key} = {int(c[key])}")
        if "pic" in c:
            lines.append(f'pic = "{c["pic"]}"')
        if "pic2" in c:
            lines.append(f'pic2 = "{c["pic2"]}"')
        # P306: kit page TOMLs use `txt`, dd.* components use `text`. Accept
        # both, and preserve the text attributes the firmware relies on —
        # dropping them in the photo-screensaver rewrite made the clock/date/
        # weather text unreadable on a user photo.
        if "txt" in c:
            lines.append(f'txt = "{c["txt"]}"')
        if "text" in c:
            lines.append(f'txt = "{c["text"]}"')
        # P357: txt_maxl MUST be >= the text's byte length — nxwright's
        # component default is 10, and a longer text REJECTS the whole
        # compile ("its txt has 13 bytes; its txt_maxl is 10"). The
        # generated pages set no txt_maxl, so any real-world label broke
        # the build. Set it from the text, floored at the default.
        if ("txt" in c or "text" in c) and "txt_maxl" not in c:
            text = c.get("txt", c.get("text", ""))
            lines.append(f"txt_maxl = {max(10, len(text))}")
        if "txt_maxl" in c:
            lines.append(f'txt_maxl = {int(c["txt_maxl"])}')
        if "font" in c:
            lines.append(f'font = "{c["font"]}"')
        for key in ("pco", "bco"):
            if key in c:
                lines.append(f'{key} = "{c[key]}"')
        for key in ("xcen", "ycen"):
            if key in c:
                lines.append(f"{key} = {int(c[key])}")
        if "sendkey" in c:
            lines.append(f"sendkey = {int(c['sendkey'])}")
        if "sta" in c:
            lines.append(f"sta = {int(c['sta'])}")
        if "vis" in c:
            lines.append(f"vis = {int(c['vis'])}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _toml_list(app_toml_text: str, key: str) -> list[str]:
    """Read a ``key = [ ... ]`` string array from an app.toml (P306: fonts
    and pictures are both kit-defined now — no hardcoded resource lists)."""
    return [
        line.strip().strip('"')
        for line in app_toml_text.split(key + " = [", 1)[1].split("]", 1)[0].split(",")
        if line.strip().strip('"')
    ]


def _write_app_toml(kit_dir: str, design: dd.PanelDesign, dest_dir: str,
                    extra_pictures: list[str] | None = None) -> None:
    # P279 CRITICAL: the detail pages were NEVER listed — nxwright derives
    # the page ids from app.toml's pages list, so det0..N were absent from
    # the compiled TFT while page_ids/component_map/dash_map claimed them:
    # every detail-page navigation no-oped and the state mirroring wrote
    # to nonexistent pages.
    pages = (list(BASE_PAGES) + [p.name for p in design.pages]
             + [dd.detail_name(i) for i in range(len(dd.light_items(design)))])
    kit_app = open(os.path.join(kit_dir, "app.toml"), encoding="utf-8").read()
    pictures = _toml_list(kit_app, "pictures")
    # P363: the studio cards are kit-level resources now
    for card in ("card_off", "card_on", "card_plain"):
        if card not in pictures:
            pictures.append(card)
    # P306: the font list comes from the kit too (the screensaver tab needs
    # real size/weight fonts); no hardcoded resources in the generator.
    fonts = _toml_list(kit_app, "fonts")
    pictures = pictures + [p for p in (extra_pictures or []) if p not in pictures]
    out = [
        "format = 1",
        'name = "nspanel-core"',
        'language = "nxlang_do_not_change_manually"',
        'screen = "NX4832F035"',
        "rotation = 270",
        'encoding = "iso-8859-1"',
        "pages = [",
    ]
    out += [f'    "{p}",' for p in pages]
    out.append("]")
    out.append("pictures = [")
    out += [f'    "{p}",' for p in pictures]
    out.append("]")
    out.append("fonts = [")
    out += [f'    "{f}",' for f in fonts]
    out.append("]")
    with open(os.path.join(dest_dir, "app.toml"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def _apply_ss_layout(comps: list, ss_layout: dict | None) -> None:
    """P369: move the screensaver components per the user's drag layout.

    Each group's box-origin override positions every component in the
    group at (box.x + dx, box.y + dy) - a stack (the weather glyphs, the
    forecast rows) moves as ONE item, preserving the kit's authored deltas
    relative to the group's bounding box. The layout is normalized first
    (closed keys, clamped coords — the same rule as the model)."""
    if not ss_layout:
        return
    layout = normalize_ss_layout(ss_layout)
    if not layout:
        return
    by_name = {c.get("name"): c for c in comps if isinstance(c, dict)}
    for group, pos in layout.items():
        spec = SS_LAYOUT_GROUPS[group]
        for name, (dx, dy) in spec["comps"].items():
            comp = by_name.get(name)
            if comp is None:
                continue
            comp["x"] = pos["x"] + dx
            comp["y"] = pos["y"] + dy


def generate_source(
    design: dd.PanelDesign, kit_dir: str, workdir: str,
    origins_dir: str | None = None,
    show_home_relays: bool = True,
    ss_layout: dict | None = None,
) -> dict[str, dict[str, int]]:
    """Build the per-panel HMI source folder; return the component map.

    P255: pages may carry a user-uploaded photo (background_image) — it is
    processed to the panel standards (bg_process) into two picture
    resources per page: the darkened variant backs the dashboard, and the
    full-brightness variant + the clock-text crops back the screensaver
    when that page is the panel's screensaver room.

    P369 (user request): ss_layout carries the drag layout of the
    screensaver preview ({group: {x, y}}) — the positions are baked into
    the screensaver page's components. Component ORDER is untouched (the
    firmware's object-name addressing and the page's positional
    dependencies survive), only x/y move, and the clock-text photo crops
    follow the moved positions (the crops read the rects AFTER the moves).
    """
    from . import bg_process as bgp

    design.validate()
    src = os.path.join(workdir, "hmi")
    if os.path.isdir(src):
        shutil.rmtree(src)
    os.makedirs(os.path.join(src, "pages"))

    # fonts, pictures, program.nx — copied verbatim from the kit
    for name in ("fonts", "pictures"):
        shutil.copytree(os.path.join(kit_dir, name), os.path.join(src, name))
    for root_file in ("program.nx", "defaults.toml"):
        src_file = os.path.join(kit_dir, root_file)
        if os.path.isfile(src_file):
            shutil.copy(src_file, os.path.join(src, root_file))

    # P255: the user's room photos -> picture resources
    extra_pictures: list[str] = []
    for n, page in enumerate(design.pages):
        if not page.background_image or origins_dir is None:
            continue
        orig = os.path.join(origins_dir, page.background_image)
        if not os.path.isfile(orig):
            continue
        scr, dash = bgp.process_background(orig, os.path.join(src, "pictures"), f"p{n}")
        extra_pictures += [f"p{n}_scr", f"p{n}_dash"]
        page.background = f"p{n}_dash"  # the dashboard uses the darkened variant
    if design.screensaver_page:
        scr_page = next((p for p in design.pages if p.name == design.screensaver_page), None)
        if scr_page is not None and scr_page.background_image and origins_dir is not None:
            orig = os.path.join(origins_dir, scr_page.background_image)
            if os.path.isfile(orig):
                n = design.pages.index(scr_page)
                scr = os.path.join(src, "pictures", f"p{n}_scr.jpg")
                extra_pictures += ["sct", "scd", "sca"]

    # base pages — copied UNCHANGED (the firmware's positional ids and
    # hardcoded component behavior depend on them)
    for page in BASE_PAGES:
        for ext in KIT_PAGE_FILES:
            src_file = os.path.join(kit_dir, "pages", page + ext)
            if os.path.isfile(src_file):
                shutil.copy(src_file, os.path.join(src, "pages", page + ext))

    # P255: the photo screensaver — written AFTER the base copy above, so
    # it wins: the full-brightness photo behind everything, photo CROPS
    # behind each clock text (sta=2); page id and component order unchanged.
    scr_design_page = next(
        (p for p in design.pages if p.name == design.screensaver_page), None)
    scr_ready = (
        scr_design_page is not None and scr_design_page.background_image
        and origins_dir is not None
        and os.path.isfile(os.path.join(origins_dir, scr_design_page.background_image))
    )
    if scr_ready:
        scr_toml = tomllib.load(
            open(os.path.join(kit_dir, "pages", "screensaver.page.toml"), "rb"))
        # P369: the drag layout BEFORE the crop rects — the photo crops
        # behind the clock texts must follow the moved positions.
        _apply_ss_layout(scr_toml["component"], ss_layout)
        n = design.pages.index(scr_design_page)
        rects = {c["name"]: (c["x"], c["y"], c["w"], c["h"])
                 for c in scr_toml["component"] if c["type"] == "text"}
        crops = {"curTime": "sct", "curDay": "scd", "curAMPM": "sca"}
        for c in scr_toml["component"]:
            if c["name"] == "bg":
                c["pic"] = f"p{n}_scr"
            elif c["name"] in crops:
                crop_name = crops[c["name"]]
                rect = rects[c["name"]]
                bgp.crop_rect(os.path.join(src, "pictures", f"p{n}_scr.jpg"), rect).save(
                    os.path.join(src, "pictures", crop_name + ".png"))
                c["sta"] = 2
                c["pic"] = crop_name
        _write_toml(
            os.path.join(src, "pages", "screensaver.page.toml"),
            "screensaver", scr_toml["component"])

    # P369: no photo on the screensaver page — the drag layout still
    # applies to the copied kit file (the photo path above already did it).
    if ss_layout and not scr_ready:
        _scr_copy = os.path.join(src, "pages", "screensaver.page.toml")
        if os.path.isfile(_scr_copy):
            _toml_data = tomllib.load(open(_scr_copy, "rb"))
            _apply_ss_layout(_toml_data["component"], ss_layout)
            _write_toml(_scr_copy, "screensaver", _toml_data["component"])

    # the menu page — regenerated over the authored room page
    menu_comps = dd.menu_components(design)
    # P363: the labels ON the menu cards render as crops OF THE CARD
    # (sta=2+pic) — the text floats on the card with no bar.
    card_png = os.path.join(src, "pictures", "card_plain.png")
    for c in menu_comps:
        if c["type"] == "text" and c["name"].startswith("ml"):
            if os.path.isfile(card_png):
                bgp.crop_rect(card_png, (c["x"], c["y"], c["w"], c["h"])).save(
                    os.path.join(src, "pictures", f"{c['name']}_crop.png"))
                c["sta"] = 2
                c["pic"] = f"{c['name']}_crop"
                extra_pictures.append(f"{c['name']}_crop")  # P363: register the crop
    _write_toml(
        os.path.join(src, "pages", "room.page.toml"),
        "room",
        menu_comps,
    )
    open(os.path.join(src, "pages", "room.nx"), "w").close()

    # P357: the home page — regenerated over the authored kit page; the
    # relay buttons appear only when the integration's panel setting says
    # so (the user decides there, the kit bakes nothing).
    _write_toml(
        os.path.join(src, "pages", "home.page.toml"),
        "home",
        dd.home_components(design, show_relays=show_home_relays),
    )
    open(os.path.join(src, "pages", "home.nx"), "w").close()

    # dash pages — appended after the base seven
    for page in design.pages:
        comps = dd.dash_components(design, page)
        n = design.pages.index(page)
        dash_photo = os.path.join(src, "pictures", f"p{n}_dash.jpg")
        if page.background_image and origins_dir is not None and os.path.isfile(dash_photo):
            # P363: the texts over the photo render as IMAGE CROPS (sta=2) —
            # the same treatment the photo screensaver gives its clock: no
            # white bars behind the text. Crop the darkened photo behind
            # the title.
            import tomllib as _tl
            for c in comps:
                if c["type"] == "text" and c["name"] == "title":
                    bgp.crop_rect(dash_photo, (c["x"], c["y"], c["w"], c["h"])).save(
                        os.path.join(src, "pictures", f"p{n}_title.png"))
                    c["sta"] = 2
                    c["pic"] = f"p{n}_title"
                    extra_pictures.append(f"p{n}_title")  # P363: register the crop
        _write_toml(
            os.path.join(src, "pages", page.name + ".page.toml"),
            page.name,
            comps,
        )
        open(os.path.join(src, "pages", page.name + ".nx"), "w").close()

    # P274: the LIGHT DETAIL PAGES — the entity cards on the panel: the
    # on/off tile, the brightness minus/percent/plus, the RGB swatches.
    lights = dd.light_items(design)
    for i, item in enumerate(lights):
        name = dd.detail_name(i)
        _write_toml(
            os.path.join(src, "pages", name + ".page.toml"),
            name,
            dd.detail_components(design, item, i),
        )
        open(os.path.join(src, "pages", name + ".nx"), "w").close()
    # P361: the swatch resources are kit-level (sw_*) — the old
    # `extra_pictures + [...] if False else extra_pictures` never added the
    # per-detail swatch names; keep that behavior without the dead expression.
    _write_app_toml(kit_dir, design, src, extra_pictures=extra_pictures)

    cmap = dd.component_map(design, show_home_relays=show_home_relays)
    # the detail pages' maps (the manager routes the detail presses)
    for i, item in enumerate(lights):
        cmap[dd.detail_name(i)] = {
            c["name"]: cid for cid, c in enumerate(
                dd.detail_components(design, item, i), start=1)
        }
    with open(os.path.join(workdir, "component_map.json"), "w", encoding="utf-8") as f:
        json.dump(cmap, f, indent=2, sort_keys=True)
    with open(os.path.join(workdir, "page_ids.json"), "w", encoding="utf-8") as f:
        json.dump(dd.page_ids(design), f)
    return cmap


def compile_tft(workdir: str, out_path: str) -> str:
    """nxwright compile → the panel's TFT. Runs in an executor.

    P312: the toolchain is VENDORED in the integration — the manager runs
    inside the Home Assistant environment where no global nxwright exists
    (it was installed only on the development host; the user's
    "No such file or directory: 'nxwright'"). Invoked via the same
    interpreter with the vendored package first on sys.path.
    """
    from .hmi_tool import ensure_toolchain, VENDORED_DIR, VENDORED_FW_DIR

    ensure_toolchain()
    src = os.path.join(workdir, "hmi")
    if os.path.exists(out_path):
        os.unlink(out_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(VENDORED_DIR.parent) + os.pathsep + env.get("PYTHONPATH", "")
    # P312: the Nextion Editor's runtime firmware is vendored too — the
    # compile needs it (the cache points there; no download consent needed)
    env["NXWRIGHT_CACHE"] = str(VENDORED_FW_DIR)
    proc = subprocess.run(
        [sys.executable, "-m", "nxwright", "compile", "--overwrite", src, out_path],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(
            "nxwright compile failed: " + (proc.stderr or proc.stdout)[-500:]
        )
    return out_path
