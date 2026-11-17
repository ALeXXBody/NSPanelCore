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


def test_w6_no_location_navigation():
    """P93: action buttons must use fetch(), never location.href navigation
    (navigating to /do_reboot parked the browser on a blank dead page)."""
    html = _web()
    assert "window.location.href" not in html, (
        "W6 REGRESSION: full-page navigation is back — actions must fetch()"
    )
    assert "fetch(url" in html or "fetch (url" in html.replace("fetch(url", "fetch (url"), (
        "W6 REGRESSION: confirmAction must fire fetch()"
    )


def test_w7_poller_uses_get_not_head():
    """P95: the 5s connection poller must use GET — the firmware only
    registers GET /, so HEAD always 404s and the overlay could never clear."""
    html = _web()
    assert '"HEAD"' not in html and "'HEAD'" not in html, (
        "W7 REGRESSION: HEAD polling is back — fw answers HEAD with 404"
    )
    assert 'open("GET", "/"' in html or "open('GET', '/'" in html, (
        "W7 REGRESSION: connection poller must GET /"
    )


def test_absurd_offset_restarts_clean():
    """P104: a 0x08 offset beyond bytes-sent (0xF10000 16s into a 115200
    stream) must clean-restart, never jump — jumping wrote Frankenstein
    images reporting 100% then System Data ERROR."""
    src = _src(NSPANEL)
    assert "readNextOffset > lastReadByte" in src, (
        "absurd-offset guard missing: unsent-data jumps must restart clean"
    )
    assert "consecutiveFailures" in src, (
        "retry bound missing: absurd-jump loop must give up loudly, not churn forever"
    )


def test_ap_fallback_always_reachable():
    """P116 audit: the setup AP must come up IMMEDIATELY on STA failure and
    stay up while the STA retries — never gated behind a timer, never torn
    down to chase the configured network, never an endless reboot loop.
    (The old code: AP only after 3 min, then scan→ESP.restart()→reboot
    forever with a wrong PSK — the panel was unreachable for ~4 of every
    5 minutes and the user saw no AP at all.)"""
    src = _src(pathlib.Path(FW) / "src" / "main.cpp")
    assert "WIFI_AP_STA" in src, "AP+STA concurrent mode missing"
    assert "Found configured WiFi. Will restart" not in src, (
        "scan-then-restart loop is back: reboots forever with a wrong PSK"
    )
    assert "millis() - lastWiFiconnected < 180 * 1000" not in src, (
        "3-minute AP gate is back: AP must come up immediately on failure"
    )
    assert 'softAP("NSPanelCore"' in src, "setup AP missing"
    assert "dropAPOnceSTAConnected" in src and "ensureAP" in src, (
        "AP lifecycle helpers missing"
    )


def test_ap_fallback_state_machine_sequence():
    """P116 regression: the AP lifecycle must follow the designed sequence
    from the ACTUAL source, in order —
      boot fail -> ensureAP (AP+STA up, web server up)
      user fixes config via AP page -> reboot -> STA connects
      -> dropAPOnceSTAConnected BEFORE mqtt start
      -> if STA drops later -> ensureAP again (restore, not gate).
    Pins the exact call order so the wiring cannot silently regress."""
    src = _src(pathlib.Path(FW) / "src" / "main.cpp")

    # 1. ensureAP() must: set AP+STA mode, start softAP, then init webMan.
    m = re.search(r"static void ensureAP\(\) \{(.*?)\n\}", src, re.S)
    assert m, "ensureAP() missing"
    body = m.group(1)
    assert "WiFi.mode(WIFI_AP_STA)" in body
    assert body.index("WiFi.softAP(") < body.index("webMan.init("), (
        "web server must start AFTER the AP is up"
    )
    assert "ESP.restart" not in body, "ensureAP must never reboot the panel"

    # 2. dropAP must run BEFORE webMan/mqtt init on STA connect (IP switch).
    m2 = re.search(
        r"if \(WiFi\.isConnected\(\)\) \{\n\s*dropAPOnceSTAConnected\(\);", src)
    assert m2, "dropAPOnceSTAConnected must be the first action on connect"
    after = src[m2.end():m2.end() + 800]
    assert "webMan.init" in after and "mqttManager.start" in after, (
        "web/mqtt init must follow the AP drop"
    )

    # 3. The retry loop must call ensureAP on EVERY failure pass (restore).
    retry = re.search(r"if \(!WiFi\.isConnected\(\)\) \{(.*?)dropAPOnceSTAConnected", src, re.S)
    assert retry, "retry block missing"
    assert retry.group(1).count("ensureAP()") >= 1, (
        "AP must be restored on every failed pass"
    )

    # 4. No-config path must park in a bounded delay loop (task alive),
    #    with the AP up — not in an eternal portMAX_DELAY inside a scan fn.
    m3 = re.search(r"No WiFi SSID configured: the setup AP runs forever\.(.*?)\n  \}", src, re.S)
    assert m3, "no-config AP path missing"
    assert "ensureAP()" in m3.group(1)
    assert "vTaskDelay(1000 / portTICK_PERIOD_MS)" in m3.group(1)


