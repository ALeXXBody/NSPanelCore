/* NSPanel Core — web UI page builders + action routing (pure, host-testable). */

#include "webui_pages.h"
#include <map>
#include "protocol.h"

const char NSP_V1_CSS[] = R"NSPANEL_V1_CSS(/* NSPanel Core panel UI — hand-written, no build step.
   Dark-first. Brand: bg #0d1016, cyan #39c8e8, teal #2e7d8e, text #c8cbce. */
:root {
  --bg: #f2f4f7;
  --card: #ffffff;
  --text: #1a2230;
  --muted: #5b6472;
  --line: #dfe4ea;
  --accent: #1899b8;
  --accent-ink: #ffffff;
  --danger: #c93a3a;
  --radius: 10px;
}
html.dark {
  --bg: #0d1016;
  --card: #141a24;
  --text: #c8cbce;
  --muted: #8b93a1;
  --line: #232c3b;
  --accent: #39c8e8;
  --accent-ink: #06222b;
  --danger: #e06c6c;
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; max-width: 560px; padding: 16px 16px 32px;
  background: var(--bg); color: var(--text);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.hidden { display: none !important; }

/* header */
.brandbar { display: flex; align-items: center; gap: 10px; margin: 2px 0 12px; }
.brandbar.slim .brandmark { width: 30px; height: 30px; }
.brandmark { width: 40px; height: 40px; color: var(--accent); flex: none; }
.brandtext { flex: 1; min-width: 0; }
.brandtext h1 { font-size: 17px; margin: 0; letter-spacing: .02em; white-space: nowrap; }
.brandtext h1 span { color: var(--accent); }
.brandtext h1 .ver { font-size: 11px; font-weight: 400; color: var(--muted); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3ddc84; margin-left: 6px; vertical-align: 1px; }

/* theme toggle */
.theme-switch { display: inline-flex; align-items: center; cursor: pointer; flex: none; }
.theme-switch.compact .track { width: 34px; height: 20px; }
.theme-switch.compact .track::after { width: 16px; height: 16px; }
.theme-switch.compact input:checked + .track::after { transform: translateX(14px); }
.theme-switch input { position: absolute; opacity: 0; }
.theme-switch .track { width: 38px; height: 22px; border-radius: 11px; background: var(--line); position: relative; transition: background .2s; }
.theme-switch .track::after { content: ""; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: transform .2s; }
.theme-switch input:checked + .track { background: var(--accent); }
.theme-switch input:checked + .track::after { transform: translateX(16px); }

/* cards + fields: horizontal rows to keep everything above the fold */
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; margin: 0 0 10px; }
.card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 0 0 2px; font-weight: 600; }
.field { display: grid; grid-template-columns: 86px 1fr; gap: 10px; align-items: center; margin: 8px 0 0; }
.field > span { font-size: 12px; color: var(--muted); }
.row { display: flex; gap: 8px; }
.row input { flex: 1; min-width: 0; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.grid2 .field { display: block; }
.grid2 .field > span { display: block; margin-bottom: 4px; }
input[type=text], input[type=password], input[type=number], select {
  width: 100%; padding: 8px 10px; font-size: 14px; color: var(--text);
  background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
}
input:focus, select:focus { outline: 2px solid var(--accent); border-color: transparent; }
.hint { font-size: 12px; color: var(--muted); margin: 6px 0 0; }

/* segmented radio */
.seg { display: flex; gap: 8px; margin-top: 10px; }
.seg label { flex: 1; }
.seg input { position: absolute; opacity: 0; }
.seg span { display: block; text-align: center; padding: 8px; border: 1px solid var(--line); border-radius: 8px; cursor: pointer; font-size: 13px; }
.seg input:checked + span { border-color: var(--accent); color: var(--accent); font-weight: 600; }

/* collapsible advanced section */
details.card { padding: 0; }
details.card summary { list-style: none; cursor: pointer; padding: 10px 12px; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
details.card summary::-webkit-details-marker { display: none; }
details.card summary::before { content: "> "; color: var(--accent); }
details.card[open] summary::before { content: "v "; }
details.card .details-body { padding: 0 12px 12px; }
.seglabel { font-size: 12px; color: var(--muted); margin: 8px 0 0; }

/* buttons */
.btn { display: inline-block; padding: 9px 16px; font-size: 14px; border-radius: 8px; border: 1px solid transparent; cursor: pointer; text-decoration: none; }
.btn-primary { background: var(--accent); color: var(--accent-ink); font-weight: 600; width: 100%; }
.btn-ghost { background: transparent; color: var(--text); border-color: var(--line); white-space: nowrap; }
.btn-danger { background: transparent; color: var(--danger); border-color: var(--danger); }
.btn-block { width: 100%; margin-top: 10px; }
.actions { display: flex; gap: 8px; margin-top: 4px; }
.actions.sticky { position: sticky; bottom: 0; padding: 10px 0 6px; background: linear-gradient(transparent, var(--bg) 30%); }
.actions .btn-primary { flex: 1; }

/* modal + overlay */
.overlay { position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center; padding: 16px; background: rgba(0,0,0,.6); }
.modal-card { width: 100%; max-width: 520px; max-height: 85vh; overflow: auto; background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--line); }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-body { padding: 14px; text-align: center; }
.icon-btn { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 4px 8px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px; border-bottom: 1px solid var(--line); }
tbody td, tbody th { padding: 8px; border-bottom: 1px solid var(--line); text-align: left; font-weight: normal; }
tbody a { color: var(--accent); cursor: pointer; }
.spinner { width: 26px; height: 26px; margin: 6px auto; border: 3px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.alert { border-radius: 8px; padding: 10px 12px; margin: 10px 14px; font-size: 13px; }
.alert-error { background: #7f1d1d; color: #fecaca; }
.alert-warn { background: #78350f; color: #fde68a; }
.overlay-card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 22px 28px; text-align: center; max-width: 320px; }

footer { text-align: center; color: var(--muted); font-size: 11px; margin-top: 14px; letter-spacing: .04em; }
footer .core { color: var(--accent); }
@media (max-width: 420px) {
  .grid2 { grid-template-columns: 1fr; }
  .field { grid-template-columns: 76px 1fr; gap: 8px; }
}
)NSPANEL_V1_CSS";


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

/* Shared page head: v1 CSS inline + the v1 theme script (localStorage, dark-first). */
static std::string page_head(const char *title) {
    return std::string("<!DOCTYPE html><html lang=en class=dark><head><meta charset=utf-8>")
    + "<meta name=viewport content='width=device-width,initial-scale=1'>"
    + "<meta name=color-scheme content='dark light'>"
    + "<title>" + title + "</title><style>" + NSP_V1_CSS + "</style>"
    + "<script>function nspanel_is_dark(){try{var t=localStorage.getItem('nspanel-theme');"
      "if(t==='dark')return true;if(t==='light')return false;}catch(e){}return true;}"
      "function nspanel_apply_theme(d){document.documentElement.classList.toggle('dark',!!d);"
      "var b=document.getElementById('theme_toggle');if(b)b.checked=!!d;"
      "try{localStorage.setItem('nspanel-theme',d?'dark':'light');}catch(e){}}"
      "(function(){nspanel_apply_theme(nspanel_is_dark());})();"
      "function toggle_theme(d){nspanel_apply_theme(d);}</script></head>";
}

static std::string brandbar(const NspWebStatus &s) {
    return "<header class=brandbar>"
    "<svg class=brandmark viewBox=\"0 0 64 64\" aria-hidden=\"true\"><rect x=\"8\" y=\"8\" width=\"48\" height=\"48\" rx=\"12\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"4\"/><text x=\"32\" y=\"45\" text-anchor=\"middle\" font-size=\"34\" font-weight=\"700\" fill=\"currentColor\" font-family=\"system-ui,sans-serif\">C</text></svg>"
    "<div class=brandtext><h1>NSPanel <span>Core</span> <span class=ver>" + html_escape(s.version) + "</span><span class=dot></span></h1></div>"
    "<label class=\"theme-switch compact\" title=\"Dark mode\"><input type=checkbox id=theme_toggle onchange=\"toggle_theme(this.checked)\"><span class=track aria-hidden=\"true\"></span></label>"
    "</header>";
}

std::string nsp_web_status_page(const NspWebStatus &s) {
    auto rowv = [](const char *k, const std::string &v) {
        return std::string("<tr><th>") + k + "</th><td>" + html_escape(v.empty() ? "\u2014" : v) + "</td></tr>";
    };
    return page_head("NSPanel Core — status") + "<body>" + brandbar(s)
    + "<section class=card><h2>Status</h2><table><tbody>"
    + rowv("Mode", s.mode) + rowv("Hostname", s.hostname) + rowv("IP", s.ip)
    + rowv("WiFi RSSI", s.rssi) + rowv("Heap used", s.heap_pct)
    + rowv("Temperature", s.temperature) + rowv("Warnings", s.warnings)
    + rowv("MQTT", s.mqtt) + rowv("Manager (adopted)", s.manager)
    + rowv("Stored fw md5", s.md5_fw) + rowv("Stored fs md5", s.md5_fs)
    + rowv("OTA state", s.ota_state) + rowv("OTA progress", s.ota_progress)
    + rowv("Uptime (s)", s.uptime_s)
    + "</tbody></table></section>"
    + "<section class=card><h2>Actions</h2><div class=actions>"
    + "<button class=\"btn btn-ghost\" onclick=\"act('reboot')\">Reboot</button>"
    + "<button class=\"btn btn-ghost\" onclick=\"act('firmware_update')\">FW update</button>"
    + "<button class=\"btn btn-ghost\" onclick=\"act('display_restart')\">Display restart</button>"
    + "</div><div class=actions><button class=\"btn btn-danger\" onclick=\"if(confirm('Factory reset? The panel restarts into its setup AP.'))act('factory_reset')\">Factory reset</button></div></section>"
    + "<p class=hint><a href=/log>Panel log</a> \u00b7 status refreshes every 5 s</p>"
    + "<script>function act(a){fetch('/action',{method:'POST',body:'action='+a})"
      ".then(r=>r.text()).then(t=>alert(t)).catch(e=>alert('failed: '+e));"
      "setTimeout(()=>location.reload(),1500);}</script>"
    + "<footer>NSPanel <span class=core>Core</span> — panel UI</footer></body></html>";
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
    NspWebStatus s; s.version = FW_VERSION;
    return page_head("NSPanel Core — log") + "<body>" + brandbar(s)
    + "<section class=card><h2>Panel log (last 64 events)</h2>"
    + "<pre style=\"white-space:pre-wrap;word-break:break-all;font:12px/1.45 ui-monospace,monospace;margin:8px 0 0\">"
    + html_escape(logdump.empty() ? "(no events yet)" : logdump)
    + "</pre></section><p class=hint><a href=/>&larr; back to status</a></p>"
    + "<footer>NSPanel <span class=core>Core</span> — panel UI</footer></body></html>";
}

/* Setup/config form — the v1 index.html layout (Device / WiFi / MQTT cards). */
std::string nsp_web_setup_page(const NspWebStatus &s) {
    auto field = [](const char *label, const std::string &inner) {
        return std::string("<label class=field><span>") + label + "</span>" + inner + "</label>";
    };
    std::string ssid_val = html_escape(s.wifi_ssid_value);
    std::string host_val = html_escape(s.hostname_value);
    std::string server_val = html_escape(s.mqtt_server_value);
    std::string port_val = html_escape(s.mqtt_port_value.empty() ? "1883" : s.mqtt_port_value);
    std::string user_val = html_escape(s.mqtt_user_value);
    return page_head("NSPanel Core — setup") + "<body>" + brandbar(s)
    + "<form method=POST action=/save>"
    + "<section class=card><h2>Device</h2>"
    + field("Name", "<input type=text name=hostname placeholder=\"Device name\" value=\"" + host_val + "\" maxlength=32>")
    + "<p class=hint>Panel name on the wire (A\u2013Z a\u2013z 0\u20139 - _).</p></section>"
    + "<section class=card><h2>WiFi</h2>"
    + field("SSID", "<div class=row><input type=text name=ssid placeholder=\"SSID\" value=\"" + ssid_val + "\"" + std::string(s.wifi_known ? "" : " required") + "><button type=button class=\"btn btn-ghost\" onclick=\"scan()\" id=scb>Scan</button></div>")
    + "<select id=sclist onchange=\"document.forms[0].ssid.value=this.value\" style=\"display:none;margin:6px 0 0\"></select>"
    + field("Password", "<input type=password name=psk>")
    + (s.wifi_known ? "<p class=hint>WiFi is already configured \u2014 leave blank to keep it.</p>" : "")
    + "</section>"
    + "<section class=card><h2>MQTT</h2>"
    + field("Server", "<input type=text name=mqtt_server placeholder=\"MQTT Server\" value=\"" + server_val + "\" required>")
    + field("Port", "<input type=number name=mqtt_port value=\"" + port_val + "\" required>")
    + field("Username", "<input type=text name=mqtt_user value=\"" + user_val + "\">")
    + field("Password", "<input type=password name=mqtt_pass>")
    + "</section>"
    + "<div class=\"actions sticky\"><button class=\"btn btn-primary\" type=submit>Save &amp; restart</button></div></form>"
    + "<script>function scan(){var b=document.getElementById('scb');b.textContent='Scanning\u2026';b.disabled=true;"
      "fetch('/scan').then(r=>r.json()).then(function(l){var s=document.getElementById('sclist');"
      "s.innerHTML='';l.forEach(function(n){var o=document.createElement('option');"
      "o.value=n.ssid;o.textContent=n.ssid+' ('+n.rssi+' dBm)';s.appendChild(o);});"
      "if(l.length){s.style.display='block';document.forms[0].ssid.value=l[0].ssid;}"
      "else{s.style.display='block';s.innerHTML='<option>(no networks found)</option>';}"
      "b.textContent='Scan again';b.disabled=false;})"
      ".catch(function(){b.textContent='Scan failed \u2014 type SSID manually';b.disabled=false;});}</script>"
    + "<footer>NSPanel <span class=core>Core</span> — panel UI</footer></body></html>";
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
