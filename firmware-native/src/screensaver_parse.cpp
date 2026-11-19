/* NSPanel Core — screensaver style + weather parse (pure, host-testable).
 * P306 / fw 0.1.14. See screensaver_parse.h for the wire contract. */

#include "screensaver_parse.h"

#include <cctype>

namespace {

/* Read a JSON string value. The manager emits json.dumps() payloads, so a
 * degree sign arrives as the escape \u00b0 (and quotes as \"). Those two
 * escapes are decoded; ANY other backslash escape rejects the field. This is
 * the P208 lesson: nothing unvalidated ever becomes a display command. */
bool json_string(const std::string &payload, const char *key, std::string &out) {
    const std::string needle = std::string("\"") + key + "\"";
    size_t k = payload.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = payload.find(':', k + needle.size());
    if (colon == std::string::npos) return false;
    size_t q1 = payload.find('"', colon + 1);
    if (q1 == std::string::npos) return false;
    std::string value;
    for (size_t i = q1 + 1; i < payload.size(); i++) {
        unsigned char c = (unsigned char)payload[i];
        if (c == '\\') {
            if (i + 1 >= payload.size()) return false;
            char n = payload[i + 1];
            if (n == '"') { value.push_back('"'); i++; continue; }
            /* \u00b0 -> the Latin-1 glyph the compiled .zi font carries. */
            if (n == 'u' && i + 5 < payload.size() && payload[i + 2] == '0' &&
                payload[i + 3] == '0' &&
                (payload[i + 4] == 'b' || payload[i + 4] == 'B') &&
                payload[i + 5] == '0') {
                value.push_back((char)0xB0);
                i += 5;
                continue;
            }
            return false;
        }
        if (c == '"') { out = value; return true; }
        value.push_back((char)c);
    }
    return false;  // unterminated
}

bool json_bool(const std::string &payload, const char *key, bool &out) {
    const std::string needle = std::string("\"") + key + "\"";
    size_t k = payload.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = payload.find(':', k + needle.size());
    if (colon == std::string::npos) return false;
    size_t p = colon + 1;
    while (p < payload.size() && std::isspace((unsigned char)payload[p])) p++;
    if (payload.compare(p, 4, "true") == 0) { out = true; return true; }
    if (payload.compare(p, 5, "false") == 0) { out = false; return true; }
    return false;
}

/* Return a balanced {...} substring for a named object, or "" when absent. */
std::string json_object(const std::string &payload, const char *key) {
    const std::string needle = std::string("\"") + key + "\"";
    size_t k = payload.find(needle);
    if (k == std::string::npos) return "";
    size_t lb = payload.find('{', k + needle.size());
    if (lb == std::string::npos) return "";
    int depth = 0;
    for (size_t i = lb; i < payload.size(); i++) {
        if (payload[i] == '{') depth++;
        else if (payload[i] == '}') {
            if (--depth == 0) return payload.substr(lb, i - lb + 1);
        }
    }
    return "";
}

/* The font-order contract from scripts/make_screensaver_fonts.py. */
int font_base(const std::string &key, bool is_date) {
    if (key == "small") return 0;
    if (key == "medium") return 2;
    if (key == "large") return 4;
    if (!is_date && key == "xlarge") return 6;
    return -1;
}

int align_id(const std::string &key) {
    if (key == "left") return 0;
    if (key == "right") return 2;
    return 1;  // center is also the safe default for a missing/bad value
}

uint16_t style_color(const std::string &obj, uint16_t fallback) {
    std::string v;
    return json_string(obj, "color", v) ? nsp_rgb565(v, fallback) : fallback;
}

void parse_style(const std::string &obj, bool is_date, NspTextStyle &s) {
    const int default_base = is_date ? 0 : 4;
    const uint16_t default_color = is_date ? 0x8C94 : 0xCE59;  // #8b93a1 / #c8cbce
    int base = default_base;
    bool bold = false;
    std::string v;
    if (json_string(obj, "font", v)) {
        int b = font_base(v, is_date);
        if (b >= 0) base = b;
    }
    if (json_string(obj, "weight", v)) bold = (v == "bold");
    s.font_id = base + (bold ? 1 : 0);
    s.pco = style_color(obj, default_color);
    s.align = json_string(obj, "align", v) ? align_id(v) : 1;
}

/* A compact forecast strip that fits the component's 24-byte .txt limit. */
std::string forecast_summary(const NspWeatherData &data) {
    std::string out;
    for (int i = 0; i < data.day_count; i++) {
        std::string entry = nsp_display_clean(data.day[i], 5) + " " +
                            nsp_display_clean(data.day_maxmin[i], 16);
        if (entry.empty() || entry == " ") continue;
        if (out.empty()) {
            if (entry.size() <= 24) out = entry;
        } else if (out.size() + 1 + entry.size() <= 24) {
            out += " ";
            out += entry;
        } else {
            break;
        }
    }
    return out;
}

}  // namespace

std::string nsp_display_clean(const std::string &value, std::size_t max) {
    std::string out;
    for (size_t i = 0; i < value.size() && out.size() < max; i++) {
        unsigned char c = (unsigned char)value[i];
        /* UTF-8 degree (C2 B0) -> the single Latin-1 byte the .zi font has. */
        if (c == 0xC2 && i + 1 < value.size() &&
            (unsigned char)value[i + 1] == 0xB0) {
            out.push_back((char)0xB0);
            i++;
            continue;
        }
        if (c >= 32 && c <= 126) {
            /* Quotes/backslash/semicolon/<> break or smuggle a Nextion
             * statement; '=' is dropped for defence in depth. */
            if (c == '"' || c == '\\' || c == ';' || c == '<' || c == '>' ||
                c == '=' || c == ',') continue;
            out.push_back((char)c);
            continue;
        }
        if (c == 0xB0) { out.push_back((char)c); continue; }  // already Latin-1
        /* everything else (0xFF terminator, controls, unknown high bytes) */
    }
    return out;
}

