/* NSPanel Core — register_accept payload parser (pure, host-testable). */

#include "accept_parse.h"
#include <cstdlib>

static bool extract_quoted(const std::string &s, const char *key, std::string &out) {
    size_t k = s.find(key);
    if (k == std::string::npos) return false;
    // opening quote of the KEY is at k; find the value's opening quote after
    // the key's closing quote.
    size_t key_close = s.find('"', k + 1);   // closing quote of the key name
    if (key_close == std::string::npos) return false;
    size_t vopen = s.find('"', key_close + 1);
    if (vopen == std::string::npos) return false;
    size_t vclose = s.find('"', vopen + 1);
    if (vclose == std::string::npos) return false;
    out = s.substr(vopen + 1, vclose - vopen - 1);
    return true;
}

bool nsp_parse_register_accept(const std::string &payload,
                               std::string &addr, int &port) {
    addr.clear();
    port = 8123;
    if (payload.find("register_accept") == std::string::npos) return false;
    if (!extract_quoted(payload, "\"address\"", addr)) return false;
    if (addr.empty()) return false;
    std::string port_s;
    if (extract_quoted(payload, "\"port\"", port_s)) {
        // quoted port (defensive); fall back to the bare-int form
        int v = atoi(port_s.c_str());
        if (v > 0 && v < 65536) port = v;
    } else {
        size_t p = payload.find("\"port\"");
        if (p != std::string::npos) {
            size_t c = payload.find(':', p + 6);
            if (c != std::string::npos) {
                int v = atoi(payload.c_str() + c + 1);
                if (v > 0 && v < 65536) port = v;
            }
        }
    }
    return true;
}
