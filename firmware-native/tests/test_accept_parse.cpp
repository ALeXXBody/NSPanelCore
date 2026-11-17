/* Host-side unit tests: register_accept parse (R1). */

#include "../src/accept_parse.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    std::string a; int p = 0;

    // The manager's REAL payload (with spaces after colons)
    CHECK(nsp_parse_register_accept(
        "{\"command\": \"register_accept\", \"address\": \"192.168.50.20\", \"port\": 8123, "
        "\"config_topic\": \"nspanel/e465b849a100/config\"}", a, p),
        "real payload parses");
    CHECK(a == "192.168.50.20", "address extracted");
    CHECK(p == 8123, "bare-int port extracted");

    // Compact form (no spaces)
    CHECK(nsp_parse_register_accept(
        "{\"command\":\"register_accept\",\"address\":\"10.0.0.2\",\"port\":1883}", a, p),
        "compact payload parses");
    CHECK(a == "10.0.0.2" && p == 1883, "compact values correct");

    // Missing address
    CHECK(!nsp_parse_register_accept("{\"command\":\"register_accept\"}", a, p),
        "accept without address rejected");

    // Empty address
    CHECK(!nsp_parse_register_accept(
        "{\"command\":\"register_accept\",\"address\":\"\",\"port\":8123}", a, p),
        "empty address rejected");

    // Not an accept at all
    CHECK(!nsp_parse_register_accept("{\"command\":\"firmware_update\"}", a, p),
        "non-accept payload rejected");

    // Port sanity clamping
    CHECK(nsp_parse_register_accept(
        "{\"command\":\"register_accept\",\"address\":\"192.168.50.20\",\"port\":99999}", a, p),
        "out-of-range port still parses (clamped later)");
    CHECK(p == 8123, "out-of-range port falls back to default 8123");

    // Port 0 rejected -> default
    CHECK(nsp_parse_register_accept(
        "{\"command\":\"register_accept\",\"address\":\"192.168.50.20\",\"port\":0}", a, p),
        "port 0 parses");
    CHECK(p == 8123, "port 0 falls back to default 8123");

    // Missing port -> default
    CHECK(nsp_parse_register_accept(
        "{\"command\":\"register_accept\",\"address\":\"192.168.50.20\"}", a, p),
        "missing port ok");
    CHECK(p == 8123, "missing port -> default 8123");

    // Key order variations
    CHECK(nsp_parse_register_accept(
        "{\"address\":\"192.168.50.20\",\"command\":\"register_accept\",\"port\":9000}", a, p),
        "reordered keys parse");
    CHECK(a == "192.168.50.20" && p == 9000, "reordered values correct");

    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
