"""Builders/parsers for the panel protobuf messages (wire-identical to the
generated code, zero dependencies). Only the messages the integration
actually uses are implemented."""

from __future__ import annotations

from .codec import (
    Reader,
    encode_bool_field,
    encode_float_field,
    encode_message_field,
    encode_packed_int32_field,
    encode_string_field,
    encode_varint,
    encode_varint_field,
)

# NSPanelConfig field numbers (protobuf_nspanel.proto)
def build_nspanel_config(p) -> bytes:
    """p: object exposing the NSPanelConfig fields (PanelConfig + rooms/pages)."""
    out = bytearray()
    out += encode_string_field(1, p["name"])
    if p.get("default_room"):
        out += encode_varint_field(2, p["default_room"])
    if p.get("default_page"):
        out += encode_varint_field(3, p["default_page"])
    if p.get("screensaver_activation_timeout"):
        out += encode_varint_field(4, p["screensaver_activation_timeout"])
    if p.get("min_button_push_time"):
        out += encode_varint_field(5, p["min_button_push_time"])
    if p.get("button_long_press_time"):
        out += encode_varint_field(6, p["button_long_press_time"])
    if p.get("special_mode_trigger_time"):
        out += encode_varint_field(7, p["special_mode_trigger_time"])
    if p.get("special_mode_release_time"):
        out += encode_varint_field(8, p["special_mode_release_time"])
    if p.get("screen_dim_level"):
        out += encode_varint_field(9, p["screen_dim_level"])
    if p.get("screensaver_dim_level"):
        out += encode_varint_field(10, p["screensaver_dim_level"])
    if p.get("screensaver_mode"):
        out += encode_varint_field(11, p["screensaver_mode"])
    if p.get("show_screensaver_inside_temperature"):
        out += encode_bool_field(12, True)
    if p.get("show_screensaver_outside_temperature"):
        out += encode_bool_field(13, True)
    if p.get("clock_us_style"):
        out += encode_bool_field(14, True)
    if p.get("use_fahrenheit"):
        out += encode_bool_field(15, True)
    if p.get("is_us_panel"):
        out += encode_bool_field(16, True)
    for room in p.get("room_infos", []):
        inner = bytearray()
        inner += encode_varint_field(1, room["room_id"])
        for pid in room.get("entity_page_ids", []):
            inner += encode_packed_int32_field(2, [pid])
        for sid in room.get("scene_page_ids", []):
            inner += encode_packed_int32_field(3, [sid])
        out += encode_message_field(17, bytes(inner))
    if p.get("reverse_relays"):
        out += encode_bool_field(18, True)
    if p.get("relay1_default_mode"):
        out += encode_bool_field(19, True)
    if p.get("relay2_default_mode"):
        out += encode_bool_field(20, True)
    if p.get("temperature_calibration"):
        out += encode_varint_field(21, p["temperature_calibration"])
    if p.get("button1_mode"):
        out += encode_varint_field(22, p["button1_mode"])
    if p.get("button2_mode"):
        out += encode_varint_field(25, p["button2_mode"])
    for gid in p.get("global_scene_entity_page_ids", []):
        out += encode_packed_int32_field(30, [gid])
    if p.get("optimistic_mode"):
        out += encode_bool_field(31, True)
    if p.get("raise_light_level_to_100_above"):
        out += encode_varint_field(32, p["raise_light_level_to_100_above"])
    out += encode_varint_field(33, p["nspanel_id"])
    for rid in p.get("relay1_relay_group", []):
        out += encode_packed_int32_field(35, [rid])
    for rid in p.get("relay2_relay_group", []):
        out += encode_packed_int32_field(37, [rid])
    if p.get("default_light_brightess"):
        out += encode_varint_field(38, p["default_light_brightess"])
    if p.get("locked_to_default_room"):
        out += encode_bool_field(39, True)
    if p.get("inside_temperature_sensor_mqtt_topic"):
        out += encode_string_field(40, p["inside_temperature_sensor_mqtt_topic"])
    if p.get("button1_lower_temperature"):
        out += encode_varint_field(41, p["button1_lower_temperature"])
    if p.get("button1_upper_temperature"):
        out += encode_varint_field(42, p["button1_upper_temperature"])
    if p.get("button2_lower_temperature"):
        out += encode_varint_field(43, p["button2_lower_temperature"])
    if p.get("button2_upper_temperature"):
        out += encode_varint_field(44, p["button2_upper_temperature"])
    return bytes(out)


