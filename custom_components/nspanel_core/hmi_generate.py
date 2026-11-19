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

from . import dashboard_design as dd

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
        if "text" in c:
            lines.append(f'txt = "{c["text"]}"')
        if "font" in c:
            lines.append(f'font = "{c["font"]}"')
        if "sendkey" in c:
            lines.append(f"sendkey = {int(c['sendkey'])}")
        if "sta" in c:
            lines.append(f"sta = {int(c['sta'])}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_app_toml(kit_dir: str, design: dd.PanelDesign, dest_dir: str,
                    extra_pictures: list[str] | None = None) -> None:
    pages = list(BASE_PAGES) + [p.name for p in design.pages]
    pictures = [
        line.strip().strip('"')
        for line in open(os.path.join(kit_dir, "app.toml"), encoding="utf-8")
        .read()
        .split("pictures = [", 1)[1]
        .split("]", 1)[0]
        .split(",")
        if line.strip().strip('"')
    ]
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
    out.append('    "NotoSans24",')
    out.append('    "NotoSans64",')
    out.append("]")
    with open(os.path.join(dest_dir, "app.toml"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def generate_source(
    design: dd.PanelDesign, kit_dir: str, workdir: str,
    origins_dir: str | None = None,
) -> dict[str, dict[str, int]]:
    """Build the per-panel HMI source folder; return the component map.

    P255: pages may carry a user-uploaded photo (background_image) — it is
    processed to the panel standards (bg_process) into two picture
    resources per page: the darkened variant backs the dashboard, and the
    full-brightness variant + the clock-text crops back the screensaver
    when that page is the panel's screensaver room.
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
        import tomllib
        scr_toml = tomllib.load(
            open(os.path.join(kit_dir, "pages", "screensaver.page.toml"), "rb"))
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

    # the menu page — regenerated over the authored room page
    _write_toml(
        os.path.join(src, "pages", "room.page.toml"),
        "room",
        dd.menu_components(design),
    )
    open(os.path.join(src, "pages", "room.nx"), "w").close()

    # dash pages — appended after the base seven
    for page in design.pages:
        _write_toml(
            os.path.join(src, "pages", page.name + ".page.toml"),
            page.name,
            dd.dash_components(design, page),
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
    extra_pictures = extra_pictures + [
        f"det{i}_sw{k}" for i in range(len(lights)) for k, _c in enumerate(dd.COLOR_PRESETS)
    ] if False else extra_pictures  # the swatch resources are kit-level (sw_*)
    _write_app_toml(kit_dir, design, src, extra_pictures=extra_pictures)

    cmap = dd.component_map(design)
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
    """nxwright compile → the panel's TFT. Runs in an executor."""
    src = os.path.join(workdir, "hmi")
    if os.path.exists(out_path):
        os.unlink(out_path)
    proc = subprocess.run(
        ["nxwright", "compile", "--overwrite", src, out_path],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(
            "nxwright compile failed: " + (proc.stderr or proc.stdout)[-500:]
        )
    return out_path
