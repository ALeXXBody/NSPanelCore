/* NSPanel Core — form encoding parser (pure, host-testable). */

#include "form_parse.h"

void nsp_parse_form(const std::string &body, std::map<std::string, std::string> &out) {
    size_t pos = 0;
    while (pos < body.size()) {
        size_t eq = body.find('=', pos);
        if (eq == std::string::npos) break;
        std::string key = body.substr(pos, eq - pos);
        size_t amp = body.find('&', eq);
        size_t val_end = (amp == std::string::npos) ? body.size() : amp;
        std::string raw = body.substr(eq + 1, val_end - (eq + 1));

        std::string dec;
        for (size_t i = 0; i < raw.size(); i++) {
            if (raw[i] == '+') dec += ' ';
            else if (raw[i] == '%' && i + 2 < raw.size()) {
                char hex[3] = {raw[i + 1], raw[i + 2], 0};
                dec += (char)strtol(hex, nullptr, 16);
                i += 2;
            } else dec += raw[i];
        }
        if (!key.empty()) out[key] = dec;
        if (amp == std::string::npos) break;
        pos = amp + 1;
    }
}
