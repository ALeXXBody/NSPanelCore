/* NSPanel Core — relay command payload parse (pure, host-testable). */

#include "relay_cmd.h"

int nsp_relay_parse(const std::string &payload) {
    size_t a = 0, b = payload.size();
    while (a < b && (payload[a] == ' ' || payload[a] == '\t' ||
                     payload[a] == '\r' || payload[a] == '\n')) a++;
    while (b > a && (payload[b - 1] == ' ' || payload[b - 1] == '\t' ||
                     payload[b - 1] == '\r' || payload[b - 1] == '\n')) b--;
    if (b - a != 1) return -1;  // exactly one char: "1" or "0"
    if (payload[a] == '1') return 1;
    if (payload[a] == '0') return 0;
    return -1;
}
