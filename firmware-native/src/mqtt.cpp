/* NSPanel Core — MQTT: registration, status reports, command handling.
 * Uses esp-mqtt natively. The version travels in EVERY status report and
 * re-registration happens every 5 minutes (P135 — version never stale). */

#include "mqtt_client.h"
#include "protocol.h"
#include "config.h"
#include "accept_parse.h"
#include "provision_parse.h"
#include "dash_cmd.h"
#include "screensaver_parse.h"

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
    // P306: retained weather + per-panel screensaver style/flags and mode
    esp_mqtt_client_subscribe(s_mqtt, TOPIC_STATUS_WEATHER, 0);
    esp_mqtt_client_subscribe(s_mqtt, topic_panel_screensaver(s_hostname).c_str(), 0);
    esp_mqtt_client_subscribe(s_mqtt, topic_panel_screensaver_mode(s_hostname).c_str(), 0);
    // Relay commands (HA switches drive the physical relays)
    esp_mqtt_client_subscribe(s_mqtt, topic_relay_cmd(s_hostname, 1).c_str(), 1);
    esp_mqtt_client_subscribe(s_mqtt, topic_relay_cmd(s_hostname, 2).c_str(), 1);
    // Register immediately on connect, then every 5 minutes (P135)
    nsp_mqtt_send_register(s_mqtt);
}

/* P208#24: fragmented payloads — esp-mqtt delivers large messages in
 * multiple DATA events; a single-event payload truncated commands. */
static std::string s_frag_topic, s_frag_data;
static bool s_frag_active = false;

void nsp_mqtt_dispatch(const std::string &topic, const std::string &payload);

/* P306: the retained style and weather feeds can arrive in either order.
 * Keep both in RAM and re-render on either arrival so the first paint is
 * complete. All parsing/command construction lives in screensaver_parse.cpp;
 * this file only sends the sanitised commands. */
static NspScreensaverConfig s_screensaver_cfg;
static NspWeatherData s_weather_data;
static bool s_weather_valid = false;
static std::string s_screensaver_mode = "with_background";

static void nsp_screensaver_apply(bool style_changed) {
    extern void nsp_display_send_command(const char *cmd);
    /* Style changes only when the retained config arrives — a weather poll
     * must not re-write 18 attributes down the UART. */
    if (style_changed) {
        for (const auto &cmd : nsp_screensaver_style_commands(s_screensaver_cfg))
            nsp_display_send_command(cmd.c_str());
    }
    /* A dark screen must not be woken by a weather update. */
    if (!s_weather_valid || s_screensaver_mode == "no_screensaver") return;
    extern float nsp_temperature(void);
    float ntc = nsp_temperature();
    char buf[24];
    std::string room;
    if (ntc != 0.0f) {  // 0.0 is the sensor's "no reading" sentinel
        snprintf(buf, sizeof(buf), "%.1f\xB0", ntc);
        room = std::string(buf) + "C";
    }
    for (const auto &cmd : nsp_weather_commands(s_weather_data, s_screensaver_cfg, room))
        nsp_display_send_command(cmd.c_str());
}

static void nsp_mqtt_data(void *handler_args, esp_event_base_t base,
                          int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)event_data;
    std::string topic(ev->topic_len ? ev->topic : "", ev->topic_len);
    if (ev->current_data_offset == 0 && ev->total_data_len > ev->data_len) {
        s_frag_topic = topic;
        s_frag_data.assign(ev->data, ev->data_len);
        s_frag_active = true;
        return;  // first fragment of a fragmented message
    }
    if (s_frag_active) {
        if (topic != s_frag_topic) { s_frag_active = false; return; }
        if (ev->current_data_offset + ev->data_len < ev->total_data_len) {
            s_frag_data.append(ev->data, ev->data_len);
            return;  // still fragmenting
        }
        s_frag_data.append(ev->data, ev->data_len);
        topic = s_frag_topic;
        std::string payload = s_frag_data;
        s_frag_active = false;
        s_frag_data.clear();
        /* fall through to dispatch with the assembled payload */
        std::string assembled = payload;
        payload.swap(assembled);
        extern void nsp_mqtt_dispatch(const std::string &topic, const std::string &payload);
        nsp_mqtt_dispatch(topic, payload);
        return;
    }
    std::string payload(ev->data, ev->data_len);
    nsp_mqtt_dispatch(topic, payload);
}

