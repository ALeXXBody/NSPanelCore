/* Host-side unit tests: log ring buffer (R1). */

#include "../src/logbuf.h"
#include <cassert>
#include <cstdio>
#include <string>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    NspLogBuf b(4);
    CHECK(b.dump() == "", "empty buffer dumps empty");
    b.add("one");
    b.add("two");
    CHECK(b.dump() == "one\ntwo", "in-order dump");
    CHECK(b.size() == 2, "size tracks");
    b.add("three");
    b.add("four");
    CHECK(b.dump() == "one\ntwo\nthree\nfour", "no wrap yet");
    b.add("five");  // wraps: oldest evicted
    CHECK(b.dump() == "two\nthree\nfour\nfive", "wrap evicts oldest");
    CHECK(b.size() == 4, "size capped at capacity");
    // Many wraps keep order
    NspLogBuf c(3);
    c.add("a"); c.add("b"); c.add("c"); c.add("d"); c.add("e");
    CHECK(c.dump() == "c\nd\ne", "multi-wrap order preserved");
    printf(g_fail ? "\n%d FAILURES\n" : "\nALL PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
