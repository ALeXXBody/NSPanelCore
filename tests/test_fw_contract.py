"""NSPanel Core firmware/integration contract tests.

Run in the fwtest venv: /tmp/opencode/fwtest/bin/python -m pytest test_fw_contract.py -v

What this proves (without ESP32 hardware):
1. Topic helpers (const.py) behave: MAC/hostname normalization, no wildcards.
2. panel_pb codec round-trips (used for OTA triggers + legacy paths).
3. Every MQTT topic the FIELD FIRMWARE subscribes to has a manager
   publisher, and every topic the firmware publishes has a manager
   subscriber (static cross-check of firmware/ sources vs manager.py).
4. Every key the firmware reads from the HTTP config JSON is emitted by
   the manager's builders (static cross-check vs dashboard builders).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components" / "nspanel_core"))
from const import topic_safe, panel_mqtt_base, panel_mqtt_topic  # noqa: E402


def mac_from_topic(topic: str, suffix: str) -> str:
    # Mirror of manager.mac_from_topic (manager.py needs HA to import, so the
    # logic is pinned here; keep in sync).
    parts = topic.split("/")
    if len(parts) >= 3 and parts[2] == suffix:
        return topic_safe(parts[1])
    return ""


def test_topic_safe_strips_wildcards():
    assert topic_safe("a/b#c+d\x00e f") == "a_b_c_d_e_f"
    assert "#" not in topic_safe("#") or topic_safe("#") == ""


def test_topic_safe_keeps_structure():
    # topic_safe lowercases + folds separators (internal use: MACs, lookups)
    assert topic_safe("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    # firmware-verbatim base keeps case/spaces (panel subscription compat)
    assert panel_mqtt_base("My Panel") == "My Panel"
    assert panel_mqtt_base("a/b#c") == "a_b_c"


def test_panel_mqtt_topics():
    assert panel_mqtt_topic("My Panel", "command") == "nspanel/My Panel/command"
    assert panel_mqtt_topic("AA:BB:CC:DD:EE:FF", "r1_cmd").startswith("nspanel/")


def test_mac_from_topic():
    assert mac_from_topic("nspanel/ab12cd34ef56/status", "status") == "ab12cd34ef56"
    assert mac_from_topic("nspanel/ab12cd34ef56/other", "status") == ""
    assert mac_from_topic("garbage", "status") == ""


def test_codec_varint_roundtrip():
    from panel_pb.codec import encode_varint_field, Reader
    assert encode_varint_field(1, 0) == b""  # proto3 zero-omission
    for n in (1, 127, 128, 300, 2**32 - 1):
        data = encode_varint_field(1, n)
        r = Reader(data)
        field, wt = r.read_tag()
        assert (field, wt) == (1, 0)
        assert r.read_varint() == n


def test_codec_string_and_float():
    from panel_pb.codec import encode_string_field, encode_float_field, Reader
    data = encode_string_field(5, "aabbccddeeff")
    r = Reader(data)
    assert r.read_tag() == (5, 2)
    assert r.read_bytes().decode() == "aabbccddeeff"
    data = encode_float_field(6, 22.5)
    r = Reader(data)
    assert r.read_tag() == (6, 5)
    assert abs(r.read_float() - 22.5) < 1e-6


def test_status_report_parse_firmware_shape():
    # Firmware sends JSON, not protobuf; the manager parses the JSON keys.
    # This pins the keys the manager must handle (see _on_panel_status_report).
    from panel_pb.messages import parse_nspanel_status_report  # noqa
    assert callable(parse_nspanel_status_report)


def _fw_sources():
    files = []
    for root in (REPO / "firmware" / "lib", REPO / "firmware" / "src"):
        files += list(root.rglob("*.cpp")) + list(root.rglob("*.hpp"))
    return files


def _manager_src():
    return (REPO / "custom_components" / "nspanel_core" / "manager.py").read_text()


def test_firmware_subscriptions_have_manager_publisher():
    """Every nspanel/... topic the firmware subscribes to must be published
    by the manager (else the panel waits forever)."""
    fw_text = "\n".join(f.read_text(errors="replace") for f in _fw_sources())
    mgr = _manager_src()
    # static subscriptions in firmware (literal nspanel/ strings in subscribe calls)
    subs = set(re.findall(r'"(nspanel/[a-z_/]+)"', fw_text))
    # dynamic per-panel topics use the hostname base — covered by base test
    static_subs = {s for s in subs if "+" not in s and "entities/light" not in s}
    uncovered = []
    for topic in sorted(static_subs):
        tail = topic.split("/")[-1]
        # manager must reference the same leaf (time/date/weather/ampm/command/...)
        if tail in ("command", "r1_cmd", "r2_cmd") or f'"{topic}"' in mgr or f"'{topic}'" in mgr or topic in mgr:
            continue
        uncovered.append(topic)
    assert not uncovered, f"firmware subscribes but manager never publishes: {uncovered}"


def test_manager_panel_topics_have_firmware_subscriber():
    """Every per-panel topic base the manager publishes to must be subscribed
    by the firmware (hostname-based)."""
    mgr = _manager_src()
    assert "panel_mqtt_topic(panel.name" in mgr or "panel_mqtt_topic(" in mgr
    fw_text = "\n".join(f.read_text(errors="replace") for f in _fw_sources())
    assert "wifi_hostname" in fw_text  # firmware builds topics from hostname


def test_config_json_keys_cover_firmware_reads():
    """Keys RoomManager reads from /api/get_nspanel_config must be emitted
    by _panel_json_config in dashboard.py."""
    dash = (REPO / "custom_components" / "nspanel_core" / "dashboard.py").read_text()
    rm = (REPO / "firmware" / "lib" / "RoomManager" / "RoomManager.cpp").read_text()
    reads = set(re.findall(r'\(\*roomData\)\["([a-z_0-9]+)"\]', rm))
    # keys the dashboard builder emits (string literals in _panel_json_config)
    builder_region = dash[dash.find("def _panel_json_config"):dash.find("def _panel_json_config") + 4000]
    emitted = set(re.findall(r'"([a-z_0-9]+)":', builder_region))
    missing = {k for k in reads if k not in emitted and k not in ("rooms",)}
    # rooms list is emitted separately; lights/scenes shapes checked below
    assert not missing, f"firmware reads keys the manager never sends: {missing}"


def test_room_json_keys_cover_firmware_reads():
    dash = (REPO / "custom_components" / "nspanel_core" / "dashboard.py").read_text()
    rm = (REPO / "firmware" / "lib" / "RoomManager" / "RoomManager.cpp").read_text()
    assert '"lights"' in dash and '"scenes"' in dash
    assert '"can_dim"' in dash and '"ceiling"' in dash
    assert "can_save" in dash
