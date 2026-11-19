"""P289: the dashboard studio's Panel settings tab must be REAL sub-tabs.

Regression for the user's report: "SCREEN & SCREENSAVER / PHYSICAL BUTTONS /
GENERAL are plain text, they do nothing". The three groups are now clickable
sub-tabs that toggle the server-rendered fields IN PLACE — the fields must
never be moved out of their <form> (that silently dropped them from FormData
on save).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DASH = (REPO / "custom_components" / "nspanel_core" / "ui" /
        "templates" / "dashboard.html")
HTML = DASH.read_text()


def test_three_clickable_subtabs_replace_the_dead_headings():
    for sec, label in (("screen", "Screen"), ("buttons", "Physical buttons"),
                       ("general", "General")):
        assert f'class="studio-subtab' in HTML
        assert f'data-sec="{sec}"' in HTML, f"missing the {sec} sub-tab"
        assert f"setPanelSubTab('{sec}')" in HTML
        assert label in HTML
    # the old plain-text headings and empty slots are gone
    assert "data-slot=" not in HTML
    assert "SCREEN &amp; SCREENSAVER</h4>" not in HTML
    assert "PHYSICAL BUTTONS</h4>" not in HTML
    assert "GENERAL</h4>" not in HTML


def test_fields_stay_inside_the_form_on_save():
    """The old code appended the sections into external slots, so the
    inputs left the form and the save POST silently omitted them."""
    assert "slot.appendChild" not in HTML
    fn = HTML[HTML.index("function setPanelSubTab"):HTML.index("function loadPanelSettings")]
    assert "style.display" in fn
    # all three groups are toggled in place, never detached
    for sec in ("screen", "buttons", "general"):
        assert f"'{sec}'" in fn
    assert "querySelector('#panel_settings_box form')" in fn


def test_saves_are_authenticated_and_report_errors():
    fn = HTML[HTML.index("function savePanelSettings"):HTML.index("/* ---- the live preview")]
    assert "nspanelFetch(form.action" in fn
    assert "new FormData(form)" in fn
    assert "Save failed" in fn
    # the in-form submit handler delegates to the same authed save
    assert "savePanelSettings();" in HTML


def test_panel_selection_and_zone_jumps_open_the_right_tab():
    assert "classList.contains('active')) loadPanelSettings()" in HTML
    assert "setTab(\"panel\"); setPanelSubTab('buttons');" in HTML
