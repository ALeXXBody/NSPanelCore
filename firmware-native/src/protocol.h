/* NSPanel Core — frozen wire protocol (contract: tests/test_detach_contract.py).
 * Every topic the firmware publishes or subscribes. Never change without a
 * coordinated manager release. */

#ifndef NSP_PROTOCOL_H
#define NSP_PROTOCOL_H

#include <string>

#define FW_VERSION "0.1.39"

/* Publish topics (built from wifi_hostname, VERBATIM — no sanitization) */
inline std::string topic_status_report(const std::string &hostname) {
    return "nspanel/" + hostname + "/status_report";
}
inline std::string topic_relay(const std::string &hostname, int relay) {
    return "nspanel/" + hostname + "/r" + std::to_string(relay) + "_state";
}
inline std::string topic_screen_cmd(const std::string &hostname) {
    return "nspanel/" + hostname + "/screen";
}
inline std::string topic_panel_cmd(const std::string &hostname) {
    return "nspanel/" + hostname + "/command";
}
/* P306: retained "Build the screensaver" payload (style + weather flags +
 * resolved temperature overrides) for one panel. */
inline std::string topic_panel_screensaver(const std::string &hostname) {
    return "nspanel/" + hostname + "/screensaver";
}
/* P306: the panel's resolved screensaver mode (plain text). A dark screen
 * must not be woken by a weather update. */
inline std::string topic_panel_screensaver_mode(const std::string &hostname) {
    return "nspanel/" + hostname + "/screensaver_mode";
}
inline std::string topic_relay_cmd(const std::string &hostname, int relay) {
    return "nspanel/" + hostname + "/r" + std::to_string(relay) + "_cmd";
}
inline std::string topic_relay_state(const std::string &hostname, int relay) {
    return "nspanel/" + hostname + "/r" + std::to_string(relay) + "_state";
}
inline std::string topic_touch(const std::string &hostname) {
    return "nspanel/" + hostname + "/touch";
}
/* P312: the PHYSICAL button press event (DETACHED/FOLLOW modes) — the
 * manager routes DETACHED presses to the bound Home Assistant entity. */
inline std::string topic_button(const std::string &hostname) {
    return "nspanel/" + hostname + "/button";
}
inline std::string topic_log(const std::string &hostname) {
    return "nspanel/" + hostname + "/log";
}

/* Manager topics (fixed) */
#define TOPIC_MANAGER_COMMAND "nspanel/mqttmanager/command"
#define TOPIC_STATUS_TIME     "nspanel/status/time"
#define TOPIC_STATUS_DATE     "nspanel/status/date"
#define TOPIC_STATUS_WEATHER  "nspanel/status/weather"

/* Frozen commands (both generations answer these) */
#define CMD_REBOOT           "reboot"
#define CMD_FIRMWARE_UPDATE  "firmware_update"
#define CMD_TFT_UPDATE       "tft_update"
#define CMD_REGISTER_ACCEPT  "register_accept"

/* Status report cadence + re-registration (P135: version never stale) */
#define STATUS_REPORT_PERIOD_MS 30000
#define REREGISTRATION_PERIOD_MS 300000

#endif
