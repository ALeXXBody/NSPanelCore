/* Host-side unit tests: screensaver style + weather parse (P306 / fw 0.1.14).
 * These check the exact bytes the firmware would send down the UART. */

#include "../src/screensaver_parse.h"
#include <cstdio>
#include <cstdint>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

static const std::string DEG(1, (char)0xB0);  // Latin-1 degree in the .zi font

static bool has(const std::vector<std::string> &v, const std::string &s) {
    for (const auto &x : v) if (x == s) return true;
    return false;
}

/* No command may carry an injected statement or a raw control byte. */
static bool safe(const std::vector<std::string> &v) {
    for (const auto &cmd : v) {
        if (cmd.find(';') != std::string::npos) return false;
        if (cmd.find('\\') != std::string::npos) return false;
        for (unsigned char c : cmd)
            if (c == 0xFF || (c < 32 && c != 0)) return false;
    }
    return true;
}

int main() {
    /* ---- sanitizer ---- */
    CHECK(nsp_display_clean("21" "\xC2\xB0" "C") == "21" + DEG + "C",
          "UTF-8 degree becomes the font's Latin-1 glyph");
    CHECK(nsp_display_clean("21" + DEG + "C") == "21" + DEG + "C",
          "already-Latin-1 degree preserved");
    CHECK(nsp_display_clean("a\";page 0;b") == "apage 0b",
          "quote/semicolon stripped, no statement smuggling");
    CHECK(nsp_display_clean(std::string("a\0b", 3)) == "ab", "NUL stripped");
    CHECK(nsp_display_clean(std::string("a\xFF" "b", 3)) == "ab",
          "0xFF terminator stripped");
    CHECK(nsp_display_clean("abcdef", 3) == "abc", "length capped");
    CHECK(nsp_display_clean("a<b>=\\c") == "abc", "angle/backslash/equals stripped");

    /* ---- RGB565 ---- */
    CHECK(nsp_rgb565("#c8cbce", 0) == 0xCE59, "clock colour -> RGB565");
    CHECK(nsp_rgb565("#8b93a1", 0) == 0x8C94, "date colour -> RGB565");
    CHECK(nsp_rgb565("#ff0000", 0) == 0xF800, "pure red -> RGB565");
    CHECK(nsp_rgb565("#GGGGGG", 0x1234) == 0x1234, "malformed colour -> fallback");
    CHECK(nsp_rgb565("#c8cbce\",page 0", 0x1234) == 0x1234,
          "injected colour string -> fallback");

    /* ---- screensaver config: the manager's compact JSON shape ---- */
    NspScreensaverConfig cfg;
    const std::string style =
        "{\"clock\":{\"font\":\"xlarge\",\"weight\":\"bold\","
        "\"color\":\"#ff0000\",\"align\":\"right\"},"
        "\"date\":{\"font\":\"medium\",\"weight\":\"regular\","
        "\"color\":\"#8b93a1\",\"align\":\"left\"},"
        "\"weather\":{\"outside_temp\":true,\"room_temp\":true,"
        "\"forecast\":true,\"wind\":true,\"rain\":true,"
        "\"sunrise_sunset\":true,\"outside_temp_override\":\"\","
        "\"room_temp_override\":\"22.5\\u00b0C\"}}";
    CHECK(nsp_screensaver_parse(style, cfg) && cfg.valid, "style payload accepted");
    CHECK(cfg.clock.font_id == 7, "xlarge bold -> font id 7");
    CHECK(cfg.clock.pco == 0xF800 && cfg.clock.align == 2, "clock colour/align parsed");
    CHECK(cfg.date.font_id == 2, "medium regular -> font id 2");
    CHECK(cfg.date.pco == 0x8C94 && cfg.date.align == 0, "date colour/align parsed");
    CHECK(cfg.flags.outside_temp && cfg.flags.sunrise_sunset && !cfg.flags.rain == false,
          "weather flags parsed");
    CHECK(cfg.outside_override.empty(), "empty outside override stays empty");
    CHECK(cfg.room_override == "22.5" + DEG + "C", "override degree decoded");

    auto cmds = nsp_screensaver_style_commands(cfg);
    CHECK(cmds.size() == 18, "style writes 3 attrs x 3 objects x 2 pages");
    CHECK(safe(cmds), "style commands carry no injected bytes");
    CHECK(has(cmds, "screensaver.curTime.font=7"), "screensaver clock font written");
    CHECK(has(cmds, "screensaver.curTime.pco=63488"), "screensaver clock colour written");
    CHECK(has(cmds, "screensaver.curTime.xcen=2"), "screensaver clock alignment written");
    CHECK(has(cmds, "mini.curDay.font=2"), "mini date font written");
    CHECK(has(cmds, "mini.curDay.pco=35988"), "mini date colour written");
    CHECK(has(cmds, "mini.curAMPM.xcen=2"), "mini AMPM follows the clock style");

    /* hostile / partial style never passes a raw value to the display */
    NspScreensaverConfig bad;
    CHECK(!nsp_screensaver_parse("not json", bad), "garbage payload rejected");
    CHECK(nsp_screensaver_parse("{\"clock\":{\"font\":\"huge\",\"color\":\"#zzzzzz\","
          "\"align\":\"sideways\",\"weight\":\"chunky\"}}", bad),
          "bad field values fall back, payload still usable");
    CHECK(bad.clock.font_id == 4, "bad font -> large regular default");
    CHECK(bad.clock.pco == 0xCE59, "bad colour -> clock default");
    CHECK(bad.clock.align == 1, "bad align -> center default");
    CHECK(nsp_screensaver_parse("{\"date\":{\"font\":\"xlarge\"}}", bad),
          "date xlarge payload accepted");
    CHECK(bad.date.font_id == 0, "date xlarge clamped to small (date has no xlarge font)");
    CHECK(nsp_screensaver_parse("{\"clock\":{\"color\":\"#fff\\u0022;page 0\"}}", bad),
          "JSON escape attack payload accepted for fallback");
    CHECK(bad.clock.pco == 0xCE59, "escape attack in colour cannot reach the command");

    /* ---- weather payload (json.dumps escaping included) ---- */
    NspWeatherData data;
    const std::string weather =
        "{\"icon\":\"sunny\",\"temp\":\"21\\u00b0C\",\"wind\":\"12 km/h\","
        "\"sunrise\":\"06:12\",\"sunset\":\"19:45\","
        "\"maxmin\":\"23\\u00b0C/9\\u00b0C\",\"prepro\":\"0.2 mm\","
        "\"forecast\":[{\"day\":\"Mon\",\"icon\":\"sunny\","
        "\"maxmin\":\"23\\u00b0C/9\\u00b0C\",\"prepro\":\"mm 20%\","
        "\"wind\":\"12 km/h\"},{\"day\":\"Tue\",\"icon\":\"rainy\","
        "\"maxmin\":\"21\\u00b0C/8\\u00b0C\",\"prepro\":\"mm 60%\","
        "\"wind\":\"9 km/h\"}]}";
    CHECK(nsp_weather_parse(weather, data) && data.valid, "weather payload accepted");
    CHECK(data.temp == "21" + DEG + "C", "weather temp degree decoded");
    CHECK(data.day_count == 2, "two forecast rows parsed");
    CHECK(data.day[0] == "Mon" && data.day[1] == "Tue", "forecast days parsed");

    auto wcmds = nsp_weather_commands(data, cfg, "19.5" + DEG + "C");
    CHECK(safe(wcmds), "weather commands carry no injected bytes");
    CHECK(has(wcmds, "screensaver.wOutTemp.txt=\"21" + DEG + "C\""),
          "outside temp falls back to the global weather topic");
    CHECK(has(wcmds, "screensaver.wRoomTemp.txt=\"22.5" + DEG + "C\""),
          "per-panel room override beats the panel NTC");
    /* P364: the weather redesign — the icons + the forecast rows replaced
     * the wind/rain/sun-times/summary text objects. */
    CHECK(has(wcmds, "screensaver.wx_sun.vis=1"), "the sun glyph visible");
    CHECK(has(wcmds, "screensaver.wx_cloud.vis=0"), "the cloud glyph hidden");
    CHECK(has(wcmds, "screensaver.wx_rain.vis=0"), "the rain glyph hidden");
    CHECK(has(wcmds, "screensaver.wx_snow.vis=0"), "the snow glyph hidden");
    CHECK(has(wcmds, "screensaver.fDay0.txt=\"Mon\""), "the forecast day rendered");
    CHECK(has(wcmds, "screensaver.fMM0.txt=\"23" + DEG + "C/9" + DEG + "C\""),
          "the forecast temps rendered");
    /* the test payload has 2 forecast days — fDay2 gets nothing */
    CHECK(!has(wcmds, "screensaver.fDay2.txt="), "no third-row write without a third day");
    for (const auto &cmd : wcmds) {
        size_t q = cmd.find("txt=\"");
        if (q == std::string::npos) continue;
        std::string text = cmd.substr(q + 5, cmd.size() - q - 6);
        CHECK(text.size() <= 24, "every weather text fits txt_maxl");
    }

    /* hides: flags off => the temps hidden, the glyphs hidden */
    NspScreensaverConfig hidden;
    CHECK(nsp_screensaver_parse("{\"weather\":{}}", hidden), "empty weather config accepted");
    auto hcmds = nsp_weather_commands(data, hidden, "19.5" + DEG + "C");
    CHECK(has(hcmds, "screensaver.wOutTemp.vis=0"), "hidden outside temp gets vis=0");
    CHECK(has(hcmds, "screensaver.wx_cloud.vis=0"), "the glyphs hidden (the default group is cloud)");
    CHECK(!has(hcmds, "screensaver.wOutTemp.txt=\""), "the hidden temp is not written");

    /* NTC fallback when there is no per-panel override */
    NspScreensaverConfig ntc_cfg;
    CHECK(nsp_screensaver_parse("{\"weather\":{\"room_temp\":true}}", ntc_cfg),
          "room-only config accepted");
    auto ncmds = nsp_weather_commands(data, ntc_cfg, "19.5" + DEG + "C");
    CHECK(has(ncmds, "screensaver.wRoomTemp.txt=\"19.5" + DEG + "C\""),
          "panel NTC used when the override is empty");

    /* adversarial weather: injection and oversized values cannot escape */
    NspWeatherData evil;
    CHECK(nsp_weather_parse("{\"temp\":\"21\\\";page 0\",\"wind\":\"\\u00ff\\xFFbad\","
          "\"forecast\":[{\"day\":\"0123456789ABCDEF\",\"maxmin\":\"huge\"}]}", evil),
          "adversarial weather payload parsed with sanitation");
    auto ecmds = nsp_weather_commands(evil, cfg, "");
    CHECK(safe(ecmds), "adversarial weather cannot smuggle a display statement");
    CHECK(!has(ecmds, "screensaver.wWind.txt=\"\\u00ff\\xFFbad\""),
          "raw escape bytes never reach the display");

    /* ---- P306 Step 5: the exact payload build_panel_screensaver_config() publishes ----
     * This is the same JSON the studio save path emits (json.dumps -> \\u00b0C),
     * so a firmware panel parses the manager's real contract, not a hand-made twin. */
    NspScreensaverConfig pub_cfg;
    const std::string published =
        "{\"clock\":{\"font\":\"xlarge\",\"weight\":\"bold\",\"color\":\"#39c8e8\",\"align\":\"right\"},"
        "\"date\":{\"font\":\"medium\",\"weight\":\"bold\",\"color\":\"#8b93a1\",\"align\":\"left\"},"
        "\"weather\":{\"outside_temp\":true,\"room_temp\":true,\"forecast\":true,\"wind\":true,"
        "\"rain\":true,\"sunrise_sunset\":true,"
        "\"outside_temp_override\":\"21.0\\u00b0C\",\"room_temp_override\":\"19.5\\u00b0C\"}}";
    CHECK(nsp_screensaver_parse(published, pub_cfg) && pub_cfg.valid,
          "published manager payload accepted");
    CHECK(pub_cfg.clock.font_id == 7 && pub_cfg.clock.align == 2 && pub_cfg.clock.pco == 0x3E5D,
          "published clock maps to xlarge bold, right, #39c8e8");
    CHECK(pub_cfg.date.font_id == 3 && pub_cfg.date.align == 0 && pub_cfg.date.pco == 0x8C94,
          "published date maps to medium bold, left, #8b93a1");
    CHECK(pub_cfg.flags.outside_temp && pub_cfg.flags.room_temp && pub_cfg.flags.forecast &&
          pub_cfg.flags.wind && pub_cfg.flags.rain && pub_cfg.flags.sunrise_sunset,
          "published weather flags all on");
    CHECK(pub_cfg.outside_override == "21.0" + DEG + "C", "published outside override decoded");
    CHECK(pub_cfg.room_override == "19.5" + DEG + "C", "published room override decoded");

    auto pub_style = nsp_screensaver_style_commands(pub_cfg);
    CHECK(has(pub_style, "screensaver.curTime.font=7"), "published style drives the panel clock font");
    CHECK(has(pub_style, "screensaver.curTime.xcen=2"), "published style drives the panel clock align");
    CHECK(has(pub_style, "mini.curDay.font=3"), "published style drives the panel date font");

    const std::string published_weather =
        "{\"icon\":\"sunny\",\"temp\":\"21.0\\u00b0C\",\"wind\":\"12 km/h\","
        "\"sunrise\":\"06:12\",\"sunset\":\"19:45\",\"maxmin\":\"23\\u00b0C/9\\u00b0C\","
        "\"prepro\":\"0.2 mm\",\"forecast\":[{\"day\":\"Mon\",\"icon\":\"sunny\","
        "\"maxmin\":\"23\\u00b0C/9\\u00b0C\",\"prepro\":\"mm 20%\",\"wind\":\"12 km/h\"}]}";
    NspWeatherData pub_w;
    CHECK(nsp_weather_parse(published_weather, pub_w) && pub_w.valid, "published weather payload accepted");
    auto pub_wcmds = nsp_weather_commands(pub_w, pub_cfg, "18.0" + DEG + "C");
    CHECK(safe(pub_wcmds), "published weather commands safe");
    CHECK(has(pub_wcmds, "screensaver.wOutTemp.txt=\"21.0" + DEG + "C\""),
          "published outside override wins over weather topic value");
    CHECK(has(pub_wcmds, "screensaver.wRoomTemp.txt=\"19.5" + DEG + "C\""),
          "published room override wins over the panel sensor");

    /* P356: the screensaver activation timeout rides the payload. */
    {
        NspScreensaverConfig to;
        const std::string with_to =
            "{\"activation_timeout\":\"45\",\"clock\":{\"font\":\"large\"}}";
        CHECK(nsp_screensaver_parse(with_to, to) && to.valid,
              "payload with activation_timeout accepted");
        CHECK(to.activation_timeout == 45, "activation_timeout parsed (45 s)");
        NspScreensaverConfig def;
        const std::string without_to = "{\"clock\":{\"font\":\"large\"}}";
        CHECK(nsp_screensaver_parse(without_to, def) && def.valid,
              "payload without activation_timeout accepted");
        CHECK(def.activation_timeout == 15, "default stays 15 s");
        NspScreensaverConfig junk;
        const std::string bad_to =
            "{\"activation_timeout\":\"banana\",\"clock\":{\"font\":\"large\"}}";
        CHECK(nsp_screensaver_parse(bad_to, junk) && junk.valid,
              "junk timeout tolerated");
        CHECK(junk.activation_timeout == 15, "junk timeout keeps the default");
        NspScreensaverConfig clamped;
        const std::string big_to =
            "{\"activation_timeout\":\"99999\",\"clock\":{\"font\":\"large\"}}";
        CHECK(nsp_screensaver_parse(big_to, clamped) && clamped.valid,
              "out-of-range timeout accepted");
        CHECK(clamped.activation_timeout == 15,
              "out-of-range timeout (beyond 3600) keeps the default");
    }

    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