# NSPanelRoomStatus
def build_nspanel_room_status(p) -> bytes:
    out = bytearray()
    if p.get("id"):
        out += encode_varint_field(1, p["id"])
    out += encode_string_field(2, p.get("name", ""))
    for field, key in (
        (3, "average_dim_level"),
        (4, "ceiling_lights_dim_level"),
        (5, "table_lights_dim_level"),
        (6, "average_color_temperature"),
        (7, "ceiling_lights_color_temperature_value"),
        (8, "table_lights_color_temperature_value"),
        (9, "num_ceiling_lights"),
        (10, "num_table_lights"),
        (11, "num_ceiling_lights_on"),
        (12, "num_table_lights_on"),
    ):
        if p.get(key):
            out += encode_varint_field(field, p[key])
    for pid in p.get("entity_page_ids", []):
        out += encode_packed_int32_field(13, [pid])
    return bytes(out)


# NSPanelRoomEntitiesPage.EntitySlot
def _build_entity_slot(p) -> bytes:
    out = bytearray()
    if p.get("room_view_position"):
        out += encode_varint_field(1, p["room_view_position"])
    out += encode_string_field(2, p.get("name", ""))
    if p.get("icon"):
        out += encode_string_field(3, p["icon"])
    if p.get("pco"):
        out += encode_varint_field(4, p["pco"])
    if p.get("pco2"):
        out += encode_varint_field(5, p["pco2"])
    if p.get("can_save_scene"):
        out += encode_bool_field(6, True)
    if p.get("mqtt_state_topic"):
        out += encode_string_field(7, p["mqtt_state_topic"])
    return bytes(out)


def build_nspanel_room_entities_page(p) -> bytes:
    out = bytearray()
    if p.get("id"):
        out += encode_varint_field(1, p["id"])
    if p.get("page_type"):
        out += encode_varint_field(2, p["page_type"])
    out += encode_string_field(3, p.get("header_text", ""))
    for slot in p.get("entities", []):
        out += encode_message_field(4, _build_entity_slot(slot))
    return bytes(out)


# NSPanelEntityState.Light
def build_nspanel_entity_state_light(p) -> bytes:
    light = p["light"]
    out = bytearray()
    if light.get("light_id"):
        out += encode_varint_field(1, light["light_id"])
    out += encode_string_field(2, light.get("name", ""))
    if light.get("brightness"):
        out += encode_varint_field(3, light["brightness"])
    if light.get("color_temp"):
        out += encode_varint_field(4, light["color_temp"])
    if light.get("hue"):
        out += encode_varint_field(5, light["hue"])
    if light.get("saturation"):
        out += encode_varint_field(6, light["saturation"])
    if light.get("can_color_temp"):
        out += encode_bool_field(7, True)
    if light.get("can_color"):
        out += encode_bool_field(8, True)
    if light.get("current_light_mode"):
        out += encode_varint_field(9, light["current_light_mode"])
    if light.get("state"):
        out += encode_bool_field(10, True)
    state = bytearray()
    state += encode_message_field(1, bytes(out))
    return bytes(state)


# NSPanelEntityState.Thermostat
def _build_thermostat_option_value(p) -> bytes:
    out = bytearray()
    out += encode_string_field(1, p.get("value", ""))
    if p.get("icon"):
        out += encode_string_field(2, p["icon"])
    return bytes(out)


