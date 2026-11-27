/* NSPanel Core — screensaver style + weather parse (pure, host-testable).
 *
 * P306 / fw 0.1.14. Two MQTT feeds drive the panel's screensaver:
 *   nspanel/<hostname>/screensaver  (retained, per-panel style + flags)
 *   nspanel/status/weather          (retained, global weather JSON)
 *
 * This module owns ALL parsing and command construction. It has no ESP-IDF
 * dependency, so the exact bytes that reach the UART are tested on the host.
 * The caller only sends the returned commands via nsp_display_send_command().
 *
 * Font IDs are the wire contract established by scripts/make_screensaver_fonts.py:
 *   small=0/1  medium=2/3  large=4/5  xlarge=6/7   (regular/bold)
 *   align left=0 center=1 right=2
 */

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

struct NspTextStyle {
    int font_id = 4;        // 0..7; 4 = large regular (the model's default)
    uint16_t pco = 0xCE59;  // RGB565 of #c8cbce (the clock's default)
    int align = 1;          // 0 left, 1 center, 2 right
};

struct NspWeatherFlags {
    bool outside_temp = false;
    bool room_temp = false;
    bool forecast = false;
    bool wind = false;
    bool rain = false;
    bool sunrise_sunset = false;
};

/* P364: the weather icon groups — the payload's icon string maps to one
 * of four glyph comps on the screensaver page (wx_sun/wx_cloud/wx_rain/
 * wx_snow). 0=sun 1=cloud 2=rain 3=snow. */
enum NspWeatherIcon { WX_SUN = 0, WX_CLOUD = 1, WX_RAIN = 2, WX_SNOW = 3 };

struct NspScreensaverConfig {
    NspTextStyle clock;
    NspTextStyle date;
    NspWeatherFlags flags;
    std::string outside_override;  // sanitized; empty => use global weather
    std::string room_override;     // sanitized; empty => use the panel's NTC
    int activation_timeout = 15;   // P356: seconds of no touch -> the screensaver
    bool valid = false;
};

struct NspWeatherData {
    int icon_group = WX_CLOUD;  // P364: the glyph group
    int row_icon[5] = {WX_CLOUD, WX_CLOUD, WX_CLOUD, WX_CLOUD, WX_CLOUD};
    std::string temp;
    std::string wind;
    std::string prepro;
    std::string sunrise;
    std::string sunset;
    std::string maxmin;
    std::string day[5];
    std::string day_maxmin[5];
    int day_count = 0;
    bool valid = false;
};

/* Whitelist sanitiser for every string that becomes a Nextion .txt command.
 * Drops command terminators (0xFF), quotes, backslashes, semicolons, angle
 * brackets, controls and unknown high bytes; transcodes a UTF-8 degree sign
 * (C2 B0) and a JSON \u00b0 escape to the font's Latin-1 byte 0xB0. */
std::string nsp_display_clean(const std::string &value, std::size_t max = 24);

/* Strict #RRGGBB -> RGB565. Any malformed input returns |fallback|. */
uint16_t nsp_rgb565(const std::string &hex, uint16_t fallback);

/* Parse the retained per-panel screensaver payload. Bad individual fields
 * fall back to safe defaults (never pass through); a payload with no usable
 * clock/date/weather object is rejected (false). */
bool nsp_screensaver_parse(const std::string &payload, NspScreensaverConfig &out);

/* Parse the retained global weather payload into sanitised, capped strings. */
bool nsp_weather_parse(const std::string &payload, NspWeatherData &out);

/* Display commands that apply the style to both HMI pages. */
std::vector<std::string> nsp_screensaver_style_commands(const NspScreensaverConfig &cfg);

/* Display commands that render weather on the screensaver page. |ntc_temp|
 * is the panel's own sensor reading (already formatted) for the room slot. */
std::vector<std::string> nsp_weather_commands(const NspWeatherData &data,
                                              const NspScreensaverConfig &cfg,
                                              const std::string &ntc_temp);
