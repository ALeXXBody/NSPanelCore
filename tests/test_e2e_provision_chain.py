"""P311 END-TO-END: the WHOLE P215/P216 provisioning chain, tested entirely
in the virtual environment — the REAL manager code against a MOCK panel
(local HTTP server) with the REAL firmware parsers compiled on host (the
same C++ sources that run on the ESP32).

Chain under test, link by link:
  1. Settings → Panel MQTT saved (real validate/apply_settings)
  2. Discovery fetch: the manager reads the mock panel's /status.json
     (real _fetch_panel_status + signature check over real HTTP)
  3. Accept: the REAL accept view pushes to the mock panel's /provision —
     the request is captured (headers + body)
  4. The captured body goes through the REAL firmware parser
     (provision_parse.cpp on host) — the credentials must round-trip
     EXACTLY, including quotes, backslashes and non-ASCII characters
  5. The panel registers (the exact JSON nsp_mqtt_send_register builds) →
     the REAL _handle_register_request: row created AND auto-accepted
     (single accept via the discovery pre-accept)
  6. The published register_accept goes through the REAL accept parser
     (accept_parse.cpp on host) — the panel adopts the manager address
  7. The REAL OTA evaluator with the panel's empty md5s triggers the
     firmware update (the md5 hook, never version-gated)
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard as D  # noqa: E402
from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import IntegrationConfig  # noqa: E402
from nspanel_core.const import topic_safe  # noqa: E402

BROKER = "192.168.50.20"
BROKER_PORT = 1883
BROKER_USER = "ALeXX"
# pins BOTH fixes: non-ASCII (ensure_ascii) + quote/backslash (parser unescape)
BROKER_PASS = "Pässwörd\"1\\x"
PANEL_HOSTNAME = "KitchenPanrl"
PANEL_MAC = "e465b849a100"


# ------------------------------------------------------------- mock panel

class _PanelServer:
    """The panel's own web surface: /status.json + /provision, recording
    everything it receives — exactly the endpoints the real firmware serves."""

    def __init__(self):
        self.provision_requests = []  # {"headers": {...}, "body": bytes}
        self.status_hits = 0
        outer = self

        class _H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):
                if self.path == "/status.json":
                    outer.status_hits += 1
                    body = json.dumps({
                        "mode": "station", "version": "0.1.4",
                        "hostname": PANEL_HOSTNAME, "ip": "127.0.0.1",
                        "rssi": "-59 dBm", "heap_pct": "40 %",
                        "temperature": "32.3 °C",
                        "warnings": "No response from the display.",
                        "mqtt": "not configured", "manager": "not adopted",
                        "md5_fw": "(none)", "md5_fs": "(none)",
                        "ota_state": "idle", "ota_progress": "0 %",
                        "uptime_s": "18",
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/provision":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    outer.provision_requests.append({
                        "content_type": self.headers.get("Content-Type"),
                        "x_nspanel": self.headers.get("X-NSPanel"),
                        "body": body,
                    })
                    resp = b"provisioned - rebooting"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


# ------------------------------------------------- real firmware parsers

@pytest.fixture(scope="module")
def host_tools():
    """Compile the real firmware parsers (the panel's actual code) on host."""
    out = pathlib.Path("/tmp/opencode/e2e_tools")
    out.mkdir(parents=True, exist_ok=True)
    src = REPO / "firmware-native" / "src"
    prov = out / "nsp_parse_provision"
    acc = out / "nsp_parse_accept"
    if not prov.exists():
        subprocess.run([
            "g++", "-std=c++17", "-o", str(prov),
            str(REPO / "tests/host_tools/nsp_parse_provision.cpp"),
            str(src / "provision_parse.cpp"),
        ], check=True, capture_output=True)
    if not acc.exists():
        subprocess.run([
            "g++", "-std=c++17", "-o", str(acc),
            str(REPO / "tests/host_tools/nsp_parse_accept.cpp"),
            str(src / "accept_parse.cpp"),
        ], check=True, capture_output=True)
    return {"provision": str(prov), "accept": str(acc)}


def _run_tool(path: str, text: str) -> str:
    return subprocess.run(
        [path], input=text.encode(), capture_output=True, check=True
    ).stdout.decode("utf-8")


# --------------------------------------------------------- shared manager

def _real_manager():
    """A manager whose DATA is real (IntegrationConfig) and whose side
    channels are recorded — the real class methods run through it."""
    mgr = MagicMock()
    mgr.config = IntegrationConfig()
    s = mgr.config.settings
    s.manager_address = BROKER  # a real install stores the HA IP
    s.manager_port = 8123
    s.panel_broker_host = ""
    s.ignored_macs = []
    mgr.hass = MagicMock()
    mgr.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *a, **k: fn(*a, **k))
    mgr.async_save = AsyncMock()
    mgr._publish = AsyncMock()
    mgr._publish_panel_status = AsyncMock()
    mgr._publish_panel_device_config = AsyncMock()
    mgr._schedule_save = lambda: None
    mgr._maybe_trigger_firmware_ota_cooled = AsyncMock()
    mgr.dash = MagicMock()
    mgr.dash.has_design.return_value = False
    mgr._panel_by_mac = lambda mac: next(
        (p for p in mgr.config.panels if p.mac == mac), None)
    mgr.is_ignored_mac = lambda mac: topic_safe(mac) in s.ignored_macs
    # MagicMock self shadows class methods — bind the real ones the
    # registration path calls
    mgr.maybe_preaccept_hostname = lambda panel, friendly: (
        M.NSPanelCoreManager.maybe_preaccept_hostname(mgr, panel, friendly))
    mgr._panel_cmd_topic = lambda panel, suffix: (
        f"nspanel/{panel.wifi_hostname or panel.name}/{suffix}")
    mgr._register_accept_reply = lambda panel: (
        M.NSPanelCoreManager._register_accept_reply(mgr, panel))
    return mgr


