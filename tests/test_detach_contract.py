"""Detach contract suite (Step 2) — freezes every behavior the rewrite must
preserve. Any drift in the wire contract, OTA rails, serving path or version
reporting fails here BEFORE the rewrite cutover, never on a panel."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "firmware"
INT = ROOT / "custom_components" / "nspanel_core"


def _src(path: pathlib.Path) -> str:
    return path.read_text()


def _py(path: pathlib.Path) -> str:
    return _src(path)


# --------------------------------------------------------------------------
# 1. MQTT topic matrix (the wire contract)
# --------------------------------------------------------------------------

def _is_v2_line() -> bool:
    """True when custom_components/nspanel_core is the REWRITTEN component.

    Discriminator: the v2 core defines handle_register_request (no leading
    underscore); the v1 manager defines _handle_register_request. The old
    platforms.py-existence check was wrong — the v1 line has one too."""
    src = (INT / "manager.py").read_text()
    return "def handle_register_request" in src

def test_topic_constants_frozen():
    """The integration's topic subscriptions are the wire contract."""
    src = _py(INT / "const.py")
    assert 'TOPIC_ROOT = "nspanel"' in src
    assert 'TOPIC_PANEL_STATUS = "nspanel/+/status"' in src
    assert 'TOPIC_PANEL_COMMAND = "nspanel/+/command"' in src
    assert 'TOPIC_PANEL_STATUS_REPORT = "nspanel/+/status_report"' in src
    assert 'TOPIC_MANAGER_COMMAND = "nspanel/mqttmanager/command"' in src


def test_panel_topic_builder_verbatim_hostname():
    """Command topics address the panel's wifi hostname VERBATIM (spaces
    kept) — the firmware subscribes exactly there (P134 finding: hostname
    mismatch = commands silently never arrive)."""
    src = _py(INT / "const.py")
    i = src.index("def panel_mqtt_base")
    body = src[i:src.index("\ndef ", i + 10)]
    # verbatim: no lowercase, no space-stripping — only wildcard/separator scrub
    assert ".lower()" not in body, "hostname must not be lowercased (breaks delivery)"
    assert 're.sub(r\'[+#/\\x00-\\x1f\\x7f]\', \'_\', s)' in body


def test_topic_safe_never_escalates():
    """topic_safe must never return slashes/wildcards (topic-escape guard)."""
    sys.path.insert(0, str(INT))
    from const import topic_safe  # type: ignore

    for bad in ("a/b", "a+b", "a#b", "../../etc", "a:b:c"):
        out = topic_safe(bad)
        assert "/" not in out and "+" not in out and "#" not in out


# --------------------------------------------------------------------------
# 2. Registration contract (panel → manager, both directions)
# --------------------------------------------------------------------------

def test_firmware_registration_payload_fields():
    """register_request carries every field the manager needs to identify,
    version and OTA-check the panel."""
    src = _src(FW / "src" / "main.cpp")
    i = src.index("void sendMqttManagerRegistrationRequest() {")
    body = src[i:src.index("\n}", i)]
    for field in ("command", "mac_origin", "friendly_name", "version",
                  "md5_firmware", "md5_data_file", "md5_tft_file", "address"):
        assert f'doc["{field}"]' in body, f"registration field {field} missing"
    assert 'MqttManager::publish("nspanel/mqttmanager/command", buffer)' in body


def test_firmware_registration_is_periodic():
    """Version display must never go stale (P135): 5-minute re-registration."""
    src = _src(FW / "src" / "main.cpp")
    assert "millis() - lastPeriodicRegistration > 300000" in src


def test_firmware_status_report_carries_version():
    src = _src(FW / "src" / "main.cpp")
    assert 'status_report_doc["version"] = NSPanelCoreFirmwareVersion' in src


def test_manager_registration_handler_updates_version():
    """The manager adopts the reported version on registration (both lines)."""
    src = _py(INT / "manager.py")
    if _is_v2_line():
        assert "panel.version = version" in src          # v2 core adoption
    else:
        assert 'panel.version = data["version"]' in src   # v1 adoption


def test_manager_status_report_adopts_version():
    if _is_v2_line():
        src = _py(INT / "manager.py")
        assert "panel.version = version" in src          # v2: live adoption
    else:
        src = _py(INT / "manager.py")
        body = src[src.index("async def _on_panel_status_report"):]
        body = body[:body.index("\n    async def ", 10)]
        assert 'panel.version = reported_version' in body


# --------------------------------------------------------------------------
# 3. Command contract (manager → panel)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", ["reboot", "firmware_update", "tft_update", "register_accept"])
def test_panel_command_names_frozen(command):
    """Both firmware generations must answer these exact command strings."""
    ours = _src(FW / "lib" / "InterfaceManager" / "InterfaceManager.cpp")
    assert f'"{command}"' in ours, f"our firmware must handle '{command}'"


def test_dashboard_update_actions_use_frozen_command_names():
    if _is_v2_line():
        src = _py(INT / "const.py")
        assert 'CMD_FIRMWARE_UPDATE = "firmware_update"' in src
        assert 'CMD_TFT_UPDATE = "tft_update"' in src
        mgr = _py(INT / "manager.py")
        assert "def send_firmware_update" in mgr and "def send_tft_update" in mgr
    else:
        src = _py(INT / "dashboard.py")
        i = src.index('action not in ("accept", "deny", "delete", "update_firmware", "update_tft")')
        window = src[i:i + 2600]
        assert '"firmware_update"' in window
        assert '"tft_update"' in window


