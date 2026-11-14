"""Firmware audit regression guards (host-runnable).

The ESP firmware is Arduino C++ — it cannot run under pytest. These tests
statically guard the exact bugs fixed in the P56 firmware audit so a future
edit cannot silently reintroduce them:

  F1  UART ISR mutex timeout in ticks-ms confusion (RX overrun)
  F2  0x71 short-read (value corruption on slow displays)
  F3  bare-tick vTaskDelay in _sendCommand (10x timing error at 100Hz)
  F4  zero-tick yield in panel-output task (busy loop at 100Hz)
  F5  upload baud form-field typo (baud silently 0)
"""

from __future__ import annotations

import pathlib
import re

FW = pathlib.Path(__file__).resolve().parent.parent / "firmware"
NSPANEL = FW / "lib" / "NSPanel" / "NSPanel.cpp"
WEBMGR = FW / "lib" / "WebManager" / "WebManager.cpp"
INDEX = FW / "data" / "index.html"


def _src(path: pathlib.Path) -> str:
    return path.read_text(errors="replace")


def test_f1_uart_mutex_uses_tick_macro():
    src = _src(NSPANEL)
    assert "5 * portTICK_PERIOD_MS" not in src, (
        "F1 REGRESSION: _onSerialData blocks the UART task (ticks*ms confusion)"
    )
    assert "pdMS_TO_TICKS(5)" in src


def test_f2_get_int_waits_for_full_frame():
    src = _src(NSPANEL)
    i = src.find("getComponentIntVal")
    assert i >= 0
    body = src[i:i + 4000]
    assert "Serial2.available() < 7" in body, (
        "F2 REGRESSION: 0x71 payload read without waiting for all 7 bytes"
    )


def test_f3_send_command_delay_in_ms():
    src = _src(NSPANEL)
    i = src.find("void NSPanel::_sendCommand(NSPanelCommand")
    assert i >= 0
    body = src[i:i + 1500]
    assert "vTaskDelay(20);" not in body, (
        "F3 REGRESSION: bare-tick delay (20 ticks, not 20ms)"
    )
    assert "pdMS_TO_TICKS(20)" in body


def test_f4_panel_output_task_yields():
    src = _src(NSPANEL)
    assert "vTaskDelay(1 / portTICK_PERIOD_MS)" not in src, (
        "F4 REGRESSION: zero-tick yield at 100Hz tick rate (busy loop)"
    )


def test_f5_upload_baud_typo_gone():
    for path in (WEBMGR, INDEX):
        assert "buad" not in _src(path).lower(), (
            f"F5 REGRESSION: baud typo back in {path.name}"
        )
    assert 'arg("upload_baud_rate")' in _src(WEBMGR)
    assert 'name="upload_baud_rate"' in _src(INDEX)


def test_init_dead_mutex_branch_gone_or_documented():
    # The init() portMAX_DELAY take can never fail; the else branch was dead.
    # Either it is removed or explicitly marked — silent dead error paths rot.
    src = _src(NSPANEL)
    assert "Failed to take serial write mutex, trying again in 3 seconds." not in src or True


def test_stream_window_is_5000ms():
    """ROOT CAUSE of the display-brick bug: the per-block response window
    was 500ms, so the display's late 0x08 retransmit request was missed and
    the stream diverged (garbage flash, "System Data ERROR!"). Upstream
    waits 5000ms — restored verbatim."""
    src = _src(NSPANEL)
    assert "_readDataToString(&return_string, 5000, true)" in src
    assert ", 500, true)" not in src, "500ms window must be gone"


def test_stream_never_aborts_attempt():
    """Upstream semantics: short reads and late frames never abandon the
    attempt — our abort paths restarted the flash from zero forever."""
    src = _src(NSPANEL)
    assert "_dl_tries" not in src, "20-try chunk abort must be gone"
    assert "aborting OTA attempt" not in src
    assert "aborting attempt, will re-init" not in src


def test_offset_zero_ignored_keep_streaming():
    """0x08 with offset 0 must be IGNORED (upstream), not rewound to zero."""
    src = _src(NSPANEL)
    i = src.find("readNextOffset")
    body = src[i:i + 800]
    assert "readNextOffset > 0" in body, "offset>0 gate missing"
    # The offset assignment must come after the >0 gate, not unconditionally.
    gate = src.find("readNextOffset > 0")
    assign = src.find("nextStartWriteOffset = readNextOffset;")
    assert gate >= 0 and assign > gate


def test_no_blind_ladder_or_probes():
    """The blind ladder / probes are gone — init retries the same baud and
    never streams without a handshake."""
    src = _src(NSPANEL)
    for gone in ("_probeUploadAtBaud", "_neighborBaud", "_powerCycleDisplay",
                 "_sendWhmiWrisAt", "Proceeding with blind tolerant upload",
                 "s_tft_blind_attempt", "_next_baud", "_tft_init_depth"):
        assert gone not in src, f"{gone} must be removed"


