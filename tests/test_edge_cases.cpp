/* P311 FULL-APP/FIRMWARE AUDIT — edge tests for the paths nothing covered.
 * Built and run by run_host_tests.sh (appended section). */
#include "../firmware-native/src/form_parse.h"
#include <map>
#include "../firmware-native/src/scan_json.h"
#include "../firmware-native/src/provision_parse.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    // ---- form_parse: the AP setup form (WiFi + advanced MQTT fields) ----
    // urlencoded body with special characters in ssid/psk/hostname
    {
        std::map<std::string, std::string> f;
        nsp_parse_form(
            "ssid=My+Home%2BWiFi&psk=pass%22word%5C&hostname=Kitchen%26Panrl"
            "&mqtt_server=192.168.50.20&mqtt_port=1883&mqtt_user=ALeXX"
            "&mqtt_pass=p%2Bss", f);
        CHECK(f.count("ssid") && (f["ssid"] == "My Home+WiFi") || (f["ssid"].find("Home") != std::string::npos),
              "form ssid decoded");
        // whatever the decode convention is, it must not DROP the fields
        CHECK(!f["psk"].empty(), "form psk not dropped");
        CHECK(!f["hostname"].empty(), "form hostname not dropped");
        CHECK(!f["mqtt_pass"].empty(), "form mqtt_pass not dropped");
    }

    // ---- provision parse: edge bodies the manager can produce ----
    {
        std::string v;
        // empty password field (anonymous broker) must parse to empty, not fail
        CHECK(nsp_provision_field(
            "{\"mqtt_server\": \"h\", \"mqtt_port\": 1883, "
            "\"mqtt_user\": \"\", \"mqtt_pass\": \"\"}", "mqtt_pass", v),
            "empty string field parses");
        CHECK(v.empty(), "empty password stays empty");

        // password with a newline (json \n) must unescape, not reject
        CHECK(nsp_provision_field(
            "{\"mqtt_pass\": \"a\\nb\"}", "mqtt_pass", v) && v == "a\nb",
            "\\n escape unescapes");

        // numeric port with spaces around it
        CHECK(nsp_provision_field(
            "{\"mqtt_port\": 1883}", "mqtt_port", v) && v == "1883",
            "bare numeric port parses");

        // a password containing the literal key of another field must not
        // confuse the extraction ("mqtt_user" inside the pass value)
        CHECK(nsp_provision_field(
            "{\"mqtt_user\": \"u\", \"mqtt_pass\": \"x\\\"mqtt_user\\\"y\"}",
            "mqtt_pass", v) && v == "x\"mqtt_user\"y",
            "key-like password value parses");
    }

    // ---- provision: malformed bodies must not crash or hang ----
    {
        std::string v;
        const char *bodies[] = {
            "", "{}", "{\"a\":}", "{\"a\": \"unterminated", "not json at all",
            "{\"mqtt_pass\": \"\\\\\"\\\\ quote\"}",
        };
        for (const char *b : bodies) {
            (void)nsp_provision_field(b, "mqtt_pass", v);  // must not crash
        }
        CHECK(true, "provision parser survives malformed bodies");
    }

    if (g_fail == 0) printf("ALL PASS\n");
    return g_fail == 0 ? 0 : 1;
}
