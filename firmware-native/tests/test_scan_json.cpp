/* Host-side unit tests for scan-result formatting (R1). */

#include "../src/scan_json.h"
#include <cassert>
#include <cstdio>
#include <vector>
#include <utility>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

static void test_basic_and_sort() {
    std::vector<std::pair<std::string, int>> recs = {{"Home", -50}, {"Cafe", -70}, {"Home2", -60}};
    std::string j = nsp_scan_json(recs);
    CHECK(j.find("\"Home\"") < j.find("\"Home2\""), "sorted by rssi desc (Home first)");
    CHECK(j.find("\"Home2\"") < j.find("\"Cafe\""), "Cafe (weakest) last");
    CHECK(j.find("-70") != std::string::npos, "rssi values present");
}

static void test_dedup_keeps_strongest() {
    std::vector<std::pair<std::string, int>> recs = {{"Home", -80}, {"Home", -42}, {"Home", -65}};
    std::string j = nsp_scan_json(recs);
    CHECK(j == "[{\"ssid\":\"Home\",\"rssi\":-42}]", "dedup keeps strongest rssi");
}

static void test_skips_empty_ssid() {
    std::vector<std::pair<std::string, int>> recs = {{"", -30}, {"Net", -55}, {"", -40}};
    std::string j = nsp_scan_json(recs);
    CHECK(j.find("\"\"") == std::string::npos, "empty SSIDs skipped");
    CHECK(j.find("Net") != std::string::npos, "named SSID kept");
}

static void test_escapes_specials() {
    std::vector<std::pair<std::string, int>> recs = {{"My \"Net\"\\work", -50}, {"Tab\tNet", -60}};
    std::string j = nsp_scan_json(recs);
    CHECK(j.find("\\\\") != std::string::npos, "backslash escaped");
    CHECK(j.find("\\t") != std::string::npos, "tab escaped");
    CHECK(j.find("\\\"Net") != std::string::npos, "quote escaped");
}

static void test_empty_input() {
    CHECK(nsp_scan_json({}) == "[]", "empty scan -> empty JSON array");
}

int main() {
    test_basic_and_sort();
    test_dedup_keeps_strongest();
    test_skips_empty_ssid();
    test_escapes_specials();
    test_empty_input();
    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