void nsp_mqtt_dispatch(const std::string &topic, const std::string &payload) {
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
    } else if (topic == TOPIC_STATUS_WEATHER) {
        NspWeatherData data;
        if (nsp_weather_parse(payload, data)) {
            s_weather_data = data;
            s_weather_valid = true;
            nsp_screensaver_apply(false);
        } else {
            nsp_mqtt_publish_log("weather: rejected payload");
        }
    } else if (topic == topic_panel_screensaver(s_hostname)) {
        NspScreensaverConfig cfg;
        if (nsp_screensaver_parse(payload, cfg)) {
            s_screensaver_cfg = cfg;
            nsp_screensaver_apply(true);
        } else {
            nsp_mqtt_publish_log("screensaver: rejected payload");
        }
    } else if (topic == topic_panel_screensaver_mode(s_hostname)) {
        if (!payload.empty() && payload.size() <= 32)
            s_screensaver_mode = payload;
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

/* P208: extract the "command" field properly — substring matching let any
 * payload MENTIONING a command word trigger it. */
static bool nsp_json_command(const std::string &payload, std::string &out) {
    /* P212: the compact form {"command":"x"} has NO space before the
     * colon — find(':') from the KEY start (not k+10, which landed on
     * the closing quote and returned the key itself). */
    size_t k = payload.find("\"command\"");
    if (k == std::string::npos) return false;
    size_t colon = payload.find(':', k);
    if (colon == std::string::npos) return false;
    size_t q1 = payload.find('"', colon + 1);
    if (q1 == std::string::npos) return false;
    size_t q2 = payload.find('"', q1 + 1);
    if (q2 == std::string::npos) return false;
    out = payload.substr(q1 + 1, q2 - q1 - 1);
    return true;
}

void nsp_mqtt_handle_command(const std::string &payload) {
    /* P180: the manager address is NEVER persisted by the v1 line — it is
     * set at runtime from the register_accept (NSPMConfig.cpp:49 wipes it
     * on every load). The migration's NVS seed therefore captured an EMPTY
     * manager address + port 8000, and every native OTA silently failed on
     * http://:8000/... Handle the accept exactly like v1: adopt address+port. */
    std::string cmd_field;
    if (nsp_json_command(payload, cmd_field)) {
        if (cmd_field == "register_accept") {
        /* P184: parsing extracted to accept_parse.cpp (HOST-UNIT-TESTED).
         * P184 fail-safe: a "no change" accept is logged too — the missing
         * adoption evidence cost us a boot loop investigation. */
        std::string addr; int port = 8123;
        if (nsp_parse_register_accept(payload, addr, port)) {
            auto valid_quad = [](const std::string &a) {
                int parts = 0, dots = 0;
                for (char c : a) {
                    if (c == '.') { dots++; if (parts == 0 || parts > 3) return false; parts = 0; continue; }
                    if (c < '0' || c > '9') return false;
                    if (parts >= 3) return false;
                    parts++;
                }
                return dots == 3 && parts > 0;
            };
            if (!addr.empty() && valid_quad(addr) &&
                (addr != g_cfg.manager_address || port != g_cfg.manager_port)) {
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
        /* register_accept with a broken payload: fall through, nothing matches */
    }
    if (!nsp_json_command(payload, cmd_field)) return;
    if (cmd_field == CMD_REBOOT) {
        esp_restart();
    } else if (cmd_field == CMD_FIRMWARE_UPDATE) {
        nsp_ota_start();
    } else if (cmd_field == CMD_TFT_UPDATE) {
        extern void nsp_tft_start(void);  // P210: real OTA TFT delivery
        nsp_tft_start();
    } else if (cmd_field == "dash") {
        /* P234: the dashboard channel — sanitized pass-through to the
         * display (dash_cmd.cpp rejects everything but allow-listed
         * statements). */
        extern void nsp_display_send_command(const char *cmd);
        std::string stmt;
        if (nsp_dash_parse(payload, stmt) == 0) {
            nsp_display_send_command(stmt.c_str());
        } else {
            nsp_mqtt_publish_log("dash: rejected payload");
        }
    } else if (cmd_field == "dash_map") {
        if (nsp_dash_map_apply(payload)) {
            nsp_mqtt_publish_log("dash: page map adopted");
        } else {
            nsp_mqtt_publish_log("dash_map: rejected payload");
        }
    } else if (cmd_field == "set_button_config") {
        /* P312: the manager delivers the physical-button configuration —
         * modes + custom MQTT topics/payloads (the panel never fetched the
         * old JSON config, so the modes were dead at every layer). Fields
         * parsed with the host-tested provision_field extractor. */
        std::string v;
        if (nsp_provision_field(payload, "button1_mode", v))
            g_cfg.button1_mode = atoi(v.c_str());
        if (nsp_provision_field(payload, "button2_mode", v))
            g_cfg.button2_mode = atoi(v.c_str());
        if (nsp_provision_field(payload, "button1_mqtt_topic", v))
            g_cfg.button1_mqtt_topic = v;
        if (nsp_provision_field(payload, "button1_mqtt_payload", v))
            g_cfg.button1_mqtt_payload = v;
        if (nsp_provision_field(payload, "button2_mqtt_topic", v))
            g_cfg.button2_mqtt_topic = v;
        if (nsp_provision_field(payload, "button2_mqtt_payload", v))
            g_cfg.button2_mqtt_payload = v;
        nsp_config_save();
        nsp_mqtt_publish_log("button config applied");
    }
}

void nsp_mqtt_send_register(void) {
    nsp_mqtt_send_register(s_mqtt);
}

/* P312: the physical-button press event (DETACHED/FOLLOW) — the manager
 * routes DETACHED presses to the bound Home Assistant entity. */
void nsp_mqtt_publish_button_event(int button) {
    if (s_mqtt == nullptr) return;
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"button\":%d,\"event\":\"press\"}", button);
    esp_mqtt_client_publish(s_mqtt, topic_button(s_hostname).c_str(), buf, 0, 0, false);
}

/* P312: CUSTOM_MQTT mode — publish the button's configured topic/payload.
 * Empty topic = unconfigured: log it, never publish to a partial topic. */
void nsp_mqtt_publish_button_custom(int button) {
    if (s_mqtt == nullptr) return;
    const std::string &topic = (button == 1) ? g_cfg.button1_mqtt_topic
                                             : g_cfg.button2_mqtt_topic;
    const std::string &payload = (button == 1) ? g_cfg.button1_mqtt_payload
                                               : g_cfg.button2_mqtt_payload;
    if (topic.empty()) {
        char l[80];
        snprintf(l, sizeof(l), "button %d: custom MQTT topic not configured", button);
        nsp_mqtt_publish_log(l);
        return;
    }
    esp_mqtt_client_publish(s_mqtt, topic.c_str(), payload.c_str(), 0, 0, false);
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
    /* P310: mirror EVERY app log line to the serial console. The app used to
     * be silent on UART0 — its story went only to MQTT — so a boot-log capture
     * showed nothing between "Calling app_main()" and a restart. Now the
     * console carries the app's own line at the exact moment anything
     * happens (or dies). */
    printf("[app] %s\n", msg);
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
    if (s_mqtt != nullptr) return;  // P279 HIGH fix: no client leak on re-IP
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
                                       /* P279 LOW fix: a dropped final fragment left
                                        * stale reassembly state — the next complete
                                        * message dispatched as prefix+garbage. */
                                       s_frag_active = false;
                                       s_frag_data.clear();
                                   }, nullptr);
    esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_DATA, nsp_mqtt_data, nullptr);
    esp_mqtt_client_start(s_mqtt);
}
