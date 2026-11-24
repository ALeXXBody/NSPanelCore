"""P357: the relays appear ONLY when the user wants them there.

User order: "relay should be on the page only if the user wants them
there... the default should be in the integrations". The integration's
panel setting (show_home_relays) decides; the generated home page and its
component map carry the rel1/rel2 buttons only when the setting says so.
The kit bakes nothing. Also: txt_maxl — nxwright's default (10) rejected
any real-world label ("its txt has 13 bytes; its txt_maxl is 10") — the
writer now sets it from the text.
"""

from __future__ import annotations

import io
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard_design as dd  # noqa: E402
from nspanel_core import hmi_generate as hg  # noqa: E402

KIT = REPO / "custom_components" / "nspanel_core" / "hmi_kit"


def _design():
    d = dd.PanelDesign(mac="e465b849a100")
    d.pages = [dd.DashPage(name="dash_page", title="Kitchen")]
    d.items = [
        dd.DashItem(id="it1", page="dash_page", slot=0,
                    entity_id="light.kitchen_light", widget="light",
                    label="Kitchen light"),
        dd.DashItem(id="it2", page="dash_page", slot=1,
                    entity_id="light.kitchen_light_small", widget="light",
                    label="Small light"),
    ]
    return d


def test_home_has_relays_by_default():
    comps = dd.home_components(_design(), show_relays=True)
    names = [c["name"] for c in comps]
    assert "rel1" in names and "rel2" in names
    assert "room_pic" in names and "scenes_pic" in names


def test_home_omits_relays_when_the_user_hides_them():
    comps = dd.home_components(_design(), show_relays=False)
    names = [c["name"] for c in comps]
    assert "rel1" not in names and "rel2" not in names
    # the navigation buttons stay
    assert "room_pic" in names and "scenes_pic" in names


def test_component_map_home_section_follows_the_flag():
    d = _design()
    with_relays = dd.component_map(d, show_home_relays=True)["home"]
    without = dd.component_map(d, show_home_relays=False)["home"]
    assert "rel1" in with_relays and "rel1" not in without
    assert without["room_btn"] != with_relays["room_btn"], (
        "removing the relays shifts the navigation ids — the map MUST "
        "follow the generated layout (the touch routing depends on it)")


def test_map_matches_the_written_toml_layout():
    """The map is derived from the SAME comps the writer renders — verify
    against the actual TOML bytes for the no-relays case."""
    import tempfile
    d = _design()
    wd = tempfile.mkdtemp(prefix="p357-")
    cmap = hg.generate_source(d, str(KIT), wd, show_home_relays=False)
    toml_text = (pathlib.Path(wd) / "hmi" / "pages" / "home.page.toml").read_text()
    comp_names = re.findall(r'^name = "(\w+)"$', toml_text, re.M)[1:]  # skip the page name
    ids = {name: n for n, name in enumerate(comp_names, start=1)}
    assert "rel1" not in ids
    for key in ("room_btn", "room_pic", "scenes_btn", "scenes_pic"):
        assert cmap["home"][key] == ids[key], (key, cmap["home"][key], ids[key])


def test_write_toml_sets_txt_maxl_from_the_text():
    """nxwright's default txt_maxl=10 rejected any longer label."""
    d = _design()
    import tempfile
    wd = tempfile.mkdtemp(prefix="p357-")
    hg.generate_source(d, str(KIT), wd, show_home_relays=True)
    dash = (pathlib.Path(wd) / "hmi" / "pages" / "dash_page.page.toml").read_text()
    # "Kitchen light" = 13 bytes -> txt_maxl must be >= 13
    m = re.search(r'txt = "Kitchen light"\ntxt_maxl = (\d+)', dash)
    assert m and int(m.group(1)) >= 13, "the label's txt_maxl must cover its length"


def test_generated_dual_state_tiles_carry_explicit_empty_txt():
    import tempfile
    d = _design()
    wd = tempfile.mkdtemp(prefix="p357-")
    hg.generate_source(d, str(KIT), wd, show_home_relays=True)
    dash = (pathlib.Path(wd) / "hmi" / "pages" / "dash_page.page.toml").read_text()
    for m in re.finditer(r"\[\[component\]\][^\[]*?dual-state-button[^\[]*", dash):
        assert 'txt = ""' in m.group(0), "the tile must not leak the compiler default"
