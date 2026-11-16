/* NSPanel Core — WiFi station + config AP fallback. */

#include "esp_wifi.h"
#include "esp_event.h"
#include "protocol.h"
#include "config.h"

static bool s_connected = false;
static int s_rssi = 0;
static char s_ip[16] = "";
static bool s_ap_up = false;

bool nsp_wifi_connected(void) { return s_connected; }
int nsp_wifi_rssi(void) { return s_rssi; }
std::string nsp_wifi_ip(void) { return s_ip; }

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    switch (id) {
    case WIFI_EVENT_STA_START:
        esp_wifi_connect();
        break;
    case WIFI_EVENT_STA_DISCONNECTED:
        s_connected = false;
        s_ip[0] = '\0';
        esp_wifi_connect();  // retry; the config AP path owns the fallback UX
        break;
    default:
        break;
    }
}

static void on_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
    snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
    s_connected = true;
    esp_wifi_sta_get_ap_info(nullptr);  // triggers RSSI cache
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) s_rssi = ap.rssi;
}

void nsp_wifi_start(void) {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_ip_event, nullptr));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    wifi_config_t wcfg = {};
    strncpy((char *)wcfg.sta.ssid, g_cfg.wifi_ssid.c_str(), sizeof(wcfg.sta.ssid) - 1);
    strncpy((char *)wcfg.sta.password, g_cfg.wifi_psk.c_str(), sizeof(wcfg.sta.password) - 1);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wcfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}