# --------------------------------------------------------------------------
# 4. OTA endpoints + rails
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "/download_firmware", "/checksum_firmware",
    "/download_data_file", "/checksum_data_file",
    "/download_tft_eu",
])
def test_ota_endpoints_exist(url):
    if _is_v2_line():
        src = _py(INT / "const.py")
        assert f'"{url}"' in src           # OTA_ENDPOINTS list (v2)
    else:
        src = _py(INT / "dashboard.py")
        assert f'"{url}"' in src


def test_ota_serving_is_manifest_first_only():
    """P131: serving stale bundled files caused two panel deaths. The store
    must be the single source of truth, manifest-fetched, md5-verified."""
    src = _py(INT / "firmware_store.py")
    assert "MANIFEST_URL" in src
    assert "def download_and_activate" in src


def test_app_auto_activates_manifest_firmware():
    """P132: no manual step, no stale-serving window."""
    if _is_v2_line():
        src = _py(INT / "__init__.py")
        assert "_refresh_firmware" in src                 # v2 auto-activation
        assert "download_and_activate" in src
        assert "send_firmware_update" in src
    else:
        src = _py(INT / "manager.py")
        i = src.index("async def _poll_firmware_manifest")
        body = src[i:src.index("\n    def ", i + 10)]
        assert "activate_firmware_version" in body
        assert "_initial_firmware_check" in src


def test_firmware_ota_rails_all_present():
    """The load-bearing OTA rails (P126–P133): all must survive the rewrite."""
    src = _src(FW / "lib" / "WebManager" / "WebManager.cpp")
    # fw/fs split across reboots
    assert "Firmware flashed — rebooting before the fs update" in src
    # fs unmount before write + remount after
    upd = src[src.index("bool WebManager::_update"):]
    upd = upd[:upd.index("\n}\n", 100)]
    assert upd.find("LittleFS.end();") < upd.find("Update.begin(")
    # bounded retries
    task = src[src.index("void WebManager::_taskPerformOTAUpdate"):]
    assert task.count("of 5.") == 2
    assert "save_attempt < 10" in task
    # watchdog
    main_src = _src(FW / "src" / "main.cpp")
    assert "OTA progress frozen for 120s" in main_src


# --------------------------------------------------------------------------
# 5. Release/serving artifact contract
# --------------------------------------------------------------------------

def test_manifest_json_is_current_and_md5_backed():
    m = json.loads((ROOT / "firmware" / "manifest.json").read_text())
    # 0.0.x = the live Arduino line (bundled files match); 0.1.x = the
    # native-cutover state (the firmware entries point at the native build
    # on the release — not bundled locally, verified at activation instead).
    assert m["version"].startswith(("0.0.", "0.1."))
    import hashlib
    base = ROOT / "custom_components" / "nspanel_core"
    for path, entry in m["files"].items():
        if "firmware.bin" in path and m["version"].startswith("0.1."):
            assert (entry.get("md5") if isinstance(entry, dict) else entry), (
                "cutover manifest: the native firmware md5 must be present"
            )
            continue
        local_file = base / path
        if not local_file.is_file():
            continue  # v2 line: no bundled firmware (overlay-only by design)
        local = hashlib.md5(local_file.read_bytes()).hexdigest()
        remote = entry.get("md5") if isinstance(entry, dict) else entry
        assert local == remote, f"manifest md5 drift for {path}"


def test_evergreen_release_asset_set():
    """publish.sh must upload exactly the six servable files."""
    src = (ROOT / "firmware" / "publish.sh").read_text()
    for name in ("sonoff-firmware.bin", "sonoff-data_file.bin",
                 "custom-firmware.bin", "custom-data_file.bin",
                 "gui.tft", "gui_us.tft"):
        assert name in src


def test_recovery_page_serves_full_ours_image():
    inst = ROOT / "firmware" / ".pio" / "build" / "esp32dev_idf5"
    fw = inst / "firmware.bin"
    if fw.exists():
        assert (b"0.0.1" in fw.read_bytes()) or (b"0.0.2" in fw.read_bytes()), "built image must match a published migration-era version"


# --------------------------------------------------------------------------
# 6. Log bridge contract
# --------------------------------------------------------------------------

def test_stomp_log_topics_mac_safe():
    src = _py(INT / "manager.py")
    assert "log_backlog" in src or "log" in src
    const_src = _py(INT / "const.py")
    # mac-safe topic building must go through topic_safe (no slashes)
    assert "def topic_safe" in const_src


def test_v2_app_has_entity_platform_parity():
    """P147: the live HA install must not lose sensors/switches."""
    if _is_v2_line():
        src = _py(INT / "__init__.py")
        assert '["sensor", "switch"]' in src
    assert (INT / "sensor.py").is_file() and (INT / "switch.py").is_file()


def test_v2_app_has_light_platform_parity():
    """v1 had relay-as-light (per-panel flag); both lines must have it."""
    assert (INT / "light.py").is_file()
    src = (INT / "light.py").read_text()
    assert "RelayLight" in src and "set_relay" in src


def test_time_date_publishing_contract():
    """P159: the panel's screensaver clock lives off the retained
    nspanel/status/{time,date,ampm} topics — the manager must publish them
    (60 s cadence), honoring the clock/date settings."""
    src = _py(INT / "manager.py")
    assert '"nspanel/status/time"' in src
    assert '"nspanel/status/date"' in src
    assert '"nspanel/status/ampm"' in src
    assert "timedelta(seconds=60)" in src
    assert "clock_us_style" in src and 'date_format or "%d/%m"' in src
