/* NSPanel Core — MQTT: registration, status reports, command handling.
 * Uses esp-mqtt natively. The version travels in EVERY status report and
 * re-registration happens every 5 minutes (P135 — version never stale). */

#include "mqtt_client.h"
#include "protocol.h"
#include "config.h"

static esp_mqtt_client_handle_t s_mqtt = nullptr;
static std::string s_hostname;

void nsp_mqtt_send_register(esp_mqtt_client_handle_t client);
void nsp_mqtt_handle_command(const std::string &payload);
void nsp_ota_start();

static void nsp_mqtt_connected(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data) {
    if (s_mqtt == nullptr) return;
    // Subscribe to the command topic (hostname verbatim) + manager command
    std::string cmd = topic_panel_cmd(s_hostname);
    esp_mqtt_client_subscribe(s_mqtt, cmd.c_str(), 1);
    esp_mqtt_client_subscribe(s_mqtt, TOPIC_MANAGER_COMMAND, 0);
    // Screensaver clock topics (the manager publishes them every 60 s)
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/time", 0);
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/date", 0);
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/ampm", 0);
    // Register immediately on connect, then every 5 minutes (P135)
    nsp_mqtt_send_register(s_mqtt);
}

static void nsp_mqtt_data(void *handler_args, esp_event_base_t base,
                          int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)event_data;
    std::string topic(ev->topic, ev->topic_len);
    std::string payload(ev->data, ev->data_len);
    if (topic == TOPIC_MANAGER_COMMAND) {
        // register_request arrives here FROM panels; the manager handles it.
        return;
    }
    if (topic == "nspanel/status/time") {
        extern void nsp_display_set_clock(const std::string &);
        nsp_display_set_clock(payload);
    } else if (topic == "nspanel/status/date") {
        extern void nsp_display_set_date(const std::string &);
        nsp_display_set_date(payload);
    } else if (topic == "nspanel/status/ampm") {
        extern void nsp_display_set_ampm(const std::string &);
        nsp_display_set_ampm(payload);
    } else if (topic == topic_panel_cmd(s_hostname)) {
        nsp_mqtt_handle_command(payload);
    }
}

void nsp_mqtt_publish_touch(int page, int component, int event) {
    if (s_mqtt == nullptr) return;
    char buf[96];
    snprintf(buf, sizeof(buf),
        "{\"page\":%d,\"component\":%d,\"event\":%d}", page, component, event);
    esp_mqtt_client_publish(s_mqtt, topic_touch(s_hostname).c_str(), buf, 0, 0, false);
}

void nsp_mqtt_handle_command(const std::string &payload) {
    if (payload.find(CMD_REBOOT) != std::string::npos) {
        esp_restart();
    } else if (payload.find(CMD_FIRMWARE_UPDATE) != std::string::npos) {
        nsp_ota_start();
    } else if (payload.find(CMD_TFT_UPDATE) != std::string::npos) {
        // TFT streaming handled by the display module (baked-in offset guard)
    }
}

void nsp_mqtt_send_register(void) {
    nsp_mqtt_send_register(s_mqtt);
}

void nsp_mqtt_send_register(esp_mqtt_client_handle_t client) {
    if (client == nullptr) return;
    char buf[512];
    snprintf(buf, sizeof(buf),
        "{\"command\":\"register_request\",\"mac_origin\":\"%s\","
        "\"friendly_name\":\"%s\",\"version\":\"" FW_VERSION "\","
        "\"md5_firmware\":\"%s\",\"md5_data_file\":\"%s\","
        "\"md5_tft_file\":\"%s\",\"address\":\"%s\"}",
        g_mac.c_str(), s_hostname.c_str(),
        g_cfg.md5_firmware.c_str(), g_cfg.md5_data_file.c_str(),
        g_cfg.md5_tft_file.c_str(), g_ip.c_str());
    esp_mqtt_client_publish(client, TOPIC_MANAGER_COMMAND, buf, 0, 0, false);
}

void nsp_mqtt_publish_status_report(const std::string &ip, int rssi,
                                    int heap_pct, float temperature,
                                    const std::string &warnings) {
    if (s_mqtt == nullptr) return;
    // P135: version in EVERY status report
    char buf[384];
    snprintf(buf, sizeof(buf),
        "{\"version\":\"" FW_VERSION "\",\"rssi\":%d,\"heap_used_pct\":%d,"
        "\"mac\":\"%s\",\"temperature\":\"%.1f\",\"ip\":\"%s\","
        "\"warnings\":\"%s\"}",
        rssi, heap_pct, g_mac.c_str(), temperature, ip.c_str(),
        warnings.c_str());
    esp_mqtt_client_publish(s_mqtt, topic_status_report(s_hostname).c_str(),
                            buf, 0, 0, true);
}

void nsp_mqtt_start(const std::string &hostname) {
    s_hostname = hostname;
    char uri[128];
    snprintf(uri, sizeof(uri), "mqtt://%s:%d",
             g_cfg.mqtt_server.c_str(), g_cfg.mqtt_port);
    esp_mqtt_client_config_t cfg = {};
    cfg.broker.address.uri = uri;
    cfg.credentials.username = g_cfg.mqtt_user.c_str();
    cfg.credentials.authentication.password = g_cfg.mqtt_pass.c_str();
    cfg.session.keepalive = 30;
    cfg.network.reconnect_timeout_ms = 5000;
    s_mqtt = esp_mqtt_client_init(&cfg);
    esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_CONNECTED, nsp_mqtt_connected, nullptr);
    esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_DATA, nsp_mqtt_data, nullptr);
    esp_mqtt_client_start(s_mqtt);
}