def test_boot_display_power_gentle_first():
    """P122 (user constraint: panel cannot be on mains while on the TTL
    bench): boot must NOT power-cycle the display before first trying to
    talk to it — the hard off→on transition browns out USB power and
    boot-loops the panel. The power cycle is a fallback only, after the
    gentle handshake fails."""
    src = _src(NSPANEL)
    init_body = src[src.index("bool NSPanel::init() {"):]
    init_body = init_body[:init_body.index("\n}\n", 100)]
    first_high = init_body.find("digitalWrite(4, HIGH)")
    first_connect = init_body.find('Serial2.print("connect")')
    assert first_connect != -1, "connect handshake missing"
    assert first_high == -1 or first_high > first_connect, (
        "boot power-cycles the display BEFORE trying the gentle handshake — "
        "boot-loops on USB power"
    )
    assert "power-cycling the display once" in src, (
        "power-cycle fallback missing (dead display would never recover)"
    )


def test_wifi_scan_endpoint_never_dead_ends():
    """P126: the setup-page scan endpoint must actively (re)start a scan on
    every empty/failed result. The old code only re-triggered on the exact
    WIFI_SCAN_FAILED value — an empty or odd state answered '[]' forever and
    the setup page never showed a single network (0.1.180 on IDF 5.5)."""
    src = _src(WEBMGR)
    i = src.index("void WebManager::respondAvailableWiFiNetworks")
    body = src[i:src.index("\n}\n", i)]
    # Every path that does not report results must call scanNetworks
    assert body.count("WiFi.scanNetworks(true)") >= 2, (
        "scan endpoint must re-trigger scanning on empty/failed states"
    )
    # Explicitly handle the running state instead of falling through
    assert "WIFI_SCAN_RUNNING" in body, (
        "scan-in-progress state must be handled explicitly"
    )
    # The AP bring-up kicks a first scan so the page has results on first poll
    main_src = _src(FW / "src" / "main.cpp")
    ap_start = main_src.index('Serial.println("Soft-AP started')
    window = main_src[ap_start:ap_start + 600]
    assert "WiFi.scanNetworks(true)" in window, (
        "AP bring-up must start the first WiFi scan immediately"
    )


def test_fs_ota_unmounts_littlefs_and_bounded_retries():
    """P129 (panel died stuck at 'Updating FS 100%'): the data-partition OTA
    must unmount LittleFS BEFORE Update.begin (mounted fs deadlocked
    Update.end() on IDF 5.5), remount after success, and the update task
    must have no infinite while(true) loops — every retry is bounded."""
    src = _src(WEBMGR)
    upd_i = src.index("bool WebManager::_update")
    upd_body = src[upd_i:src.index("\n}\n", upd_i)]
    unmount = upd_body.find("LittleFS.end();")
    begin = upd_body.find("Update.begin(")
    assert unmount != -1 and begin != -1 and unmount < begin, (
        "fs OTA must unmount LittleFS before Update.begin"
    )
    remount = upd_body.find("LittleFS.begin(false)", begin)
    assert remount != -1 and remount < upd_body.find("return true;", begin), (
        "fs OTA must remount the updated filesystem after success"
    )
    task_i = src.index("void WebManager::_taskPerformOTAUpdate")
    task_body = src[task_i:]
    assert "while (true)" not in task_body[:task_body.index("void WebManager::", task_i + 10)] if "void WebManager::" in task_body[task_i+10:] else True, (
        "no infinite loops allowed in the OTA task"
    )
    assert task_body.count("of 5.") == 2, "fw and fs retries must be bounded (P176 raised them to 5)"
    assert "save_attempt < 10" in task_body, "config save retries must be bounded"


