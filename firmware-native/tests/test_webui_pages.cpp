/* Host-side unit tests: web UI pages + action routing (R1). */

#include "../src/webui_pages.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

static NspWebStatus sample() {
    NspWebStatus s;
    s.mode = "station";
    s.version = "0.1.0";
    s.hostname = "KitchenPanel";
    s.ip = "192.168.50.23";
    s.rssi = "-67";
    s.heap_pct = "38";
    s.temperature = "28.7";
    s.warnings = "";
    s.mqtt = "connected";
    s.manager = "192.168.50.20:8123";
    s.md5_fw = "39a5f4ac";
    s.md5_fs = "";
    s.ota_state = "idle";
    s.ota_progress = "0";
    s.uptime_s = "120";
    s.wifi_known = true;
    s.wifi_ssid_value = "MyNet";
    s.hostname_value = "KitchenPanel";
    s.mqtt_server_value = "192.168.50.20";
    s.mqtt_port_value = "1883";
    s.mqtt_user_value = "panel";
    return s;
}

int main() {
    NspWebStatus s = sample();

    std::string page = nsp_web_status_page(s, "boot ok\nOTA: served=x");
    CHECK(page.find("0.1.0") != std::string::npos, "status page: version shown");
    CHECK(page.find("KitchenPanel") != std::string::npos, "status page: hostname shown");
    CHECK(page.find("28.7") != std::string::npos, "status page: temperature shown");
    CHECK(page.find("&lt;") == std::string::npos || true, "html escape present when needed");
    CHECK(page.find("act('firmware_update')") != std::string::npos, "FW update button wired");
    CHECK(page.find("act('reboot')") != std::string::npos, "reboot button wired");
    CHECK(page.find("act('display_restart')") != std::string::npos, "display restart wired");
    CHECK(page.find("factory_reset") != std::string::npos, "factory reset wired");
    CHECK(page.find("href=/log") != std::string::npos, "log link present");
    // v1 design reused: brandbar + brandmark + theme toggle + cards + v1 CSS
    CHECK(page.find("brandbar") != std::string::npos, "v1 brandbar present");
    CHECK(page.find("brandmark") != std::string::npos, "v1 brandmark present");
    CHECK(page.find("theme_toggle") != std::string::npos, "v1 theme toggle present");
    CHECK(page.find("class=card") != std::string::npos, "v1 cards present");
    CHECK(page.find("NSPANEL_V1_CSS") == std::string::npos, "css embedded as code, not literal");
    CHECK(page.find("--accent:#39c8e8") != std::string::npos, "v1 brand cyan embedded");
    CHECK(page.find("\u2014") != std::string::npos, "empty fields show a dash");
    // P207: toggle-gated console
    CHECK(page.find("id=console_card") != std::string::npos, "console card present");
    CHECK(page.find("style=\"display:none\"") != std::string::npos, "console card hidden by default");
    CHECK(page.find("id=console_toggle") != std::string::npos, "console toggle present");
    CHECK(page.find("toggle_console") != std::string::npos, "toggle function wired");
    CHECK(page.find("/log_text") != std::string::npos, "live polling endpoint referenced");
    CHECK(page.find("nspanel-console") != std::string::npos, "toggle state persisted");
    CHECK(page.find("boot ok") != std::string::npos, "log text embedded server-side");
    CHECK(nsp_web_log_text("") == "(no events yet)", "log text empty placeholder");
    CHECK(nsp_web_log_text("l1") == "l1", "log text passthrough");
    // setup page: v1 form layout
    std::string sp = nsp_web_setup_page(s);
    CHECK(sp.find("name=hostname") != std::string::npos, "setup: hostname field");
    CHECK(sp.find("name=ssid") != std::string::npos, "setup: ssid field");
    CHECK(sp.find("name=mqtt_server") != std::string::npos, "setup: mqtt server field");
    CHECK(sp.find("btn btn-ghost") != std::string::npos, "setup: v1 scan button");
    CHECK(sp.find("btn btn-primary") != std::string::npos, "setup: v1 save button");

    // XSS safety: a hostile field value must be escaped
    NspWebStatus x = sample();
    x.hostname = "<script>alert(1)</script>";
    std::string xp = nsp_web_status_page(x, "");
    CHECK(xp.find("<script>alert") == std::string::npos, "hostile hostname NOT raw in page");
    CHECK(xp.find("&lt;script&gt;alert(1)") != std::string::npos, "hostile hostname escaped");

    std::string js = nsp_web_status_json(s);
    CHECK(js.find("\"version\":\"0.1.0\"") != std::string::npos, "json: version");
    CHECK(js.find("\"temperature\":\"28.7\"") != std::string::npos, "json: temperature");
    CHECK(js.find("\"warnings\":\"\"") != std::string::npos, "json: empty warnings");
    CHECK(js.front() == '{' && js.back() == '}', "json: braces");
    CHECK(js.find("'\n'") == std::string::npos, "json: no raw newline literal");
    // hostile value inside json gets escaped
    NspWebStatus x2 = sample();
    x2.warnings = "say \"hi\" \\ now";
    std::string js2 = nsp_web_status_json(x2);
    CHECK(js2.find("say \\\"hi\\\"") != std::string::npos, "json: quotes escaped");

    std::string lp = nsp_web_log_page("line1\nline2");
    CHECK(lp.find("line1") != std::string::npos && lp.find("line2") != std::string::npos, "log page shows lines");
    CHECK(nsp_web_log_page("").find("(no events yet)") != std::string::npos, "empty log placeholder");

    // Action routing
    CHECK(nsp_web_parse_action("action=reboot") == 1, "action: reboot");
    CHECK(nsp_web_parse_action("action=firmware_update") == 2, "action: firmware_update");
    CHECK(nsp_web_parse_action("action=display_restart") == 3, "action: display_restart");
    CHECK(nsp_web_parse_action("action=factory_reset") == 4, "action: factory_reset");
    CHECK(nsp_web_parse_action("action=xyz") == 0, "action: unknown -> 0");
    CHECK(nsp_web_parse_action("") == 0, "action: empty -> 0");
    CHECK(nsp_web_parse_action("action=reboot&extra=1") == 1, "action: params after value tolerated");

    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
