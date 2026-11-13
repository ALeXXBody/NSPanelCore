"""Regression tests: every UI template renders with realistic context.

Run with an HA dev venv (templates import nothing from HA, but the suite
runs together):
    /tmp/opencode/ha-venv-2611/bin/python -m pytest tests/test_templates.py -v

Catches UndefinedError from missing context keys, renamed model fields,
and string-vs-bool comparisons that silently render wrong selections.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

REPO = Path(__file__).resolve().parent.parent
ENV = Environment(
    loader=FileSystemLoader(str(REPO / "custom_components" / "nspanel_core" / "ui" / "templates"))
)
ENV.globals["RC"] = lambda *a, **k: ""


def _base(**kw):
    ctx = dict(
        request=SimpleNamespace(path="/ui"),
        version="vX",
        nspanels=[],
        notifications=[],
        has_unread_messages=False,
        mqtt_password="",
        home_assistant_token="",
        mqtt_server="",
        mqtt_port=1883,
        mqtt_username="",
        room=None,
        enabled_themes={},
        theme="nspmwip",
        current_theme="nspmwip",
        theme_mode="dark",
        ingress_path="",
        manager_address="",
        manager_port=8000,
    )
    ctx.update(kw)
    return ctx


def _panel(**kw):
    d = dict(
        id=1, name="Kitchen Panel", mac="aabbcc", wifi_hostname="KitchenPanel",
        button1_mode=1, button2_mode=2, button1_detached_light=5,
        button2_detached_light=0, button1_detached_room=3, button2_detached_room=1,
        reverse_relays=False, relay1_default_mode=True, relay2_default_mode=False,
        relay1_is_light=True, relay2_is_light=False, lock_to_default_room=True,
        is_us_panel=False, us_panel_orientation="", room_id=1, rooms=[],
        friendly_name="K", mac_address="x", room={"id": 1},
        button1_detached_mode_entity=None, button2_detached_mode_entity=None,
        show_home_scenes=True, show_home_ceiling=True, show_home_table=True,
        show_home_kelvin=True, screensaver_mode="global", default_page=2,
        temperature_calibration=0.0,
    )
    d.update(kw)
    return d


def test_edit_panel_renders_with_truthy_checks():
    import re

    pd = _panel()
    rooms = [SimpleNamespace(id=1, friendly_name="Living"), SimpleNamespace(id=3, friendly_name="Bed")]
    lights = [{"id": 5, "name": "Ceiling", "ha_entity": "light.x", "room_id": 3}]
    out = ENV.get_template("edit_nspanel.html").render(
        _base(
            panel_info={"data": pd},
            nspanel={"data": pd},
            settings=dict(pd, selected_tft=""),
            rooms=rooms,
            lights=lights,
            page_title="t",
            temperature_unit="celsius",
            current_temperature=0,
            current_humidity=0,
            current_pressure=0,
            current_wifi_signal_strength=0,
            current_ram_usage=0,
        )
    )
    assert 'value="5" selected' in out  # detached light pre-selected
    m = re.search(r'<select name="button1_detached_mode_room".*?</select>', out, re.S)
    assert m and 'value="3" selected' in m.group(0)  # detached room pre-selected
    assert 'Thermostat' not in out  # no invalid button modes 4/5 (light id 5 legitimately renders value="5")
    m = re.search(r'id="us-panel-vertical-example"[^>]*>', out)
    assert m and "hidden" in m.group(0)  # EU panel hides US preview


def test_settings_renders_with_auto_tft():
    out = ENV.get_template("settings.html").render(
        _base(
            default_nspanel_type="sonoff",
            auto_tft_updates=True,
            color_temp_min=2700,
            color_temp_max=6500,
            reverse_color_temp=False,
            optimistic_mode=False,
            turn_on_behaviour="color_temp",
            turn_on_behavior="color_temp",
            turn_on_light_behaviour="color_temp",
            home_assistant_address="",
            raise_to_100_light_level=0,
            min_button_push_time=50,
            button_long_press_time=400,
            special_mode_trigger_time=350,
            special_mode_release_time=600,
            screensaver_activation_timeout=15,
            screen_dim_level=100,
            screensaver_dim_level=20,
            screensaver_mode="with_background",
            light_turn_on_brightness=0,
            room_status_backoff_time=0,
            all_rooms_status_backoff_time=0,
            max_live_log_messages=100,
            max_log_buffer_size=1000,
            is_home_assistant_addon=True,
            rooms=[],
            themes={"nspmwip": "x"},
            page_title="Settings",
        )
    )
    assert "Auto-install on register" in out
    assert "modal_confirm" in out  # modals.html included, not the empty stub


def test_weather_renders_stored_values():
    out = ENV.get_template("weather_and_time.html").render(
        _base(
            location_latitude="51.5",
            location_longitude="-0.1",
            weather_update_interval=20,
            clock_us_style=False,
            date_format="%d/%m",
            use_fahrenheit=False,
            precipitation_format="mm",
            wind_speed_format="kn",
            outside_temp_provider="",
            outside_temp_sensor="",
            page_title="W",
        )
    )
    assert 'value="20"' in out  # stored interval, not empty
    assert 'value="knots"' in out


def test_all_templates_render():
    import re

    cases = {
        "denied_nspanels.html": _base(
            nspanels=[{"denied": True, "name": "X", "mac": "m", "id": 1}], page_title="D"),
        "index_htmx_nspanels_section.html": _base(),
        "rooms.html": _base(rooms=[], page_title="R"),
        "relay_groups.html": _base(relay_groups=[], page_title="G"),
        "index_htmx.html": _base(page_title="I"),
        "global_scenes.html": _base(scenes=[], page_title="G"),
        "about.html": _base(page_title="A"),
        "manager_settings.html": _base(page_title="M"),
        "base.html": _base(),
        "navbar.html": _base(),
    }
    qs = SimpleNamespace(
        id=1, friendly_name="R", name="R", nspanel_set=SimpleNamespace(all=[]),
        entity_set=SimpleNamespace(all=[]), room_temp_provider="", room_temp_sensor="")
    cases["edit_room.html"] = _base(
        room=qs, rooms=[], nspanels=[], total_num_rooms=1, entity_pages=[], page_title="E")
    for tpl, ctx in cases.items():
        ENV.get_template(tpl).render(ctx)  # raises on UndefinedError
    assert re.search(r"upload_tft_modal\.showModal", cases["navbar.html"] and
                    ENV.get_template("navbar.html").render(_base()))
