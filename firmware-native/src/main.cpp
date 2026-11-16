/* NSPanel Core — app entry: NVS, WiFi, MQTT, display, housekeeping.
 *
 * Boot order (all lessons baked in):
 * NVS → config → display init (gentle, never power-cycle) → WiFi → MQTT →
 * registration (immediate + every 5 min) → status reports (30s, version
 * included) → OTA watchdog check (1s).
 */

#include "esp_event.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "esp_system.h"
#include "esp_mac.h"
#include "esp_adc/adc_oneshot.h"
#include <cstdio>
#include <string>
#include "protocol.h"
#include "config.h"

extern void nsp_wifi_start(void);
extern bool nsp_wifi_connected(void);
extern int nsp_wifi_rssi(void);
extern std::string nsp_wifi_ip(void);
extern void nsp_mqtt_start(const std::string &hostname);
extern void nsp_mqtt_send_register(void);
extern void nsp_mqtt_publish_status_report(const std::string &ip, int rssi,
                                           int heap_pct, float temperature,
                                           const std::string &warnings);
extern void nsp_display_init(void);
extern const char *nsp_display_warning(void);
extern void nsp_ota_watchdog_feed_check(void);
extern float nsp_temperature(void);

static std::string s_mac;
static int64_t s_last_register_us = 0;
static int64_t s_last_report_us = 0;

void nsp_setup_ap_start(void);  // declared at FILE scope — inside the
                               // extern "C" app_main it would get C linkage
                               // and never link against the C++ definition

/* NTC 10k (B=3950) on GPIO39/ADC1_CH7 — same hardware the v1 firmware used. */
#include "esp_adc/adc_oneshot.h"
#include <cmath>
static adc_oneshot_unit_handle_t s_adc = nullptr;
static bool s_adc_init = false;
float nsp_temperature() {
    if (!s_adc_init) {
        adc_oneshot_unit_init_cfg_t init = {};
        init.unit_id = ADC_UNIT_1;
        if (adc_oneshot_new_unit(&init, &s_adc) != ESP_OK) return 0.0f;
        adc_oneshot_chan_cfg_t chan = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12 };
        if (adc_oneshot_config_channel(s_adc, ADC_CHANNEL_7, &chan) != ESP_OK) return 0.0f;
        s_adc_init = true;
    }
    int raw = 0;
    if (adc_oneshot_read(s_adc, ADC_CHANNEL_7, &raw) != ESP_OK || raw <= 1) return 0.0f;
    float r = 10000.0f * raw / (4095.0f - raw);
    return 1.0f / (1.0f / 298.15f + logf(r / 10000.0f) / 3950.0f) - 273.15f;
}


extern "C" void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());  // factory NVS holds config
    nsp_config_load();

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char macbuf[18];
    snprintf(macbuf, sizeof(macbuf), "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    s_mac = macbuf;
    g_mac = macbuf;

    // Display FIRST, gently — never blocks the network path (P130).
    nsp_display_init();

    if (g_cfg.wifi_ssid.empty()) {
        // Unconfigured (fresh NVS): the setup AP owns first boot.
        nsp_setup_ap_start();
    } else {
        nsp_wifi_start();  // station; nsp_wifi registers the GOT_IP handler
    }

    for (;;) {
        int64_t now = esp_timer_get_time();
        if (nsp_wifi_connected()) {
            // P135: re-register every 5 minutes
            if (now - s_last_register_us > (int64_t)REREGISTRATION_PERIOD_MS * 1000) {
                extern void nsp_mqtt_send_register(void);
                nsp_mqtt_send_register();
                s_last_register_us = now;
            }
            // Status report every 30s, version included
            if (now - s_last_report_us > (int64_t)STATUS_REPORT_PERIOD_MS * 1000) {
                uint32_t heap = esp_get_free_heap_size();
                uint32_t total = esp_get_free_heap_size() + heap;
                (void)total;
                int pct = 100 - (int)((100ULL * heap) / 320000);
                nsp_mqtt_publish_status_report(
                    nsp_wifi_ip(), nsp_wifi_rssi(), pct,
                    nsp_temperature(), nsp_display_warning());
                s_last_report_us = now;
            }
        }
        nsp_ota_watchdog_feed_check();  // P133 seatbelt (native)
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
