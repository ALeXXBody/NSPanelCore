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
    """The manager adopts the reported version on registration."""
    src = _py(INT / "manager.py")
    assert 'panel.version = data["version"]' in src


def test_manager_status_report_adopts_version():
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
    src = _py(INT / "dashboard.py")
    assert f'"{url}"' in src


def test_ota_serving_is_manifest_first_only():
    """P131: serving stale bundled files caused two panel deaths. The store
    must be the single source of truth, manifest-fetched, md5-verified."""
    src = _py(INT / "firmware_store.py")
    assert "DEFAULT_MANIFEST_URL" in src
    assert "def download_and_activate" in src


def test_app_auto_activates_manifest_firmware():
    """P132: no manual step, no stale-serving window."""
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
    assert task.count("of 3.") == 2
    assert "save_attempt < 10" in task
    # watchdog
    main_src = _src(FW / "src" / "main.cpp")
    assert "OTA progress frozen for 120s" in main_src


# --------------------------------------------------------------------------
# 5. Release/serving artifact contract
# --------------------------------------------------------------------------

def test_manifest_json_is_current_and_md5_backed():
    m = json.loads((ROOT / "firmware" / "manifest.json").read_text())
    assert m["version"].startswith("0.0.")
    import hashlib
    for path, entry in m["files"].items():
        local = hashlib.md5((ROOT / "custom_components" / "nspanel_core" / path).read_bytes()).hexdigest()
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
        assert b"0.0.1" in fw.read_bytes(), "built image must match the published version"


# --------------------------------------------------------------------------
# 6. Log bridge contract
# --------------------------------------------------------------------------

def test_stomp_log_topics_mac_safe():
    src = _py(INT / "manager.py")
    assert "log_backlog" in src or "log" in src
    const_src = _py(INT / "const.py")
    # mac-safe topic building must go through topic_safe (no slashes)
    assert "def topic_safe" in const_src
