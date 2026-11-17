/* NSPanel Core — web UI page builders + action routing (pure, host-testable). */

#include "webui_pages.h"
#include <map>

static std::string html_escape(const std::string &s) {
    std::string o;
    for (char c : s) {
        switch (c) {
        case '<': o += "&lt;"; break;
        case '>': o += "&gt;"; break;
        case '&': o += "&amp;"; break;
        case '"': o += "&quot;"; break;
        default: o += c;
        }
    }
    return o;
}

static std::string row(const char *k, const std::string &v) {
    return std::string("<tr><td>") + k + "</td><td>" + html_escape(v.empty() ? "—" : v) + "</td></tr>";
}

std::string nsp_web_status_page(const NspWebStatus &s) {
    std::string p = "<!DOCTYPE html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>NSPanel Core — status</title><style>"
    "body{font:14px/1.5 system-ui;max-width:460px;margin:24px auto;padding:0 16px;"
    "background:#0d1016;color:#c8cbce}h1{font-size:18px}h1 span{color:#39c8e8}"
    "table{width:100%;border-collapse:collapse}td{padding:4px 6px;border-bottom:1px solid #1c2534}"
    "td:first-child{color:#8b93a1;font-size:12px;width:42%}"
    "button{padding:8px 14px;margin:4px 4px 0 0;background:#2277aa;color:#fff;border:0;"
    "border-radius:6px;font-size:14px}.warn{background:#7a3c3c}.reset{background:#7a3c3c}"
    "a{color:#39c8e8}.note{color:#8b93a1;font-size:12px}</style></head>"
    "<body><h1>NSPanel <span>Core</span> — " + html_escape(s.mode) + "</h1>"
    "<table>"
    + row("Version", s.version)
    + row("Hostname", s.hostname)
    + row("IP", s.ip)
    + row("WiFi RSSI", s.rssi)
    + row("Heap used", s.heap_pct)
    + row("Temperature", s.temperature)
    + row("Warnings", s.warnings)
    + row("MQTT", s.mqtt)
    + row("Manager (adopted)", s.manager)
    + row("Stored fw md5", s.md5_fw)
    + row("Stored fs md5", s.md5_fs)
    + row("OTA state", s.ota_state)
    + row("OTA progress", s.ota_progress)
    + row("Uptime (s)", s.uptime_s)
    + "</table>"
    "<p>"
    "<button onclick=\"act('reboot')\">Reboot</button>"
    "<button onclick=\"act('firmware_update')\">FW update</button>"
    "<button onclick=\"act('display_restart')\">Display restart</button>"
    "<button class=reset onclick=\"if(confirm('Factory reset? The panel restarts into its setup AP.'))act('factory_reset')\">Factory reset</button>"
    "</p>"
    "<p class=note><a href=/log>Panel log</a> · refreshes every 5 s</p>"
    "<script>function act(a){fetch('/action',{method:'POST',body:'action='+a})"
    ".then(r=>r.text()).then(t=>alert(t)).catch(e=>alert('failed: '+e));"
    "setTimeout(()=>location.reload(),1500);}</script>"
    "</body></html>";
    return p;
}

std::string nsp_web_status_json(const NspWebStatus &s) {
    auto esc = [](const std::string &v) {
        std::string o;
        for (char c : v) {
            if (c == '"' || c == '\\') { o += '\\'; o += c; }
            else if (static_cast<unsigned char>(c) < 0x20) o += ' ';
            else o += c;
        }
        return o;
    };
    auto kv = [&](const char *k, const std::string &v) {
        return std::string("\"") + k + "\":\"" + esc(v) + "\"";
    };
    return "{" + kv("mode", s.mode) + "," + kv("version", s.version) + ","
         + kv("hostname", s.hostname) + "," + kv("ip", s.ip) + ","
         + kv("rssi", s.rssi) + "," + kv("heap_pct", s.heap_pct) + ","
         + kv("temperature", s.temperature) + "," + kv("warnings", s.warnings) + ","
         + kv("mqtt", s.mqtt) + "," + kv("manager", s.manager) + ","
         + kv("md5_fw", s.md5_fw) + "," + kv("md5_fs", s.md5_fs) + ","
         + kv("ota_state", s.ota_state) + "," + kv("ota_progress", s.ota_progress) + ","
         + kv("uptime_s", s.uptime_s) + "}";
}

std::string nsp_web_log_page(const std::string &logdump) {
    return "<!DOCTYPE html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>NSPanel Core — log</title><style>"
    "body{font:14px/1.5 system-ui;margin:20px auto;max-width:760px;padding:0 14px;"
    "background:#0d1016;color:#c8cbce}h1{font-size:18px}h1 span{color:#39c8e8}"
    "pre{background:#000;border:1px solid #232c3b;border-radius:8px;padding:12px;"
    "white-space:pre-wrap;word-break:break-all;font:12px/1.45 ui-monospace,monospace}"
    "a{color:#39c8e8}</style></head>"
    "<body><h1>NSPanel <span>log</span> (last 64 events) — <a href=/>back</a></h1>"
    "<pre>" + html_escape(logdump.empty() ? "(no events yet)" : logdump) + "</pre>"
    "</body></html>";
}

int nsp_web_parse_action(const std::string &body) {
    size_t a = body.find("action=");
    if (a == std::string::npos) return 0;
    std::string v = body.substr(a + 7);
    size_t amp = v.find('&');
    if (amp != std::string::npos) v = v.substr(0, amp);
    if (v == "reboot") return 1;
    if (v == "firmware_update") return 2;
    if (v == "display_restart") return 3;
    if (v == "factory_reset") return 4;
    return 0;
}
