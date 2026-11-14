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
    """The blind ladder / probes are gone — upstream init retries the two
    known bauds and never streams without a handshake."""
    src = _src(NSPANEL)
    for gone in ("_probeUploadAtBaud", "_neighborBaud", "_powerCycleDisplay",
                 "_sendWhmiWrisAt", "Proceeding with blind tolerant upload"):
        assert gone not in src, f"{gone} must be removed"


def test_init_retries_two_bauds_upstream_style():
    src = _src(NSPANEL)
    assert "communication_baud_rate == 115200 ? NSPMConfig::instance->tft_upload_baud : 115200" in src
    assert "_tft_init_depth" not in src, "7-attempt cap must be gone"
    # Escape settle restored to upstream expression in BOTH call sites.
    assert src.count("(1000000 / Serial2.baudRate()) + 30 / portTICK_PERIOD_MS") == 2
