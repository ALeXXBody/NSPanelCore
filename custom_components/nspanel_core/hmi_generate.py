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
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_app_toml(kit_dir: str, design: dd.PanelDesign, dest_dir: str) -> None:
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
    design: dd.PanelDesign, kit_dir: str, workdir: str
) -> dict[str, dict[str, int]]:
    """Build the per-panel HMI source folder; return the component map."""
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

    # base pages — copied UNCHANGED (the firmware's positional ids and
    # hardcoded component behavior depend on them)
    for page in BASE_PAGES:
        for ext in KIT_PAGE_FILES:
            src_file = os.path.join(kit_dir, "pages", page + ext)
            if os.path.isfile(src_file):
                shutil.copy(src_file, os.path.join(src, "pages", page + ext))

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

    _write_app_toml(kit_dir, design, src)

    cmap = dd.component_map(design)
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