# ------------------------------------------------------------------ chain

@pytest.mark.enable_socket
async def test_e2e_full_provision_chain(host_tools):
    # The HA test plugin re-disables sockets in pytest_runtest_setup AFTER
    # the marker check — re-enable explicitly for this test: the chain runs
    # against a REAL local HTTP server (the mock panel).
    import pytest_socket
    pytest_socket.enable_socket()

    panel = _PanelServer()
    try:
        mgr = _real_manager()

        # the real class methods must run through the mock self
        mgr.validate_settings = lambda ui, cur=None: M.NSPanelCoreManager.validate_settings(ui, cur)
        mgr._publish_manager_status = AsyncMock()
        mgr._reschedule_weather = lambda: None

        # 1. the user saves the Panel MQTT settings (real validate/apply)
        errors = await M.NSPanelCoreManager.apply_settings(mgr, {
            "panel_broker_host": BROKER,
            "panel_broker_port": str(BROKER_PORT),
            "panel_broker_user": BROKER_USER,
            "panel_broker_pass": BROKER_PASS,
        })
        assert not errors
        assert mgr.config.settings.panel_broker_pass == BROKER_PASS

        # 2. discovery: the manager reads the panel's status over real HTTP
        status = await M.NSPanelCoreManager._fetch_panel_status(mgr, panel.address)
        assert status is not None, "the manager must recognize the panel by signature"
        assert status["hostname"] == PANEL_HOSTNAME
        mgr._discovered_panels = {panel.address: status}

        # 3. the user ACCEPTS (the real view, pushing over real HTTP)
        with patch.object(D, "_manager", return_value=mgr):
            with patch.object(D, "_nspanel_auth_ok", AsyncMock(return_value=True)):
                resp = await D.DiscoveredPanelActionView().post(_req(
                    {"action": "accept", "address": panel.address,
                     "hostname": PANEL_HOSTNAME}))
        assert resp.status == 200, resp.text

        # the push reached the mock panel with the guard headers
        req = panel.provision_requests[-1]
        assert req["content_type"] == "application/x-www-form-urlencoded"
        assert req["x_nspanel"] == "1"
        # the hostname is pre-accepted for the coming registration
        assert topic_safe(PANEL_HOSTNAME) in map(
            topic_safe, mgr.config.settings.pre_accepted_hostnames)

        # 4. the PANEL parses the captured body with its REAL parser —
        #    the credentials must round-trip byte-exact
        parsed = _run_tool(host_tools["provision"],
                           req["body"].decode("utf-8")).strip().split("\t")
        assert parsed[0] == BROKER
        assert parsed[1] == str(BROKER_PORT)
        assert parsed[2] == BROKER_USER
        assert parsed[3] == BROKER_PASS, (
            f"the panel would store {parsed[3]!r}, not {BROKER_PASS!r}")
        assert parsed[4] == "ok"

        # 5. the panel registers with the EXACT payload the firmware builds
        register_json = json.dumps({
            "command": "register_request", "mac_origin": PANEL_MAC,
            "friendly_name": PANEL_HOSTNAME, "version": "0.1.4",
            "md5_firmware": "", "md5_data_file": "", "md5_tft_file": "",
            "address": "127.0.0.1",
        })
        await M.NSPanelCoreManager._handle_register_request(
            mgr, PANEL_MAC, json.loads(register_json))

        rows = [p for p in mgr.config.panels if p.mac == PANEL_MAC]
        assert len(rows) == 1, "exactly one row for the panel"
        assert rows[0].accepted is True, "single accept: pre-accepted at discovery"
        assert rows[0].name == PANEL_HOSTNAME

        # register_accept + the reload nudge went to the panel's OWN command
        # topic (P355: the P324 suppression lifted — accept + reload)
        topics = [c.args[0] for c in mgr._publish.await_args_list]
        cmd_topic = f"nspanel/{PANEL_HOSTNAME}/command"
        assert topics.count(cmd_topic) == 2, topics

        # 6. the panel adopts the manager with its REAL parser
        accept_payload = mgr._publish.await_args_list[0].args[1]
        adopted = _run_tool(host_tools["accept"], accept_payload).strip().split("\t")
        assert adopted[0] == BROKER
        assert adopted[1] == "8123"
        assert adopted[2] == "ok"

        # 7. the md5 hook: the panel reported EMPTY md5s — the update fires
        mgr._ota_md5 = {"firmware/sonoff/firmware.bin": "x"}
        mgr.ota_md5 = MagicMock(side_effect=lambda kind, name: {
            ("firmware", "sonoff/firmware.bin"): "587386d3e042c6303087745a7341ebcf",
            ("firmware", "sonoff/data_file.bin"): "74d7ce6e39754a9bec2ae3a075620c49",
            ("tft", "gui.tft"): "b2b6a2e3e53ab56405d2202d51c98a29",
        }.get((kind, name), ""))
        await M.NSPanelCoreManager._maybe_trigger_firmware_ota(
            mgr, rows[0], {"md5_firmware": ""})
        cmds = [c.args[1] for c in mgr._publish.await_args_list]
        assert any('"firmware_update"' in c for c in cmds), cmds
    finally:
        panel.stop()


def _req(form):
    r = MagicMock()
    r.headers = {"Cookie": "", "Authorization": "Bearer good"}
    r.cookies = {}
    r.query = {}
    r.match_info = {}

    async def post():
        return form

    r.post = post
    return r