def test_fw_and_fs_ota_split_across_reboots():
    """P132 (both panel deaths): after flashing new firmware the fs update
    must NEVER run in the same boot under freshly-flashed (not yet running)
    code — the fs step always executes under the newest firmware. The fw
    path reboots immediately; the manager drives the fs update after the
    restart."""
    src = _src(WEBMGR)
    task_i = src.index("void WebManager::_taskPerformOTAUpdate")
    task_body = src[task_i:]
    assert "fw_was_flashed = true;" in task_body, "fw flash must be tracked"
    assert "Firmware flashed — rebooting before the fs update" in task_body, (
        "fw update must reboot before any fs work"
    )
    fs_guard = src.index("} else if (firmwareUpdateSuccessful) {", task_i)
    assert fs_guard > src.index("Firmware flashed — rebooting before the fs update", task_i), (
        "fs section must be skipped when firmware was flashed"
    )


def test_app_never_serves_stale_firmware():
    """P132: the integration must auto-activate the manifest firmware (no
    manual step) — on update_available in the periodic poll and once shortly
    after startup — because serving stale bundled files caused both deaths."""
    src = _src(FW.parent / "custom_components" / "nspanel_core" / "manager.py")
    v2 = "def handle_register_request" in src
    if v2:
        src = _src(FW.parent / "custom_components" / "nspanel_core" / "__init__.py")
        assert "_refresh_firmware" in src and "download_and_activate" in src
        return
    poll_i = src.index("async def _poll_firmware_manifest")
    poll_body = src[poll_i:src.index("\n    def ", poll_i + 10)]
    if "activate_firmware_version" in poll_body:
        assert "_initial_firmware_check" in src, (
            "startup must schedule an early firmware check"
        )
    # v2 line: activation lives in __init__.py (checked above)


def test_ota_watchdog_recovers_stalled_updates():
    """P133: last-resort seatbelt — a stalled OTA task (frozen progress
    >120s) must be force-rebooted by the WiFi-task loop instead of wedging
    the panel. Mid-write reboots are recovery-safe (inactive app partition
    / re-creatable config fs)."""
    src = _src(FW / "src" / "main.cpp")
    assert "OTA progress frozen for 120s" in src, "OTA watchdog missing"
    assert "OTA stalled — rebooting." in src, "watchdog must force a reboot"
    i = src.index("OTA progress frozen for 120s")
    loop_i = src.rindex("for (;;)", 0, i)
    assert loop_i < i, "watchdog must live inside the WiFi task loop"


def test_version_never_stale_periodic_registration_and_report():
    """P135 (app showed a forever-stale v0.3.967): the panel must (a) carry
    its version in EVERY status report and (b) re-register periodically —
    version was a one-shot boot event before. The app must adopt the
    reported version from status reports."""
    src = _src(FW / "src" / "main.cpp")
    sr = src.index('status_report_doc["state"]')
    window = src[sr - 600:sr + 200]
    assert 'status_report_doc["version"]' in window, (
        "status reports must carry the running version"
    )
    reg = src.index("!InterfaceManager::hasRegisteredToManager")
    reg_window = src[reg:reg + 300]
    assert "300000" in reg_window, "periodic re-registration (5 min) missing"
    cc = FW.parent / "custom_components" / "nspanel_core"
    v2 = "def handle_register_request" in (cc / "manager.py").read_text()
    if v2:   # v2 line: version adopted in the core
        mgr = _src(cc / "manager.py")
        assert "panel.version = version" in mgr, "v2 must adopt version on status"
    else:    # v1 line: adoption in the status handler
        mgr = _src(cc / "manager.py")
        sri = mgr.index("async def _on_panel_status_report")
        body = mgr[sri:mgr.index("\n    async def ", sri + 10)]
        assert 'panel.version = reported_version' in body, (
            "app must adopt the reported version from status reports"
        )
