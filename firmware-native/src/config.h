/* NSPanel Core — persistent config in NVS (no fs round-trips). */

#include "nvs_flash.h"
#include "nvs.h"
#include <string>

struct NSPConfig {
    std::string wifi_ssid;
    std::string wifi_psk;
    std::string wifi_hostname = "NSPanelCore";
    std::string mqtt_server;
    int32_t mqtt_port = 1883;
    std::string mqtt_user;
    std::string mqtt_pass;
    std::string manager_address;
    int32_t manager_port = 8123;
    bool reverse_relays = false;
    int32_t button1_mode = 0;  // canonical enum: 0=DIRECT 1=DETACHED 2=CUSTOM_MQTT 3=FOLLOW
    int32_t button2_mode = 0;
    std::string button1_mqtt_topic;
    std::string button1_mqtt_payload;
    std::string button2_mqtt_topic;
    std::string button2_mqtt_payload;
    std::string md5_firmware;
    std::string md5_data_file;
    std::string md5_tft_file;
    uint32_t tft_md5_seq = 0;  // P352: bumped at EVERY "delivered md5 recorded" — the
                               // manager distinguishes a fresh record from a stale one
                               // by this counter (a record BEFORE the send armed can
                               // never count as the delivery's proof)
    uint8_t relay1_default = 0;  // P359: the boot state — the STUDIO's "default mode"
    uint8_t relay2_default = 0;  // selection (1 = on); dead until this lands
};

inline NSPConfig g_cfg;

inline bool nsp_config_load() {
    nvs_handle_t h;
    if (nvs_open("nspcfg", NVS_READONLY, &h) != ESP_OK) return false;
    char buf[128];
    size_t len;
    auto get = [&](const char *key, std::string &out) {
        len = sizeof(buf);
        if (nvs_get_str(h, key, buf, &len) == ESP_OK) out.assign(buf, len - 1);
    };
    get("ssid", g_cfg.wifi_ssid);
    get("psk", g_cfg.wifi_psk);
    get("hostname", g_cfg.wifi_hostname);
    get("mqtt_server", g_cfg.mqtt_server);
    nvs_get_i32(h, "mqtt_port", &g_cfg.mqtt_port);
    get("mqtt_user", g_cfg.mqtt_user);
    get("mqtt_pass", g_cfg.mqtt_pass);
    get("manager", g_cfg.manager_address);
    nvs_get_i32(h, "manager_port", &g_cfg.manager_port);
    nvs_get_u8(h, "reverse_relays", (uint8_t *)&g_cfg.reverse_relays);
    nvs_get_i32(h, "btn1_mode", &g_cfg.button1_mode);
    nvs_get_i32(h, "btn2_mode", &g_cfg.button2_mode);
    get("btn1_topic", g_cfg.button1_mqtt_topic);
    get("btn1_payload", g_cfg.button1_mqtt_payload);
    get("btn2_topic", g_cfg.button2_mqtt_topic);
    get("btn2_payload", g_cfg.button2_mqtt_payload);
    get("md5_fw", g_cfg.md5_firmware);
    get("md5_fs", g_cfg.md5_data_file);
    get("md5_tft", g_cfg.md5_tft_file);
    nvs_get_u32(h, "tft_md5_seq", &g_cfg.tft_md5_seq);
    nvs_get_u8(h, "relay1_default", &g_cfg.relay1_default);
    nvs_get_u8(h, "relay2_default", &g_cfg.relay2_default);
    nvs_close(h);
    return !g_cfg.wifi_ssid.empty();
}

inline bool nsp_config_save() {
    nvs_handle_t h;
    if (nvs_open("nspcfg", NVS_READWRITE, &h) != ESP_OK) return false;
    auto set = [&](const char *key, const std::string &v) {
        nvs_set_str(h, key, v.c_str());
    };
    set("ssid", g_cfg.wifi_ssid);
    set("psk", g_cfg.wifi_psk);
    set("hostname", g_cfg.wifi_hostname);
    set("mqtt_server", g_cfg.mqtt_server);
    nvs_set_i32(h, "mqtt_port", g_cfg.mqtt_port);
    set("mqtt_user", g_cfg.mqtt_user);
    set("mqtt_pass", g_cfg.mqtt_pass);
    set("manager", g_cfg.manager_address);
    nvs_set_i32(h, "manager_port", g_cfg.manager_port);
    nvs_set_u8(h, "reverse_relays", g_cfg.reverse_relays ? 1 : 0);
    nvs_set_i32(h, "btn1_mode", g_cfg.button1_mode);
    nvs_set_i32(h, "btn2_mode", g_cfg.button2_mode);
    set("btn1_topic", g_cfg.button1_mqtt_topic);
    set("btn1_payload", g_cfg.button1_mqtt_payload);
    set("btn2_topic", g_cfg.button2_mqtt_topic);
    set("btn2_payload", g_cfg.button2_mqtt_payload);
    set("md5_fw", g_cfg.md5_firmware);
    set("md5_fs", g_cfg.md5_data_file);
    set("md5_tft", g_cfg.md5_tft_file);
    nvs_set_u32(h, "tft_md5_seq", g_cfg.tft_md5_seq);
    nvs_set_u8(h, "relay1_default", g_cfg.relay1_default);
    nvs_set_u8(h, "relay2_default", g_cfg.relay2_default);
    esp_err_t err = nvs_commit(h);
    nvs_close(h);
    return err == ESP_OK;
}

/* Called after a successful OTA to persist the new checksums. */
inline void nsp_config_set_md5s(const std::string &fw, const std::string &fs) {
    g_cfg.md5_firmware = fw;
    g_cfg.md5_data_file = fs;
    nsp_config_save();
}

/* Shared runtime globals (set once in app_main). */
inline std::string g_mac;
inline std::string g_ip;

/* P184: web UI mode switch (setup AP vs station root page) */
bool nsp_wifi_is_ap_mode(void);
void nsp_wifi_set_ap_mode(bool v);
