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
                 "templates" / "_tab_general.html")
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
            active_tab="general",
            nspanels=[],
            manager_address=s.manager_address,
            manager_port=s.manager_port,
            color_temp_min=s.color_temp_min,
            color_temp_max=s.color_temp_max,
            reverse_color_temp=s.reverse_color_temp,
            screensaver_dim_level=20,
            screensaver_activation_timeout=15,
            screensaver_mode="with_background",
            rooms=[],
            auto_tft_updates=True,
            # weather tab fields (rendered as tabs since P236)
            location_latitude=s.location_latitude,
            location_longitude=s.location_longitude,
            weather_update_interval=s.weather_update_interval,
            clock_us_style=s.clock_us_style,
            date_format=s.date_format,
            use_fahrenheit=s.use_fahrenheit,
            precipitation_format=s.precipitation_format,
            wind_speed_format=s.wind_speed_format,
            outside_temp_provider=s.outside_temp_provider,
            outside_temp_sensor=s.outside_temp_sensor_entity,
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



def test_p361_removed_fields_have_no_inputs():
    """P361: the dead GlobalSettings fields were removed (no consumer); the
    settings page must not render inputs the backend ignores."""
    html = SETTINGS_HTML.read_text(errors="replace")
    for name in ("light_turn_on_brightness", "optimistic_mode",
                 "turn_on_behaviour", "mqtt_wait_time", "mqtt_server",
                 "mqtt_password", "home_assistant_address"):
        assert name not in html, f"the removed field {name} still renders an input"
