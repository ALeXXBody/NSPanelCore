/* NSPanel Core — the panel's own web UI (ESP wiring).
 *
 * P184: the user's standing request — "the best solution for these issues
 * is a webui". This is the local surface the panel never had:
 * status page, self-triggered OTA, display restart, factory reset, and an
 * in-RAM log view. ONE httpd serves both modes (setup AP and station);
 * the root page switches by mode (setup form vs status).
 *
 * Endpoints: GET / (status or setup), GET /status.json, GET /log,
 * GET /scan, POST /save (config form), POST /action.
 */

#include "esp_http_server.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "nvs.h"
#include "protocol.h"
#include "config.h"
#include "form_parse.h"
#include "scan_json.h"
#include "webui_pages.h"
#include "logbuf.h"
#include <string>
#include <vector>
#include <utility>
#include <cstdio>
#include <cstring>

static NspLogBuf s_logbuf(64);

void nsp_web_log(const std::string &line) {
    s_logbuf.add(line);
}

extern void nsp_mqtt_publish_log(const char *msg);
extern void nsp_ota_start();
extern bool nsp_display_restart(void);
extern std::string nsp_fault_dump(void);  // P317
extern bool nsp_mqtt_connected(void);
extern int nsp_wifi_rssi(void);
extern std::string nsp_wifi_ip(void);
extern float nsp_temperature(void);
extern const char *nsp_display_warning(void);
extern int nsp_ota_progress(void);
extern int nsp_ota_state(void);   // 0 idle, 1 fw, 2 fs (enum OtaState)
extern void nsp_config_server_start(void);
extern bool nsp_wifi_is_ap_mode(void);

static bool s_web_up = false;

static const char *ota_state_name(int state) {
    switch (state) {
    case 1: return "updating firmware";
    case 2: return "updating filesystem";
    default: return "idle";
    }
}

static NspWebStatus nsp_web_gather_status(void) {
    NspWebStatus s;
    s.mode = nsp_wifi_is_ap_mode() ? "setup (AP)" : "station";
    s.version = FW_VERSION;
    s.hostname = g_cfg.wifi_hostname.empty() ? "(unset)" : g_cfg.wifi_hostname;
    s.ip = nsp_wifi_is_ap_mode() ? "192.168.1.1 (AP)" : nsp_wifi_ip();
    s.rssi = std::to_string(nsp_wifi_rssi()) + " dBm";
    uint32_t heap = esp_get_free_heap_size();
    s.heap_pct = std::to_string(100 - (int)((100ULL * heap) / 320000)) + " %";
    char tb[16];
    snprintf(tb, sizeof(tb), "%.1f °C", nsp_temperature());
    s.temperature = tb;
    s.warnings = nsp_display_warning();
    s.mqtt = (g_cfg.mqtt_server.empty()) ? "not configured"
             : (nsp_mqtt_connected() ? "connected" : "disconnected");
    s.manager = g_cfg.manager_address.empty()
        ? "not adopted"
        : g_cfg.manager_address + ":" + std::to_string(g_cfg.manager_port);
    s.md5_fw = g_cfg.md5_firmware.empty() ? "(none)" : g_cfg.md5_firmware;
    s.md5_fs = g_cfg.md5_data_file.empty() ? "(none)" : g_cfg.md5_data_file;
    int st = nsp_ota_state();
    s.ota_state = ota_state_name(st);
    s.ota_progress = std::to_string(nsp_ota_progress()) + " %";
    s.uptime_s = std::to_string((long long)(esp_timer_get_time() / 1000000LL));
    s.fault_log = nsp_fault_dump();  // P317: the captured death diagnostics
    return s;
}

/* ---- handlers ---- */

static bool s_ap_mode = false;  // root page switches by mode

static esp_err_t on_get_root(httpd_req_t *req) {
    NspWebStatus s = nsp_web_gather_status();
    if (s_ap_mode) {
        // Fresh/unconfigured: the setup form (v1 design) is the root.
        s.wifi_known = !g_cfg.wifi_ssid.empty();
        s.wifi_ssid_value = g_cfg.wifi_ssid;
        s.hostname_value = g_cfg.wifi_hostname;
        s.mqtt_server_value = g_cfg.mqtt_server;
        s.mqtt_port_value = std::to_string(g_cfg.mqtt_port);
        s.mqtt_user_value = g_cfg.mqtt_user;
        std::string page = nsp_web_setup_page(s);
        httpd_resp_send(req, page.c_str(), page.size());
        return ESP_OK;
    }
    std::string page = nsp_web_status_page(s, s_logbuf.dump());
    httpd_resp_send(req, page.c_str(), page.size());
    return ESP_OK;
}

static esp_err_t on_get_status_json(httpd_req_t *req) {
    std::string js = nsp_web_status_json(nsp_web_gather_status());
    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, js.c_str(), js.size());
    return ESP_OK;
}

static esp_err_t on_get_log(httpd_req_t *req) {
    std::string page = nsp_web_log_page(s_logbuf.dump());
    httpd_resp_send(req, page.c_str(), page.size());
    return ESP_OK;
}

/* P207: raw log text for the console card's live polling. */
static esp_err_t on_get_log_text(httpd_req_t *req) {
    std::string text = nsp_web_log_text(s_logbuf.dump());
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_send(req, text.c_str(), text.size());
    return ESP_OK;
}

