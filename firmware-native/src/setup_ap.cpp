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

// P185: the setup form builder moved to webui_pages.cpp (pure, host-tested,
// v1 design) — nsp_web_setup_page().

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
