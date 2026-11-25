/* Host-side unit tests: dash command parse (P234). */

#include "../src/dash_cmd.h"
#include <cstdio>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    std::string s;
    /* happy paths */
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"page dash_kitchen\"}", s) == 0
          && s == "page dash_kitchen", "page nav accepted");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"b0.val=1\"}", s) == 0
          && s == "b0.val=1", "val assignment accepted");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"t0.txt=\\\"21.5 C\\\"\"}", s) == 0
          && s == "t0.txt=\"21.5 C\"", "txt assignment accepted");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"bg.pic=7\"}", s) == 0
          && s == "bg.pic=7", "pic assignment accepted");

    /* txt sanitation */
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"t0.txt=\\\"a\\\"b\\\"\"}", s) == 0
          && s == "t0.txt=\"ab\"", "embedded quotes dropped (not passthrough)");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"t0.txt=\\\"a\\\\x01c\\\"\"}", s) == -1,
          "backslash escapes rejected outright");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"t0.txt=\\\"ok\\\";page 0\"}", s) == -1,
          "statement smuggling rejected");

    /* injection attempts */
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"page home;reboot\"}", s) == -1,
          "semicolon in page name rejected");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"page DASH_KITCHEN\"}", s) == -1,
          "uppercase page name rejected");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"x.rest=1\"}", s) == -1,
          "unknown attr rejected");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"rest.val=abc\"}", s) == -1,
          "non-numeric val rejected");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"B0.val=1\"}", s) == -1,
          "uppercase object rejected");
    CHECK(nsp_dash_parse("{\"command\":\"dash\",\"payload\":\"\"}", s) == -1,
          "empty payload rejected");
    CHECK(nsp_dash_parse("{\"command\":\"reboot\",\"payload\":\"x\"}", s) == -1,
          "wrong command rejected");

    /* dash_map */
    int pages[8] = {0};
    CHECK(nsp_dash_map_parse("{\"command\":\"dash_map\",\"pages\":[4,7,8]}", pages, 8) == 3
          && pages[0] == 4 && pages[1] == 7 && pages[2] == 8, "dash_map parsed");
    CHECK(nsp_dash_map_parse("{\"command\":\"dash_map\",\"pages\":[]}", pages, 8) == -1,
          "empty dash_map rejected");
    /* P361 (audit M8): the dp= contract accepts 0..255 — the old 15 ceiling
     * rejected bigger designs' whole map. 255 is valid; 999 is junk. */
    CHECK(nsp_dash_map_parse("{\"command\":\"dash_map\",\"pages\":[99]}", pages, 8) == 1
          && pages[0] == 99, "page id 255-range accepted");
    CHECK(nsp_dash_map_parse("{\"command\":\"dash_map\",\"pages\":[999]}", pages, 8) == -1,
          "out-of-range page id rejected");
    CHECK(nsp_dash_map_parse("{\"command\":\"dash_map\",\"pages\":[4,abc]}", pages, 8) == -1,
          "garbage in pages rejected");

    /* membership */
    int ids[3] = {4, 7, 8};
    CHECK(nsp_dash_page(ids, 3, 7), "dash page recognized");
    CHECK(!nsp_dash_page(ids, 3, 2), "base page not a dash page");
    CHECK(!nsp_dash_page(nullptr, 3, 4), "no map -> nothing is a dash page");

    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
