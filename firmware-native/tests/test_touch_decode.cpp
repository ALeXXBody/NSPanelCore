/* Host-side unit tests: touch frame decode (R1). */

#include "../src/touch_decode.h"
#include <cassert>
#include <cstdio>
#include <vector>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    // Single clean frame: page 2, component 5, pressed
    {
        unsigned char f[] = {0x65, 2, 5, 1, 0xFF, 0xFF, 0xFF};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.size() == 1, "single frame decoded");
        CHECK(v[0].page == 2 && v[0].component == 5 && v[0].event == 1, "fields correct");
        CHECK(v[0].consumed == 7, "consumed = 7");
    }
    // Released event
    {
        unsigned char f[] = {0x65, 2, 10, 0, 0xFF, 0xFF, 0xFF};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.size() == 1 && v[0].event == 0, "released event decoded");
    }
    // Two frames back-to-back
    {
        unsigned char f[] = {0x65, 2, 5, 1, 0xFF, 0xFF, 0xFF, 0x65, 6, 17, 0, 0xFF, 0xFF, 0xFF};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.size() == 2, "two frames decoded");
        CHECK(v[0].component == 5 && v[1].component == 17, "second frame fields correct");
    }
    // Garbage prefix then frame (display noise)
    {
        unsigned char f[] = {0x00, 0x1A, 0x66, 0x65, 2, 5, 1, 0xFF, 0xFF, 0xFF};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.size() == 1 && v[0].component == 5, "garbage prefix skipped");
    }
    // Truncated frame at buffer end -> ignored
    {
        unsigned char f[] = {0x65, 2, 5, 1, 0xFF, 0xFF};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.empty(), "truncated frame ignored");
    }
    // 0x65 with wrong terminator -> ignored
    {
        unsigned char f[] = {0x65, 2, 5, 1, 0xFF, 0xFF, 0x00};
        auto v = nsp_touch_decode(f, sizeof(f));
        CHECK(v.empty(), "bad terminator ignored");
    }
    // Empty / null
    {
        CHECK(nsp_touch_decode(nullptr, 10).empty(), "null buffer -> empty");
        unsigned char f[1] = {0x65};
        CHECK(nsp_touch_decode(f, 0).empty(), "zero length -> empty");
    }
    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