uint16_t nsp_rgb565(const std::string &hex, uint16_t fallback) {
    if (hex.size() != 7 || hex[0] != '#') return fallback;
    unsigned value = 0;
    for (int i = 1; i < 7; i++) {
        unsigned char c = (unsigned char)hex[i];
        unsigned digit;
        if (c >= '0' && c <= '9') digit = c - '0';
        else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
        else return fallback;
        value = (value << 4) | digit;
    }
    unsigned r = (value >> 16) & 0xFF, g = (value >> 8) & 0xFF, b = value & 0xFF;
    return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

bool nsp_screensaver_parse(const std::string &payload, NspScreensaverConfig &out) {
    const std::string clock = json_object(payload, "clock");
    const std::string date = json_object(payload, "date");
    const std::string weather = json_object(payload, "weather");
    if (clock.empty() && date.empty() && weather.empty()) return false;

    NspScreensaverConfig r;
    parse_style(clock, false, r.clock);
    parse_style(date, true, r.date);
    json_bool(weather, "outside_temp", r.flags.outside_temp);
    json_bool(weather, "room_temp", r.flags.room_temp);
    json_bool(weather, "forecast", r.flags.forecast);
    json_bool(weather, "wind", r.flags.wind);
    json_bool(weather, "rain", r.flags.rain);
    json_bool(weather, "sunrise_sunset", r.flags.sunrise_sunset);
    std::string v;
    if (json_string(weather, "outside_temp_override", v))
        r.outside_override = nsp_display_clean(v, 24);
    if (json_string(weather, "room_temp_override", v))
        r.room_override = nsp_display_clean(v, 24);
    r.valid = true;
    out = r;
    return true;
}

bool nsp_weather_parse(const std::string &payload, NspWeatherData &out) {
    /* Top-level fields only: search before "forecast" so a row's "wind"
     * cannot be mistaken for the current wind. */
    size_t fk = payload.find("\"forecast\"");
    const std::string head = fk == std::string::npos ? payload
                                                     : payload.substr(0, fk);
    NspWeatherData r;
    std::string v;
    bool any = false;
    const char *fields[][2] = {
        {"temp", "temp"}, {"wind", "wind"}, {"prepro", "prepro"},
        {"sunrise", "sunrise"}, {"sunset", "sunset"}, {"maxmin", "maxmin"},
    };
    std::string *targets[] = {&r.temp, &r.wind, &r.prepro,
                              &r.sunrise, &r.sunset, &r.maxmin};
    for (int i = 0; i < 6; i++) {
        if (json_string(head, fields[i][0], v)) {
            *targets[i] = nsp_display_clean(v, 24);
            any = true;
        }
    }
    if (fk != std::string::npos) {
        size_t lb = payload.find('[', fk);
        if (lb != std::string::npos) {
            size_t i = lb + 1;
            while (i < payload.size() && r.day_count < 5) {
                size_t ob = payload.find('{', i);
                if (ob == std::string::npos) break;
                size_t cb = payload.find('}', ob);
                if (cb == std::string::npos) break;
                const std::string row = payload.substr(ob, cb - ob + 1);
                std::string day, maxmin;
                json_string(row, "day", day);
                json_string(row, "maxmin", maxmin);
                r.day[r.day_count] = nsp_display_clean(day, 5);
                r.day_maxmin[r.day_count] = nsp_display_clean(maxmin, 16);
                r.day_count++;
                any = true;
                i = cb + 1;
            }
        }
    }
    r.valid = any;
    out = r;
    return r.valid;
}

std::vector<std::string> nsp_screensaver_style_commands(const NspScreensaverConfig &cfg) {
    std::vector<std::string> cmds;
    const char *pages[] = {"screensaver", "mini"};
    const char *objects[] = {"curTime", "curDay", "curAMPM"};
    for (const char *page : pages) {
        for (const char *object : objects) {
            const NspTextStyle &s =
                (std::string(object) == "curDay") ? cfg.date : cfg.clock;
            const std::string base = std::string(page) + "." + object;
            cmds.push_back(base + ".font=" + std::to_string(s.font_id));
            cmds.push_back(base + ".pco=" + std::to_string(s.pco));
            cmds.push_back(base + ".xcen=" + std::to_string(s.align));
        }
    }
    return cmds;
}

std::vector<std::string> nsp_weather_commands(const NspWeatherData &data,
                                              const NspScreensaverConfig &cfg,
                                              const std::string &ntc_temp) {
    std::vector<std::string> cmds;
    auto add = [&cmds](const char *object, bool show, const std::string &value) {
        const std::string base = std::string("screensaver.") + object;
        cmds.push_back(base + ".vis=" + (show ? "1" : "0"));
        if (show)
            cmds.push_back(base + ".txt=\"" + nsp_display_clean(value, 24) + "\"");
    };
    add("wOutTemp", cfg.flags.outside_temp,
        cfg.outside_override.empty() ? data.temp : cfg.outside_override);
    add("wRoomTemp", cfg.flags.room_temp,
        cfg.room_override.empty() ? ntc_temp : cfg.room_override);
    add("wWind", cfg.flags.wind, "W " + data.wind);
    add("wRain", cfg.flags.rain, "R " + data.prepro);
    add("wSun", cfg.flags.sunrise_sunset, "U" + data.sunrise + " D" + data.sunset);
    add("wForecast", cfg.flags.forecast, forecast_summary(data));
    return cmds;
}
