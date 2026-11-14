"""P76 settings-form contract: the Save button died silently because the
form could never validate (brightness min=1 vs backend 0..100 at the
default 0, plus a required mqtt_server field the backend ignores and the
template always renders empty). These guards pin the contract both sides.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
import sys as _sys

_sys.path.insert(0, str(REPO / "custom_components"))
SETTINGS_HTML = (REPO / "custom_components" / "nspanel_core" / "ui" /
                 "templates" / "settings.html")
MANAGER = REPO / "custom_components" / "nspanel_core" / "manager.py"


def _backend_keys() -> set[str]:
    src = MANAGER.read_text(errors="replace")
    keys = set(re.findall(r'key == "([^"]+)"', src))
    for tup in re.findall(r'key in \((.*?)\)', src, re.S):
        keys.update(re.findall(r'"([^"]+)"', tup))
    return keys


def _required_names() -> set[str]:
    html = SETTINGS_HTML.read_text(errors="replace")
    names = set()
    for tag in re.finditer(r"<(?:input|select|textarea)[^>]*>", html):
        t = tag.group(0)
        if "required" not in t:
            continue
        m = re.search(r'name="([^"]+)"', t)
        if m:
            names.add(m.group(1))
    return names


def test_p76_brightness_zero_accepted():
    from nspanel_core.manager import NSPanelCoreManager

    clean, errors = NSPanelCoreManager.validate_settings(
        {"light_turn_on_brightness": "0"}, {})
    assert not errors, f"brightness 0 must validate: {errors}"
    assert clean["light_turn_on_brightness"] == 0
    clean, errors = NSPanelCoreManager.validate_settings(
        {"light_turn_on_brightness": "101"}, {})
    assert errors, "brightness 101 must be rejected"


def test_p76_no_required_field_renders_empty():
    """The exact Save-bricking mechanism: render settings.html with
    fresh-install defaults (GlobalSettings()) — every required input must
    carry a non-empty value, or the browser blocks submit for everyone."""
    import sys as _s

    _s.path.insert(0, str(REPO / "tests"))
    from test_templates import ENV, _base

    from nspanel_core.models import GlobalSettings

    s = GlobalSettings()
    out = ENV.get_template("settings.html").render(
        _base(
            manager_address=s.manager_address,
            manager_port=s.manager_port,
            mqtt_server=getattr(s, "mqtt_server", ""),
            mqtt_port=getattr(s, "mqtt_port", 1883),
            mqtt_username=getattr(s, "mqtt_username", ""),
            color_temp_min=s.color_temp_min,
            color_temp_max=s.color_temp_max,
            reverse_color_temp=s.reverse_color_temp,
            optimistic_mode=s.optimistic_mode,
            turn_on_behaviour=s.turn_on_behaviour,
            raise_to_100_light_level=0,
            light_turn_on_brightness=s.light_turn_on_brightness,
            min_button_push_time=50,
            button_long_press_time=400,
            special_mode_trigger_time=350,
            special_mode_release_time=600,
            screen_dim_level=100,
            screensaver_dim_level=20,
            screensaver_activation_timeout=15,
            max_live_log_messages=100,
            max_log_buffer_size=1000,
            room_status_backoff_time=0,
            all_rooms_status_backoff_time=0,
            screensaver_mode="with_background",
            rooms=[],
            auto_tft_updates=True,
        )
    )
    empty = []
    for tag in re.finditer(r"<input[^>]*>", out):
        t = tag.group(0)
        if "required" not in t:
            continue
        m = re.search(r'name="([^"]+)"', t)
        v = re.search(r'value="([^"]*)"', t)
        # Only config-backed fields (those WITH a value attribute): a
        # required field rendering value="" blocks submit for everyone
        # (the mqtt_server brick). Blank user-entry fields (Add room name:
        # no value attr, placeholder instead) are correctly left empty.
        if m and v is not None and v.group(1) == "":
            if 'type="checkbox"' in t or 'type="radio"' in t or 'type="submit"' in t:
                continue
            empty.append(m.group(1))
    assert not empty, (
        f"required inputs rendering empty (browser blocks Save): {empty}"
    )


def test_p76_brightness_min_matches_backend():
    m = re.search(r'name="light_turn_on_brightness"[^>]*min="(\d+)"',
                  SETTINGS_HTML.read_text(errors="replace"))
    assert m and m.group(1) == "0", (
        "brightness input min must be 0 to match backend 0..100"
    )
