/* NSPanel Core — MQTT: registration, status reports, command handling.
 * Uses esp-mqtt natively. The version travels in EVERY status report and
 * re-registration happens every 5 minutes (P135 — version never stale). */

#include "mqtt_client.h"
#include "protocol.h"
#include "config.h"
#include "accept_parse.h"

static esp_mqtt_client_handle_t s_mqtt = nullptr;
static std::string s_hostname;

void nsp_mqtt_send_register(esp_mqtt_client_handle_t client);
void nsp_mqtt_handle_command(const std::string &payload);
void nsp_mqtt_publish_log(const char *msg);
void nsp_ota_start();

static volatile bool s_mqtt_up = false;
bool nsp_mqtt_connected(void) { return s_mqtt_up; }

static void nsp_mqtt_connected(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data) {
    if (s_mqtt == nullptr) return;
    s_mqtt_up = true;  // P184: the web UI status shows the real link state
    // Subscribe to the command topic (hostname verbatim) + manager command
    std::string cmd = topic_panel_cmd(s_hostname);
    esp_mqtt_client_subscribe(s_mqtt, cmd.c_str(), 1);
    esp_mqtt_client_subscribe(s_mqtt, TOPIC_MANAGER_COMMAND, 0);
    // Screensaver clock topics (the manager publishes them every 60 s)
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/time", 0);
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/date", 0);
    esp_mqtt_client_subscribe(s_mqtt, "nspanel/status/ampm", 0);
    // Relay commands (HA switches drive the physical relays)
    esp_mqtt_client_subscribe(s_mqtt, topic_relay_cmd(s_hostname, 1).c_str(), 1);
    esp_mqtt_client_subscribe(s_mqtt, topic_relay_cmd(s_hostname, 2).c_str(), 1);
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
    } else if (topic == topic_relay_cmd(s_hostname, 1)) {
        extern void nsp_relay_handle_cmd(int, const std::string &);
        nsp_relay_handle_cmd(1, payload);
    } else if (topic == topic_relay_cmd(s_hostname, 2)) {
        extern void nsp_relay_handle_cmd(int, const std::string &);
        nsp_relay_handle_cmd(2, payload);
    } else if (topic == topic_panel_cmd(s_hostname)) {
        nsp_mqtt_handle_command(payload);
    }
}

void nsp_mqtt_publish_relay_state(int relay, bool state) {
    if (s_mqtt == nullptr) return;
    esp_mqtt_client_publish(s_mqtt, topic_relay_state(s_hostname, relay).c_str(),
                            state ? "1" : "0", 0, 0, true);
}

void nsp_mqtt_publish_touch(int page, int component, int event) {
    if (s_mqtt == nullptr) return;
    char buf[96];
    snprintf(buf, sizeof(buf),
        "{\"page\":%d,\"component\":%d,\"event\":%d}", page, component, event);
    esp_mqtt_client_publish(s_mqtt, topic_touch(s_hostname).c_str(), buf, 0, 0, false);
}

void nsp_mqtt_handle_command(const std::string &payload) {
    /* P180: the manager address is NEVER persisted by the v1 line — it is
     * set at runtime from the register_accept (NSPMConfig.cpp:49 wipes it
     * on every load). The migration's NVS seed therefore captured an EMPTY
     * manager address + port 8000, and every native OTA silently failed on
     * http://:8000/... Handle the accept exactly like v1: adopt address+port. */
    if (payload.find("register_accept") != std::string::npos) {
        /* P184: parsing extracted to accept_parse.cpp (HOST-UNIT-TESTED).
         * P184 fail-safe: a "no change" accept is logged too — the missing
         * adoption evidence cost us a boot loop investigation. */
        std::string addr; int port = 8123;
        if (nsp_parse_register_accept(payload, addr, port)) {
            if (addr != g_cfg.manager_address || port != g_cfg.manager_port) {
                g_cfg.manager_address = addr;
                g_cfg.manager_port = port;
                nsp_config_save();
                char l[128];
                snprintf(l, sizeof(l), "manager address adopted: %s:%d", addr.c_str(), port);
                nsp_mqtt_publish_log(l);
            } else {
                nsp_mqtt_publish_log("manager accept: address already adopted (no change)");
            }
        } else {
            nsp_mqtt_publish_log("manager accept: malformed payload ignored");
        }
        return;
    }
    if (payload.find(CMD_REBOOT) != std::string::npos) {
        esp_restart();
    } else if (payload.find(CMD_FIRMWARE_UPDATE) != std::string::npos) {
        nsp_ota_start();
    } else if (payload.find(CMD_TFT_UPDATE) != std::string::npos) {
        extern void nsp_tft_start(void);  // P210: real OTA TFT delivery
        nsp_tft_start();
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

/* P179 diagnostic: OTA milestones on the panel log topic — the same channel
 * the v1 line used; wire-visible evidence of where the OTA stops. */
void nsp_mqtt_publish_log(const char *msg) {
    extern void nsp_web_log(const std::string &);
    nsp_web_log(msg);  // P184: every OTA/manager event is visible on the panel web UI
    if (s_mqtt == nullptr) return;
    esp_mqtt_client_publish(s_mqtt, topic_log(s_hostname).c_str(), msg, 0, 0, false);
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
    esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_DISCONNECTED,
                                   [](void *, esp_event_base_t, int32_t, void *) {
                                       s_mqtt_up = false;  // P184 fail-safe: the status page reflects reality
                                   }, nullptr);
    esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_DATA, nsp_mqtt_data, nullptr);
    esp_mqtt_client_start(s_mqtt);
}
