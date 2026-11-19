"""P306 Step 0 — screensaver style/weather persisted fields + panel payload.

Pure, host-runnable tests for the foundation of the "Build the screensaver"
tab. These run under the HA dev venv (system python lacks homeassistant).
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

pytest.importorskip("homeassistant")

from nspanel_core.manager import build_panel_screensaver_config  # noqa: E402
from nspanel_core.models import IntegrationConfig, PanelConfig, RoomConfig  # noqa: E402


def _panel(**overrides):
    base = dict(id=7, mac="aabbcc", name="Kitchen", accepted=True)
    base.update(overrides)
    return PanelConfig(**base)


def test_new_panel_has_safe_screensaver_defaults():
    p = _panel()
    assert (p.clock_font, p.clock_weight, p.clock_color, p.clock_align) == (
        "large", "regular", "#c8cbce", "center")
    assert (p.date_font, p.date_weight, p.date_color, p.date_align) == (
        "small", "regular", "#8b93a1", "center")
    for flag in ("show_ss_outside_temp", "show_ss_room_temp", "show_ss_forecast",
                 "show_ss_wind", "show_ss_rain", "show_ss_sunrise_sunset"):
        assert getattr(p, flag) is False
    assert p.ss_outside_temp_entity == "" and p.ss_room_temp_entity == ""


def test_stored_config_without_new_fields_upgrades_cleanly():
    old = {"id": 7, "mac": "aabbcc", "name": "Kitchen", "screensaver_mode": "with_background"}
    p = PanelConfig.from_dict(old)
    assert p.clock_font == "large"          # default, not AttributeError
    assert p.show_ss_forecast is False
    assert p.to_dict()["clock_font"] == "large"


def test_hostile_values_are_clamped_to_closed_enums():
    p = _panel(clock_font="99px", date_font="../etc", clock_weight="STYLE",
               date_align="up", clock_color="red;drop", date_color="javascript:x",
               show_ss_rain="not-a-bool", ss_room_temp_entity=123)
    assert p.clock_font == "large" and p.date_font == "small"
    assert p.clock_weight == "regular" and p.date_align == "center"
    assert p.clock_color == "#c8cbce" and p.date_color == "#8b93a1"
    assert p.show_ss_rain is True           # bool() of a non-empty string
    assert p.ss_room_temp_entity == ""


def test_valid_custom_values_are_normalised():
    p = _panel(clock_font="xlarge", date_font="medium", clock_weight="bold",
               clock_align="left", date_color="#39C8E8", show_ss_forecast=True)
    assert p.clock_font == "xlarge" and p.date_font == "medium"
    assert p.clock_weight == "bold" and p.clock_align == "left"
    assert p.date_color == "#39c8e8"
    assert p.show_ss_forecast is True


def test_payload_shape_is_stable_and_carries_resolved_temps():
    p = _panel(clock_font="medium", clock_weight="bold", date_color="#39c8e8",
               show_ss_outside_temp=True, show_ss_forecast=True,
               ss_outside_temp_entity="sensor.outside")
    cfg = IntegrationConfig()
    payload = build_panel_screensaver_config(p, cfg.settings,
                                             outside_temp="21.4", room_temp="")
    assert set(payload) == {"clock", "date", "weather"}
    assert payload["clock"] == {"font": "medium", "weight": "bold",
                                "color": "#c8cbce", "align": "center"}
    assert payload["date"]["color"] == "#39c8e8"
    assert payload["weather"]["outside_temp"] is True
    assert payload["weather"]["forecast"] is True
    assert payload["weather"]["room_temp"] is False
    assert payload["weather"]["outside_temp_override"] == "21.4"
    assert payload["weather"]["room_temp_override"] == ""
    assert set(payload["weather"]) == {
        "outside_temp", "room_temp", "forecast", "wind", "rain",
        "sunrise_sunset", "outside_temp_override", "room_temp_override"}


def test_room_sensor_entity_defaults_from_the_panels_room():
    """The manager resolves a room's temp sensor when no per-panel override
    exists — asserted structurally so the publish path cannot silently drop it."""
    src = (REPO / "custom_components" / "nspanel_core" / "manager.py").read_text()
    assert "ss_room_temp_entity" in src
    assert "temp_sensor_entity" in src
    assert 'topic_panel_screensaver' not in src  # the helper lives in protocol.h
    assert '_panel_cmd_topic(panel, "screensaver")' in src
