/* NSPanel Core — setup AP: first-boot configuration portal.
 *
 * When no config is stored (fresh NVS), the panel raises the NSPanelCore
 * AP with a minimal config form. Saving writes NVS and reboots into STA.
 * This is the native-firmware equivalent of the v1 setup page — smaller,
 * no filesystem dependency (page served from RAM).
 */

#include "esp_wifi.h"
#include "esp_http_server.h"
#include "protocol.h"
#include "config.h"
#include <string>
#include <cstring>
#include <arpa/inet.h>

static std::string nsp_build_setup_page() {
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
    "input{width:100%;padding:8px;margin:4px 0 12px;background:#141a24;"
    "border:1px solid #232c3b;border-radius:6px;color:#c8cbce;box-sizing:border-box}"
    "button{width:100%;padding:10px;background:#2277aa;color:#fff;border:0;"
    "border-radius:6px;font-size:15px}label{color:#8b93a1;font-size:12px}"
    ".note{color:#8b93a1;font-size:12px}</style></head>"
    "<body><h1>NSPanel <span>Core</span> setup</h1>"
    "<form method=POST action=/save>"
    "<label>WiFi SSID</label><input name=ssid " + ssid_attr + (wifi_known ? "" : " required") + ">"
    + wifi_note +
    "<label>WiFi password</label><input name=psk type=password>"
    "<label>Panel name (hostname)</label><input name=hostname value='" + g_cfg.wifi_hostname + "'>"
    "<label>MQTT server</label><input name=mqtt_server required>"
    "<label>MQTT port</label><input name=mqtt_port value='1883'>"
    "<label>MQTT username</label><input name=mqtt_user>"
    "<label>MQTT password</label><input name=mqtt_pass type=password>"
    "<button>Save &amp; restart</button></form></body></html>";
    return page;
}

static bool s_server_up = false;

static esp_err_t on_get_root(httpd_req_t *req) {
    std::string page = nsp_build_setup_page();
    httpd_resp_send(req, page.c_str(), page.size());
    return ESP_OK;
}

static esp_err_t on_post_save(httpd_req_t *req) {
    std::string body;
    int len = req->content_len;
    if (len > 0 && len < 1024) {
        char buf[1024] = "";
        int r = httpd_req_recv(req, buf, len);
        (void)r;
        body.assign(buf, len);
    }
    // Naive form-encode parse (urldecode in-place, minimal)
    auto find = [&](const char *key, std::string &out) {
        std::string needle = std::string(key) + "=";
        size_t pos = body.find(needle);
        if (pos == std::string::npos) return;
        pos += strlen(needle.c_str());
        size_t end = body.find('&', pos);
        std::string raw = body.substr(pos, end == std::string::npos ? std::string::npos : end - pos);
        // urldecode: + → space, %XX
        std::string dec;
        for (size_t i = 0; i < raw.size(); i++) {
            if (raw[i] == '+') dec += ' ';
            else if (raw[i] == '%' && i + 2 < raw.size()) {
                char hex[3] = {raw[i + 1], raw[i + 2], 0};
                dec += (char)strtol(hex, nullptr, 16);
                i += 2;
            } else dec += raw[i];
        }
        out = dec;
    };
    std::string ssid, psk, hostname, server, port, user, pass;
    find("ssid", ssid);
    find("psk", psk);
    find("hostname", hostname);
    find("mqtt_server", server);
    find("mqtt_port", port);
    find("mqtt_user", user);
    find("mqtt_pass", pass);

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
    // Serve the config form over the CURRENT interface (AP or STA).
    nsp_config_server_start();
}

bool nsp_config_server_up(void) { return s_server_up; }

void nsp_setup_ap_start(void) {
    if (s_server_up) return;
    s_server_up = true;

    esp_netif_create_default_wifi_ap();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    wifi_config_t ap = {};
    strcpy((char *)ap.ap.ssid, "NSPanelCore");
    ap.ap.ssid_len = strlen("NSPanelCore");
    ap.ap.max_connection = 4;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
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

    httpd_handle_t server = nullptr;
    httpd_config_t hcfg = HTTPD_DEFAULT_CONFIG();
    if (httpd_start(&server, &hcfg) == ESP_OK) {
        httpd_uri_t root = {"/", HTTP_GET, on_get_root, nullptr};
        httpd_uri_t save = {"/save", HTTP_POST, on_post_save, nullptr};
        httpd_register_uri_handler(server, &root);
        httpd_register_uri_handler(server, &save);
    }
}

bool nsp_setup_ap_up(void) { return s_server_up; }