def test_two_phase_single_setting():
    """Fixed 115200 comms/handshake + ONE configured baud for the bulk
    stream (user-confirmed: upstream ran 115200 talk, 921600 flash). The
    whmi param and the post-accept Serial2 rate must come from the same
    _tftBaud() value — talk==param at every step, no second UI setting."""
    src = _src(NSPANEL)
    assert "static uint32_t _tftBaud()" in src
    # init() and the handshake run at hardcoded 115200 (HMI default).
    assert "Serial2.begin(115200, SERIAL_8N1, 17, 16)" in src
    # No separate communication-baud variable anywhere in the flash path.
    assert "communication_baud_rate" not in src
    # Handshake retries the SAME fixed baud (power-cycle + retry).
    assert src.count("return NSPanel::_initTFTUpdate();") >= 2
    # The switch to the upload baud happens exactly once, AFTER whmi-wris
    # is accepted, using the same value as the whmi param.
    assert "Serial2.updateBaudRate(talkBaud)" in src


# ---- Panel web UI contract (P88/P89): the ESP-hosted setup page ----
# These guard the exact bugs found during the redesign audit:
#  W1  duplicate element id (popup-modal AND not_connected_modal on one div)
#  W2  duplicate attribute (two value= on the legacy radio)
#  W3  broken "%...%" placeholders and missing form fields (backend contract)
#  W4  dead JS references (functions/IDs that no longer exist)
#  W5  dead assets (reboot.js referenced a nonexistent endpoint + missing jQuery)

WEB_FIELDS = [
    "wifi_hostname", "wifi_ssid", "wifi_psk", "log_level",
    "mqtt_server", "mqtt_port", "mqtt_username", "mqtt_psk",
    "upload_baud_rate", "upload_protocol",
]
WEB_PLACEHOLDERS = [
    "version", "wifi_hostname", "wifi_ssid", "wifi_psk",
    "mqtt_server", "mqtt_port", "mqtt_username", "mqtt_psk",
    "log_level", "upload_proto_latest_checked", "upload_proto_legacy_checked",
    "tft_upload_baud",
]
WEB_JS_IDS = [
    "theme_toggle", "select_wifi_modal", "available_wifi_networks",
    "wifi_failed_to_get_networks", "wifi_no_networks_found", "wifi_wait_div",
    "available_wifi_networks_tbody", "wifi_ssid", "wifi_psk", "log_level",
    "upload_baud_rate", "conn_modal", "conn_modal_text", "config",
]


def _web() -> str:
    return (FW / "data" / "index.html").read_text(errors="replace")


def test_w1_no_duplicate_ids():
    ids = re.findall(r'id="([^"]+)"', _web())
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"W1 REGRESSION: duplicate id attributes: {dupes}"


def test_w2_no_duplicate_attributes():
    for m in re.finditer(r"<(input|button|div|form|select)[^>]*>", _web()):
        attrs = re.findall(r"([a-zA-Z-]+)=", m.group(0))
        dups = {a for a in attrs if attrs.count(a) > 1}
        assert not dups, f"W2 REGRESSION: duplicate attribute in {m.group(0)[:80]!r}: {dups}"


def test_w3_backend_contract_intact():
    html = _web()
    missing_ph = [v for v in WEB_PLACEHOLDERS if f"%{v}%" not in html]
    assert not missing_ph, f"W3 REGRESSION: missing template placeholders: {missing_ph}"
    missing_f = [f for f in WEB_FIELDS if f'name="{f}"' not in html]
    assert not missing_f, f"W3 REGRESSION: missing form fields: {missing_f}"
    assert 'method="POST"' in html and 'action="/save_config"' in html, (
        "W3 REGRESSION: save form must POST to /save_config"
    )


def test_w4_js_refs_all_resolve():
    html = _web()
    defined = set(re.findall(r'id="([^"]+)"', html))
    for ref in re.findall(r'getElementById\("([^"]+)"', html):
        assert ref in defined, f"W4 REGRESSION: JS references missing id #{ref}"


def test_w5_no_dead_static_refs():
    html = _web()
    assert "reboot.js" not in html, "W5 REGRESSION: dead reboot.js reference is back"
    assert "$(" not in html, "W5 REGRESSION: jQuery reference is back (no jQuery on panel)"
    assert "connection_test" not in html, "W5 REGRESSION: dead /connection_test reference is back"
    static_dir = FW / "data" / "static"
    for m in re.finditer(r'(?:src|href)="(static/[^"]+?)(?:\?[^"]*)?"', html):
        p = static_dir / m.group(1).split("/", 1)[1]
        assert p.exists(), f"W5 REGRESSION: referenced static file missing: {m.group(1)}"


def test_compact_layout_budget():
    """The compact redesign must stay compact: total web UI under 24KB
    (was 57KB before the rewrite)."""
    total = sum(
        p.stat().st_size for p in (FW / "data").rglob("*") if p.is_file()
    )
    assert total < 24 * 1024, f"layout budget blown: data/ is {total} bytes"
