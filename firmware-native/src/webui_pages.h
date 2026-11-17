/* NSPanel Core — web UI page builders + action routing (pure, host-testable).
 *
 * The pages take a plain status struct — no ESP types — so every byte of
 * HTML/JSON logic runs under the host test suite (R1).
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
};

/* Status page (human) */
std::string nsp_web_status_page(const NspWebStatus &s);
/* Machine-readable status */
std::string nsp_web_status_json(const NspWebStatus &s);
/* Log view page */
std::string nsp_web_log_page(const std::string &logdump);

/* POST /action body parse. Returns:
 * 0 = none/unknown, 1 = reboot, 2 = firmware_update,
 * 3 = display_restart, 4 = factory_reset */
int nsp_web_parse_action(const std::string &body);