/* Factory reset fail-safe: erase the nspcfg namespace, reboot into the
 * setup AP. Confirmation happens in the browser button. */
static void nsp_factory_reset(void) {
    nvs_handle_t h;
    if (nvs_open("nspcfg", NVS_READWRITE, &h) == ESP_OK) {
        nvs_erase_all(h);
        nvs_commit(h);
        nvs_close(h);
    }
}

/* P208#1 (web audit): CSRF guard — a cross-site no-cors fetch cannot set
 * custom headers; requiring one blocks drive-by factory resets. */
bool nsp_web_post_ok(httpd_req_t *req) {  // P279: shared with provision.cpp
    if (req->content_len <= 0 || req->content_len > 1024) return false;
    char ct[64] = "";
    if (httpd_req_get_hdr_value_str(req, "Content-Type", ct, sizeof(ct)) != ESP_OK) {
        return false;
    }
    if (strstr(ct, "application/x-www-form-urlencoded") == nullptr) return false;
    char hdr[8] = "";
    return httpd_req_get_hdr_value_str(req, "X-NSPanel", hdr, sizeof(hdr)) == ESP_OK;
}

static esp_err_t on_post_action(httpd_req_t *req) {
    if (!nsp_web_post_ok(req)) {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Forbidden");
        return ESP_OK;
    }
    std::string body;
    int len = req->content_len;
    if (len > 0 && len < 256) {
        char buf[256] = "";
        int r = httpd_req_recv(req, buf, len);
        (void)r;
        body.assign(buf, len);
    }
    int action = nsp_web_parse_action(body);
    const char *msg = "unknown action";
    switch (action) {
    case 1:
        nsp_mqtt_publish_log("webui: reboot requested");  // P315: writes both channels
        msg = "Rebooting…";
        httpd_resp_send(req, msg, strlen(msg));
        vTaskDelay(pdMS_TO_TICKS(800));
        esp_restart();
        return ESP_OK;
    case 2:
        nsp_mqtt_publish_log("webui: firmware update requested");  // P315: writes both channels
        nsp_ota_start();
        msg = "OTA started — watch the status page";
        break;
    case 3:
        nsp_mqtt_publish_log("webui: display restart requested");  // P315: writes both channels
        msg = nsp_display_restart() ? "Display reconnected"
                                    : "Display still not responding";
        break;
    case 4:
        nsp_mqtt_publish_log("webui: FACTORY RESET requested");  // P315: writes both channels
        nsp_factory_reset();
        msg = "Config erased — restarting into the setup AP";
        httpd_resp_send(req, msg, strlen(msg));
        vTaskDelay(pdMS_TO_TICKS(800));
        esp_restart();
        return ESP_OK;
    default:
        break;
    }
    httpd_resp_send(req, msg, strlen(msg));
    return ESP_OK;
}

static esp_err_t on_post_save(httpd_req_t *req) {
    if (!nsp_web_post_ok(req)) {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Forbidden");
        return ESP_OK;
    }
    // The config form — same handler as the setup portal (shared module).
    extern esp_err_t nsp_handle_config_save(httpd_req_t *req);
    return nsp_handle_config_save(req);
}

static esp_err_t on_get_scan(httpd_req_t *req) {
    extern esp_err_t nsp_handle_scan(httpd_req_t *req);
    return nsp_handle_scan(req);
}

bool nsp_web_up(void) { return s_web_up; }

/* Registers ALL handlers on a fresh httpd and starts it. */
bool nsp_web_start(bool ap_mode) {
    if (s_web_up) return true;
    s_ap_mode = ap_mode;
    httpd_handle_t server = nullptr;
    httpd_config_t hcfg = HTTPD_DEFAULT_CONFIG();
    if (httpd_start(&server, &hcfg) != ESP_OK) return false;
    httpd_uri_t root = {"/", HTTP_GET, on_get_root, nullptr};
    httpd_uri_t status = {"/status.json", HTTP_GET, on_get_status_json, nullptr};
    httpd_uri_t log = {"/log", HTTP_GET, on_get_log, nullptr};
    httpd_uri_t logtext = {"/log_text", HTTP_GET, on_get_log_text, nullptr};
    extern esp_err_t nsp_handle_provision(httpd_req_t *req);
    httpd_uri_t provision = {"/provision", HTTP_POST, nsp_handle_provision, nullptr};
    httpd_uri_t scan = {"/scan", HTTP_GET, on_get_scan, nullptr};
    httpd_uri_t save = {"/save", HTTP_POST, on_post_save, nullptr};
    httpd_uri_t action = {"/action", HTTP_POST, on_post_action, nullptr};
    httpd_register_uri_handler(server, &root);
    httpd_register_uri_handler(server, &status);
    httpd_register_uri_handler(server, &log);
    httpd_register_uri_handler(server, &logtext);
    httpd_register_uri_handler(server, &provision);
    httpd_register_uri_handler(server, &scan);
    httpd_register_uri_handler(server, &save);
    httpd_register_uri_handler(server, &action);
    s_web_up = true;
    nsp_web_log(std::string("webui started (") + (ap_mode ? "setup AP" : "station") + ")");
    return true;
}