def _build_thermostat_option(p) -> bytes:
    out = bytearray()
    out += encode_string_field(1, p.get("name", ""))
    if p.get("current_value"):
        out += encode_string_field(2, p["current_value"])
    if p.get("current_icon"):
        out += encode_string_field(3, p["current_icon"])
    for opt in p.get("options", []):
        out += encode_message_field(4, _build_thermostat_option_value(opt))
    return bytes(out)


def build_nspanel_entity_state_thermostat(p) -> bytes:
    th = p["thermostat"]
    out = bytearray()
    if th.get("thermostat_id"):
        out += encode_varint_field(1, th["thermostat_id"])
    out += encode_string_field(2, th.get("name", ""))
    if th.get("has_current_temperature"):
        out += encode_float_field(3, th.get("current_temperature", 0.0))
        out += encode_bool_field(4, True)
    if th.get("set_temperature"):
        out += encode_float_field(5, th["set_temperature"])
    if th.get("step_size"):
        out += encode_float_field(6, th["step_size"])
    for opt in th.get("options", []):
        out += encode_message_field(7, _build_thermostat_option(opt))
    state = bytearray()
    state += encode_message_field(2, bytes(out))
    return bytes(state)


# NSPanelWeatherUpdate
def _build_forecast_item(p) -> bytes:
    out = bytearray()
    out += encode_string_field(1, p.get("weather_icon", ""))
    out += encode_string_field(2, p.get("precipitation_string", ""))
    out += encode_string_field(3, p.get("temperature_maxmin_string", ""))
    out += encode_string_field(4, p.get("wind_string", ""))
    if p.get("display_string"):
        out += encode_string_field(5, p["display_string"])
    return bytes(out)


def build_nspanel_weather_update(p) -> bytes:
    out = bytearray()
    for item in p.get("forecast_items", []):
        out += encode_message_field(1, _build_forecast_item(item))
    out += encode_string_field(2, p.get("current_weather_icon", ""))
    out += encode_string_field(3, p.get("current_temperature_string", ""))
    out += encode_string_field(4, p.get("current_maxmin_temperature", ""))
    out += encode_string_field(5, p.get("current_wind_string", ""))
    out += encode_string_field(6, p.get("sunrise_string", ""))
    out += encode_string_field(7, p.get("sunset_string", ""))
    out += encode_string_field(8, p.get("current_precipitation_string", ""))
    return bytes(out)


# ------------------------------------------------------------------
# Decoding: NSPanelMQTTManagerCommand
# ------------------------------------------------------------------

