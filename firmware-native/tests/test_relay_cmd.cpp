/* Host-side unit tests: relay command parse (R1). */

#include "../src/relay_cmd.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    CHECK(nsp_relay_parse("1") == 1, "exact '1' -> 1");
    CHECK(nsp_relay_parse("0") == 0, "exact '0' -> 0");
    CHECK(nsp_relay_parse(" 1 ") == 1, "whitespace tolerated");
    CHECK(nsp_relay_parse("1\n") == 1, "trailing newline tolerated");
    CHECK(nsp_relay_parse("") == -1, "empty -> invalid");
    CHECK(nsp_relay_parse("true") == -1, "'true' -> invalid (fail-safe)");
    CHECK(nsp_relay_parse("on") == -1, "'on' -> invalid");
    CHECK(nsp_relay_parse("11") == -1, "'11' -> invalid (not a bool)");
    CHECK(nsp_relay_parse("x") == -1, "garbage -> invalid");
    CHECK(nsp_relay_parse("  ") == -1, "whitespace only -> invalid");
    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
