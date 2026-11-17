/* NSPanel Core — setup AP: first-boot configuration portal.
 *
 * When no config is stored (fresh NVS), the panel raises the NSPanelCore
 * AP with a minimal config form. Saving writes NVS and reboots into STA.
 * This is the native-firmware equivalent of the v1 setup page — smaller,
 * no filesystem dependency (page served from RAM).
 */

#include "esp_wifi.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "protocol.h"
#include "config.h"
#include "form_parse.h"
#include "scan_json.h"
#include <string>
#include <cstring>
#include <map>
#include <vector>
#include <utility>
#include <cstdlib>
#include <arpa/inet.h>

std::string nsp_build_setup_page() {
    bool wifi_known = !g_cfg.wifi_ssid.empty();
    std::string ssid_attr = wifi_known ? ("value=\"" + g_cfg.wifi_ssid + "\"") : "";
    std::string wifi_note = wifi_known
        ? "<p class=note>WiFi is already configured — leave blank to keep it.</p>"
        : "";
    std::string page =
    "<!DOCTYPE html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>NSPanel Core setup</title><style>"
    "body{font:14px/1.5 system-ui;max-width:420px;margin:24px auto;padding:0 16px;"
    "background:#0d1016;color:#c8cbce}h1{font-size:18px}h1 span{color:#39c8e8}"
    "input,select{width:100%;padding:8px;margin:4px 0 12px;background:#141a24;"
    "border:1px solid #232c3b;border-radius:6px;color:#c8cbce;box-sizing:border-box}"
    "button{width:100%;padding:10px;background:#2277aa;color:#fff;border:0;"
    "border-radius:6px;font-size:15px}button.sc{background:#182031;color:#7fb8d8;"
    "border:1px solid #232c3b;padding:6px;font-size:13px;width:auto}"
    "label{color:#8b93a1;font-size:12px}"
    ".note{color:#8b93a1;font-size:12px}</style></head>"
    "<body><h1>NSPanel <span>Core</span> setup</h1>"
    "<form method=POST action=/save>"
    "<label>WiFi SSID</label><input name=ssid " + ssid_attr + (wifi_known ? "" : " required") + ">"
    + wifi_note +
    "<button type=button class=sc onclick='scan()' id=scb>Scan for networks</button>"
    "<select id=sclist onchange=\"document.forms[0].ssid.value=this.value\" style=display:none></select>"
    "<label>WiFi password</label><input name=psk type=password>"
    "<label>Panel name (hostname)</label><input name=hostname value='" + g_cfg.wifi_hostname + "'>"
    "<label>MQTT server</label><input name=mqtt_server required>"
    "<label>MQTT port</label><input name=mqtt_port value='1883'>"
    "<label>MQTT username</label><input name=mqtt_user>"
    "<label>MQTT password</label><input name=mqtt_pass type=password>"
    "<button>Save &amp; restart</button></form>"
    "<script>"
    "function scan(){var b=document.getElementById('scb');b.textContent='Scanning…';b.disabled=true;"
    "fetch('/scan').then(r=>r.json()).then(function(l){var s=document.getElementById('sclist');"
    "s.innerHTML='';l.forEach(function(n){var o=document.createElement('option');"
    "o.value=n.ssid;o.textContent=n.ssid+' ('+n.rssi+' dBm)';s.appendChild(o);});"
    "if(l.length){s.style.display='block';document.forms[0].ssid.value=l[0].ssid;}"
    "else{s.style.display='block';s.innerHTML='<option>(no networks found)</option>';}"
    "b.textContent='Scan again';b.disabled=false;})"
    ".catch(function(){b.textContent='Scan failed — type SSID manually';b.disabled=false;});}"
    "</script></body></html>";
    return page;
}

static bool s_server_up = false;

/* P183: WiFi scan for the setup form. The AP runs in APSTA mode so the
 * scan works while the AP broadcasts. Blocking scan (~2-4 s) inside the
 * httpd worker task. Output via the host-tested nsp_scan_json(). */
esp_err_t nsp_handle_scan(httpd_req_t *req) {
    httpd_resp_set_type(req, "application/json");
    wifi_scan_config_t sc = {};
    esp_err_t err = esp_wifi_scan_start(&sc, true);
    if (err != ESP_OK) {
        httpd_resp_send(req, "[]", 2);
        return ESP_OK;
    }
    uint16_t n = 0;
    esp_wifi_scan_get_ap_num(&n);
    if (n > 20) n = 20;  // top 20 is plenty for a pick list
    std::vector<std::pair<std::string, int>> recs;
    if (n > 0) {
        wifi_ap_record_t *aprecs = (wifi_ap_record_t *)malloc(sizeof(wifi_ap_record_t) * n);
        if (aprecs) {
            esp_wifi_scan_get_ap_records(&n, aprecs);  // also frees the scan cache
            for (uint16_t i = 0; i < n; i++) {
                char ssid[33];
                memcpy(ssid, aprecs[i].ssid, 32);
                ssid[32] = '\0';
                recs.push_back({std::string(ssid), (int)aprecs[i].rssi});
            }
            free(aprecs);
        }
    }
    std::string json = nsp_scan_json(recs);
    httpd_resp_send(req, json.c_str(), json.size());
    return ESP_OK;
}