def _decode_light_command(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {"light_ids": []}
    while not r.eof():
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            # packed repeated int32: raw varints, no tags
            pr = Reader(r.read_bytes())
            while not pr.eof():
                out["light_ids"].append(pr.read_varint())
        elif field == 1 and wt == 0:
            out["light_ids"].append(r.read_varint())
        elif wt == 0:
            out[{
                2: "has_brightness",
                3: "brightness",
                4: "has_color_temperature",
                5: "color_temperature",
                6: "has_hue",
                7: "hue",
                8: "has_saturation",
                9: "saturation",
            }.get(field, f"light_{field}")] = r.read_varint()
        elif wt == 2:
            r.read_bytes()
        elif wt == 5:
            r.read_float()
    return out


def _decode_toggle_entity(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {}
    while not r.eof():
        field, wt = r.read_tag()
        if wt == 0:
            out[{1: "entity_page_id", 2: "entity_slot"}.get(field, f"f{field}")] = r.read_varint()
        elif wt == 2:
            r.read_bytes()
    return out


def _decode_first_page(data: bytes, is_on: bool) -> dict:
    r = Reader(data)
    out: dict = {}
    prefix = "first_page_turn_on" if is_on else "first_page_turn_off"
    keys = {
        1: f"{prefix}_affect_lights",
        2: "brightness_slider_value",
        3: "kelvin_slider_value",
        4: "selected_room",
    }
    if is_on:
        keys.update({5: "global", 6: "has_brightness_value", 7: "has_kelvin_value"})
    else:
        keys.update({2: "global"})
    while not r.eof():
        field, wt = r.read_tag()
        if wt == 0:
            out[keys.get(field, f"f{field}")] = r.read_varint()
        elif wt == 2:
            r.read_bytes()
    return out


def _decode_button_pressed(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {}
    while not r.eof():
        field, wt = r.read_tag()
        if field == 2 and wt == 0:
            out["button_id"] = r.read_varint()
        elif wt == 2:
            r.read_bytes()
    return out


def _decode_thermostat_temperature(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {}
    while not r.eof():
        field, wt = r.read_tag()
        if field == 1 and wt == 0:
            out["thermostat_id"] = r.read_varint()
        elif field == 2 and wt == 5:
            out["temperature"] = r.read_float()
        elif wt == 2:
            r.read_bytes()
    return out


def _decode_thermostat_command(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {}
    while not r.eof():
        field, wt = r.read_tag()
        if wt == 0:
            out[{1: "thermostat_id"}.get(field, f"f{field}")] = r.read_varint()
        elif wt == 2:
            value = r.read_bytes()
            out[{2: "option", 3: "new_value"}.get(field, f"f{field}")] = value.decode("utf-8", "replace")
        elif wt == 5:
            r.read_float()
    return out


def _decode_save_scene(data: bytes) -> dict:
    return _decode_toggle_entity(data)


def parse_nspanel_mqttmanager_command(data: bytes) -> dict:
    """Returns {'kind': <oneof name>, **payload} mirroring the oneof."""
    r = Reader(data)
    result: dict = {}
    while not r.eof():
        field, wt = r.read_tag()
        if wt == 2:
            payload = r.read_bytes()
            if field == 1:
                result = {"kind": "first_page_turn_on", **_decode_first_page(payload, True)}
            elif field == 2:
                result = {"kind": "first_page_turn_off", **_decode_first_page(payload, False)}
            elif field == 3:
                result = {"kind": "light_command", **_decode_light_command(payload)}
            elif field == 4:
                result = {"kind": "toggle_entity_from_entities_page", **_decode_toggle_entity(payload)}
            elif field == 5:
                result = {"kind": "save_scene_command", **_decode_save_scene(payload)}
            elif field == 6:
                result = {"kind": "button_pressed", **_decode_button_pressed(payload)}
            elif field == 7:
                result = {"kind": "thermostat_temperature_command", **_decode_thermostat_temperature(payload)}
            elif field == 8:
                result = {"kind": "thermostat_command", **_decode_thermostat_command(payload)}
        elif wt == 0:
            if field == 100:
                result["nspanel_id"] = r.read_varint()
            else:
                r.read_varint()
        elif wt == 5:
            r.read_float()
    return result


def parse_nspanel_status_report(data: bytes) -> dict:
    r = Reader(data)
    out: dict = {"warnings": []}

    def as_int32(value: int) -> int:
        value &= 0xFFFFFFFF
        return value - 0x100000000 if value >= 0x80000000 else value

    int32_fields = {1: "nspanel_state", 2: "update_progress", 3: "rssi", 4: "heap_used_pct"}
    float_fields = {6: "temperature", 13: "humidity", 15: "pressure"}
    while not r.eof():
        field, wt = r.read_tag()
        if wt == 0:
            value = r.read_varint()
            if field in int32_fields:
                out[int32_fields[field]] = as_int32(value)
            else:
                out[{12: "has_humidity", 14: "has_pressure"}.get(field, f"f{field}")] = value
        elif wt == 5:
            out[float_fields.get(field, f"f{field}")] = r.read_float()
        elif wt == 2:
            payload = r.read_bytes()
            if field == 5:
                out["mac_address"] = payload.decode("utf-8", "replace")
            elif field == 7:
                out["ip_address"] = payload.decode("utf-8", "replace")
            elif field == 8:
                out["warnings"].append({"raw": payload.hex()})
            elif field == 9:
                out["md5_firmware"] = payload.decode("utf-8", "replace")
            elif field == 10:
                out["md5_littlefs"] = payload.decode("utf-8", "replace")
            elif field == 11:
                out["md5_tft_gui"] = payload.decode("utf-8", "replace")
    return out
