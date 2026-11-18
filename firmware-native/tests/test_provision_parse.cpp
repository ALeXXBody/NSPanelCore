/* P222c: host tests for the provisioning payload parser (R1 — the
 * /provision endpoint shipped without tests once; this closes that gap). */

#include "../src/provision_parse.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    std::string v;

    /* the manager's real payload (compact JSON) */
    CHECK(nsp_provision_field(
        "{\"mqtt_server\":\"192.168.50.20\",\"mqtt_port\":1883,"
        "\"mqtt_user\":\"panels\",\"mqtt_pass\":\"s3cret\"}", "mqtt_server", v)
        && v == "192.168.50.20", "compact: mqtt_server");
    CHECK(nsp_provision_field(
        "{\"mqtt_server\":\"192.168.50.20\",\"mqtt_port\":1883,"
        "\"mqtt_user\":\"panels\",\"mqtt_pass\":\"s3cret\"}", "mqtt_port", v)
        && v == "1883", "compact: numeric port");

    /* spaced JSON (the app sends json.dumps — may have spaces) */
    CHECK(nsp_provision_field(
        "{\"mqtt_server\": \"broker.local\", \"mqtt_user\": \"u1\"}", "mqtt_server", v)
        && v == "broker.local", "spaced: mqtt_server");

    /* quoted port (treated as string, still captured) */
    CHECK(nsp_provision_field(
        "{\"mqtt_port\":\"8883\"}", "mqtt_port", v) && v == "8883", "quoted port");

    /* missing key */
    CHECK(!nsp_provision_field("{\"mqtt_user\":\"u\"}", "mqtt_server", v),
          "missing key rejected");

    /* empty string value */
    CHECK(nsp_provision_field("{\"mqtt_server\":\"\"}", "mqtt_server", v) && v.empty(),
          "empty string value captured (caller validates)");

    /* special chars in password: json.dumps escapes inner quotes and the
     * parser unescapes them (P235: provisioning broke on quote passwords). */
    CHECK(nsp_provision_field(
        "{\"mqtt_pass\":\"p@\\\"ss!\"}", "mqtt_pass", v) && v == "p@\"ss!",
        "password with escaped quote");

    /* key substring must not match (mqtt_server2 must not return mqtt_server's value) */
    CHECK(!nsp_provision_field("{\"mqtt_server2\":\"x\"}", "mqtt_server", v),
          "key prefix not falsely matched");

    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
