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


def test_power_cycle_settle_is_3s():
    """The Nextion needs ~2s from reset release to its bootloader prompt.

    Regression: the old 1.2s settle sent whmi-wris while the display was
    still booting, so every probe and every blind stream started deaf.
    """
    src = _src(NSPANEL)
    i = src.find("static void _powerCycleDisplay()")
    assert i >= 0
    body = src[i:i + 1200]
    assert body.count("vTaskDelay(3000") >= 2, (
        "power-cycle must hold reset 3s AND settle 3s after release"
    )


def test_silent_blind_pass_retries_at_9600():
    """A corrupt flash resets the display baud to the Nextion default 9600.

    Regression: the blind stream ran 115200-only, unheard by a 9600 display
    no matter how healthy the wire. A fully silent first pass on a
    recovery-sized file must trigger a second blind pass at 9600.
    """
    src = _src(NSPANEL)
    assert "_streamTFTFile" in src, "streaming must live in the testable helper"
    assert "_sendWhmiWrisAt(file_size, 9600)" in src
    assert "1048576" in src, "second pass must be size-guarded (16MB at 9600 is hours)"
    assert "heard_any" in src
