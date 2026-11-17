/* NSPanel Core — scan-results formatting (pure, host-testable). */

#include "scan_json.h"
#include <algorithm>
#include <map>
#include <cstdio>

static std::string json_escape(const std::string &s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += c; }
        else if (c == '\n') o += "\\n";
        else if (c == '\r') o += "\\r";
        else if (c == '\t') o += "\\t";
        else if (static_cast<unsigned char>(c) < 0x20) o += ' ';  // other control chars → space
        else o += c;
    }
    return o;
}

std::string nsp_scan_json(const std::vector<std::pair<std::string, int>> &records) {
    // Dedup: strongest RSSI per SSID (std::map keeps insertion order for ties;
    // overwrite only when strictly stronger so results are deterministic).
    std::map<std::string, int> best;
    for (const auto &r : records) {
        if (r.first.empty()) continue;
        auto it = best.find(r.first);
        if (it == best.end() || r.second > it->second) best[r.first] = r.second;
    }
    // Sort by RSSI desc.
    std::vector<std::pair<std::string, int>> items(best.begin(), best.end());
    std::stable_sort(items.begin(), items.end(),
                     [](const auto &a, const auto &b) { return a.second > b.second; });

    std::string out = "[";
    char buf[48];
    for (size_t i = 0; i < items.size(); i++) {
        snprintf(buf, sizeof(buf), "%d", items[i].second);
        if (i) out += ",";
        out += "{\"ssid\":\"" + json_escape(items[i].first) + "\",\"rssi\":" + buf + "}";
    }
    out += "]";
    return out;
}
