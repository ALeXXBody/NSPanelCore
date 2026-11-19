"""P289/P290: the dashboard studio's Panel settings tab must be REAL sub-tabs,
with the behavior that belonged to the moved fields.

Regression for the user's report: "SCREEN & SCREENSAVER / PHYSICAL BUTTONS /
GENERAL are plain text, they do nothing" and then "you made the tabs but where
are the functions for these tabs?! ... you have a ledger... USE IT!!!".

The fields were MOVED from the per-panel settings page (P263/P266), so the JS
behavior that came with them (update_shown_elements
from edit_nspanel.js, and the background picker from edit_nspanel.html) had to
move with them. The shared static JS + the shared modal are that move — one
source loaded by BOTH pages. The fields must never be moved out of their form
(that silently dropped them from FormData on save).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = (REPO / "custom_components" / "nspanel_core" / "ui")
DASH = UI / "templates" / "dashboard.html"
PARTIAL = UI / "templates" / "_panel_settings_fields.html"
MODAL = UI / "templates" / "_background_selector_modal.html"
EDIT = UI / "templates" / "edit_nspanel.html"
JS = UI / "static" / "panel_settings.js"
EDIT_JS = UI / "static" / "edit_nspanel.js"

HTML = DASH.read_text()
FIELDS = PARTIAL.read_text()


def _between(text, start, end):
    return text[text.index(start):text.index(end)]


def test_three_clickable_subtabs_replace_the_dead_headings():
    for sec, label in (("screen", "Screen"), ("buttons", "Physical buttons"),
                       ("general", "General")):
        assert 'class="studio-subtab' in HTML
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
    fn = _between(HTML, "function setPanelSubTab", "function loadPanelSettings")
    assert "style.display" in fn
    # all three groups are toggled in place, never detached
    for sec in ("screen", "buttons", "general"):
        assert f"'{sec}'" in fn
    # P297: the form is looked up inside the settings box so a missing form
    # can trigger an on-demand load; the sections themselves stay in place.
    assert "box.querySelector('form')" in fn
    # P290: P289 built "general" by moving every other child of the screen's
    # parent — that swallowed the wrapper containing the buttons section, so
    # the physical-buttons sub-tab could never be displayed. No more surgery.
    assert "appendChild" not in fn
    assert "createElement" not in fn


def test_the_partial_renders_all_three_sections_as_siblings():
    """The sections are server-rendered inside the one form; the studio only
    hides/shows them. General must be explicit, not assembled in the browser."""
    assert FIELDS.count('data-section="general"') == 1
    assert FIELDS.count('data-section="buttons"') == 1
    assert FIELDS.count('data-section="screen"') == 1
    assert FIELDS.index('data-section="general"') < FIELDS.index('data-section="buttons"')
    assert FIELDS.index('data-section="buttons"') < FIELDS.index('data-section="screen"')
    assert FIELDS.lstrip().startswith("{# P263") or "P263" in FIELDS[:200]
    assert FIELDS.index("<form ") < FIELDS.index('data-section="general"')
    assert FIELDS.rstrip().endswith("</form>")
    # the fields the moved tabs own really live in those sections
    general = _between(FIELDS, 'data-section="general"', 'data-section="buttons"')
    buttons = _between(FIELDS, 'data-section="buttons"', 'data-section="screen"')
    screen = FIELDS[FIELDS.index('data-section="screen"'):]
    for field in ("friendly_name", "panel_type", "room_id"):
        assert field in general, f"{field} missing from the general section"
    # these controls are removed from the General UI (kept only where data
    # integrity requires hidden preservation on save, never as visible controls)
    for removed in ("lock_to_default_room", "show_home_scenes",
                    "show_home_ceiling", "show_home_table", "show_home_kelvin",
                    "rooms"):
        assert f'type="checkbox" name="{removed}"' not in general
        assert f'type="radio" name="{removed}"' not in general
    assert '<select name="default_page"' not in general
    assert '<label for="default_page"' not in general
    assert "Reverse relays" not in general
    for field in ("button1_mode", "button2_mode", "button1_detached_mode_room",
                  "button2_detached_mode_room", "button1_mqtt_mode_controls",
                  "button2_mqtt_mode_controls"):
        assert field in buttons, f"{field} missing from the buttons section"
    for field in ("screen_dim_level", "screensaver_dim_level",
                  "screensaver_activation_timeout", "screensaver_mode"):
        assert field in screen, f"{field} missing from the screen section"


def test_saves_are_authenticated_and_report_errors():
    fn = _between(HTML, "function savePanelSettings", "/* ---- the live preview")
    assert "nspanelFetch(form.action" in fn
    assert "new FormData(form)" in fn
    assert "Save failed" in fn
    # the in-form submit handler delegates to the same authed save
    assert "savePanelSettings();" in HTML


def test_panel_selection_and_zone_jumps_open_the_right_tab():
    assert "classList.contains('active')) loadPanelSettings()" in HTML
    assert "setTab(\"panel\"); setPanelSubTab('buttons');" in HTML


# ---------------------------------------------------------------------------
# P290 — the FUNCTIONS that came with the moved fields
# ---------------------------------------------------------------------------

def test_moved_field_behavior_is_in_one_shared_static_file():
    js = JS.read_text()
    for fn in ("function update_shown_elements()",
               "function bindPanelSettingsBehavior()"):
        assert fn in js, f"missing {fn}"
    # direct/detached/mqtt/follow modes for BOTH physical buttons
    for n in ("1", "2"):
        for ident in (f"button{n}_mode", f"button{n}_detached_mode_controls",
                      f"button{n}_detached_mode_light", f"button{n}_mqtt_mode_controls",
                      f"button{n}_detached_mode_room"):
            assert f'#{ident}' in js, f"missing {ident} handling"
        assert f'.button{n}_detached_mode_light_option[data-room-id=' in js
        assert f'button{n}_detached_mode_light").prop("required", true)' in js
    # the original change bindings, including the screensaver-mode one
    for ident in ("button1_mode", "button2_mode", "screensaver_mode",
                  "button1_detached_mode_room", "button2_detached_mode_room"):
        assert f'$("#{ident}").change(update_shown_elements)' in js
    # P309: the panel example drawing and its update function are deleted
    assert "update_nspanel_example_view" not in js
    for example in ("eu-panel-example", "us-panel-vertical-example",
                    "us-panel-horizontal-example", "us-panel-horizontal-mirrored-example"):
        assert example not in js


def test_settings_page_uses_the_same_behavior_single_source():
    edit_js = EDIT_JS.read_text()
    assert "function update_shown_elements()" not in edit_js
    assert "function update_nspanel_example_view()" not in edit_js
    assert "bindPanelSettingsBehavior();" in edit_js
    for page in (HTML, EDIT.read_text()):
        assert 'static/panel_settings.js?version={{ static_ver }}' in page


def test_studio_binds_the_behavior_after_injecting_the_form():
    fn = _between(HTML, "function loadPanelSettings", "function savePanelSettings")
    assert "box.innerHTML = t;" in fn
    assert fn.index("box.innerHTML = t;") < fn.index("bindPanelSettingsBehavior();")
    # the panel type drives the live device preview
    assert "typeSel.addEventListener('change', renderPreview)" in fn
    # switching sub-tabs re-evaluates the conditional controls
    sub = _between(HTML, "function setPanelSubTab", "function loadPanelSettings")
    assert "update_shown_elements()" in sub


def test_the_panel_drawing_and_background_selector_are_gone():
    """P309 (user: "you can remove the panel drawing from there, you can
    delete the code as well, is not used anymore") — the example drawing, its
    update function, the background-selector modal and every trigger are
    deleted; the background is chosen through the studio's photo gallery."""
    for text, label in ((FIELDS, "partial"), (HTML, "dashboard"), (EDIT.read_text(), "edit")):
        assert "eu-panel-example" not in text, label
        assert "us-panel-vertical-example" not in text, label
        assert "openBackgroundSelector" not in text, label
        assert "selected_tft" not in text, label
        assert "_background_selector_modal" not in text, label
    assert "update_nspanel_example_view" not in JS.read_text()
    assert not MODAL.exists(), "the background selector modal file must be deleted"
