/* NSPanel Core — web UI page builders + action routing (pure, host-testable).
 *
 * P185: the pages reuse the PROVEN v1 WebManager design verbatim — the
 * same hand-written CSS (embedded below, byte-identical to the repo's
 * data/static/main.css), the same brandbar/brandmark/theme-toggle
 * classes, the same card/button vocabulary the user already knows.
 * The builders take a plain status struct — no ESP types — so every byte
 * of HTML/JSON logic runs under the host test suite (R1).
 */

#pragma once
#include <string>

struct NspWebStatus {
    std::string mode;         // "setup (AP)" or "station"
    std::string version;
    std::string hostname;
    std::string ip;
    std::string rssi;
    std::string heap_pct;
    std::string temperature;
    std::string warnings;
    std::string mqtt;         // "connected" / "disconnected"
    std::string manager;      // adopted manager address:port (or "not adopted")
    std::string md5_fw;
    std::string md5_fs;
    std::string ota_state;
    std::string ota_progress;
    std::string uptime_s;
    std::string fault_log;    // P317: captured task_wdt/panic lines (survive reboots)
    bool wifi_known;          // setup form prefill state
    std::string wifi_ssid_value;
    std::string hostname_value;
    std::string mqtt_server_value;
    std::string mqtt_port_value;
    std::string mqtt_user_value;
};

/* Status page (human). logdump = the panel log text, embedded in the
 * toggle-gated console card (P207: visible only while the toggle is on). */
std::string nsp_web_status_page(const NspWebStatus &s, const std::string &logdump);
/* Machine-readable status */
std::string nsp_web_status_json(const NspWebStatus &s);
/* Log view page */
std::string nsp_web_log_page(const std::string &logdump);
/* Raw log text for the console card's live polling (P207). */
std::string nsp_web_log_text(const std::string &logdump);
/* Setup/config form (AP root and station reconfig — v1 look) */
std::string nsp_web_setup_page(const NspWebStatus &s);

/* POST /action body parse. Returns:
 * 0 = none/unknown, 1 = reboot, 2 = firmware_update,
 * 3 = display_restart, 4 = factory_reset */
int nsp_web_parse_action(const std::string &body);