esp_err_t nsp_handle_config_save(httpd_req_t *req) {
    std::string body;
    int len = req->content_len;
    if (len > 0 && len < 1024) {
        char buf[1024] = "";
        int r = httpd_req_recv(req, buf, len);
        (void)r;
        body.assign(buf, len);
    }
    // P182: parsing extracted to form_parse.cpp (pure code, HOST-UNIT-TESTED —
    // R1: the setup path is the one that crashed the panel; its input layer
    // must be tested, not trusted).
    std::map<std::string, std::string> f;
    nsp_parse_form(body, f);
    const std::string &ssid = f.count("ssid") ? f["ssid"] : std::string();
    const std::string &psk = f.count("psk") ? f["psk"] : std::string();
    const std::string &hostname = f.count("hostname") ? f["hostname"] : std::string();
    const std::string &server = f.count("mqtt_server") ? f["mqtt_server"] : std::string();
    const std::string &port = f.count("mqtt_port") ? f["mqtt_port"] : std::string();
    const std::string &user = f.count("mqtt_user") ? f["mqtt_user"] : std::string();
    const std::string &pass = f.count("mqtt_pass") ? f["mqtt_pass"] : std::string();

    if (!ssid.empty() && !server.empty()) {  // fresh setup (AP mode)
        g_cfg.wifi_ssid = ssid;
        g_cfg.wifi_psk = psk;
        if (!hostname.empty()) g_cfg.wifi_hostname = hostname;
        // STA completion path: empty ssid keeps the recovered WiFi config
        g_cfg.mqtt_server = server;
        if (!port.empty()) g_cfg.mqtt_port = atoi(port.c_str());
        g_cfg.mqtt_user = user;
        g_cfg.mqtt_pass = pass;
        nsp_config_save();
    }
    const char *ok = "<html><body style='font:14px system-ui;background:#0d1016;"
                     "color:#c8cbce;padding:24px'>Saved — restarting into your "
                     "network. The NSPanelCore AP will disappear.</body></html>";
    httpd_resp_send(req, ok, HTTPD_RESP_USE_STRLEN);
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
    return ESP_OK;
}

void nsp_config_server_start(void) {
    /* P184: the config server IS the web UI now — one httpd serves both
     * modes (status page in station, setup form on the AP). Called from:
     *   - on_ip_event: WiFi recovered but MQTT settings unknown (P148) */
    extern bool nsp_web_start(bool ap_mode);
    if (nsp_web_start(false)) s_server_up = true;
}

bool nsp_config_server_up(void) { return s_server_up; }

void nsp_setup_ap_start(void) {
    /* P182 crash fix (verified by the panel's own serial log):
     *   ESP_ERROR_CHECK esp_wifi_set_default_wifi_ap_handlers() →
     *   ESP_ERR_INVALID_STATE because the DEFAULT EVENT LOOP did not exist
     *   (and esp_netif was not initialized) when the AP netif was created.
     * The STA path had this init; the AP path never did. */
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_create_default_wifi_ap();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    wifi_config_t ap = {};
    strcpy((char *)ap.ap.ssid, "NSPanelCore");
    ap.ap.ssid_len = strlen("NSPanelCore");
    ap.ap.max_connection = 4;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));  // P183: APSTA so the scan works while the AP is up
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_ERROR_CHECK(esp_wifi_start());

    // Default AP netif is 192.168.4.1; pin the documented 192.168.1.1
    esp_netif_t *netif = esp_netif_next(nullptr);
    esp_netif_ip_info_t info;
    memset(&info, 0, sizeof(info));
    info.ip.addr = htonl(0xC0A80101);       // 192.168.1.1
    info.netmask.addr = htonl(0xFFFFFF00);  // 255.255.255.0
    esp_netif_dhcps_stop(netif);
    esp_netif_set_ip_info(netif, &info);
    esp_netif_dhcps_start(netif);

    // Web UI (setup form as root, + status/log/actions)
    nsp_wifi_set_ap_mode(true);
    extern bool nsp_web_start(bool ap_mode);
    if (nsp_web_start(true)) s_server_up = true;
}

bool nsp_setup_ap_up(void) { return s_server_up; }
