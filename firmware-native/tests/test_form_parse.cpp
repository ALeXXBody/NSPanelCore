/* Host-side unit tests for the native firmware's pure logic (R1).
 * Compiled and run with plain g++ — no framework, no ESP-IDF needed.
 * Run: tests/run_host_tests.sh
 */

#include "../src/form_parse.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

static void test_basic_pair() {
    std::map<std::string, std::string> f;
    nsp_parse_form("ssid=MyNet&psk=secret", f);
    CHECK(f["ssid"] == "MyNet", "basic key=value");
    CHECK(f["psk"] == "secret", "second pair");
}

static void test_plus_and_percent() {
    std::map<std::string, std::string> f;
    nsp_parse_form("ssid=My+Network&psk=pa%23ss%20word", f);
    CHECK(f["ssid"] == "My Network", "'+' decodes to space");
    CHECK(f["psk"] == "pa#ss word", "%XX decoding incl # and space");
}

static void test_missing_and_empty() {
    std::map<std::string, std::string> f;
    nsp_parse_form("ssid=Net&psk=&hostname=", f);
    CHECK(f["ssid"] == "Net", "first key present");
    CHECK(f["psk"] == "", "empty value parses as empty string");
    CHECK(f["hostname"] == "", "trailing empty value");
    CHECK(f.find("mqtt_server") == f.end(), "absent key stays absent");
}

static void test_special_chars() {
    std::map<std::string, std::string> f;
    nsp_parse_form("mqtt_pass=p%40ss%26word%3D1&mqtt_user=admin%40mail.com", f);
    CHECK(f["mqtt_pass"] == "p@ss&word=1", "encoded @, &, = in value");
    CHECK(f["mqtt_user"] == "admin@mail.com", "encoded @ in user");
}

static void test_repeated_key_last_wins() {
    std::map<std::string, std::string> f;
    nsp_parse_form("ssid=A&ssid=B", f);
    CHECK(f["ssid"] == "B", "repeated key: last wins");
}

static void test_value_with_equals() {
    std::map<std::string, std::string> f;
    nsp_parse_form("psk=abc=def&ssid=x", f);
    CHECK(f["psk"] == "abc=def", "unencoded '=' inside value preserved");
}

int main() {
    test_basic_pair();
    test_plus_and_percent();
    test_missing_and_empty();
    test_special_chars();
    test_repeated_key_last_wins();
    test_value_with_equals();
    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
