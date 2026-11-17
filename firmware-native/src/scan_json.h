/* NSPanel Core — scan-results formatting (pure, host-testable).
 *
 * Dedup by SSID (keep the strongest RSSI), sort by RSSI desc, emit JSON.
 * The WiFi-scan plumbing stays in the ESP code; this part is unit tested
 * on the host (R1).
 */

#pragma once
#include <string>
#include <vector>
#include <utility>

/* records: (ssid, rssi). Empty SSIDs are skipped. */
std::string nsp_scan_json(const std::vector<std::pair<std::string, int>> &records);
