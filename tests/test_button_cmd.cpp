/* P312: physical button action decision — the canonical mode enum
 * (0=DIRECT 1=DETACHED 2=CUSTOM_MQTT 3=FOLLOW) drives hardware behavior.
 * A unknown/glitched mode must NEVER actuate hardware. */

#include "../firmware-native/src/button_cmd.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>

static int g_fail = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); g_fail++; } \
                              else { printf("ok: %s\n", msg); } } while (0)

int main() {
    NspButtonAction a;

    CHECK(nsp_button_action(0, &a) == 0, "DIRECT parses");
    CHECK(a.toggle_relay && !a.report_manager && !a.publish_custom,
          "DIRECT toggles the relay only");

    CHECK(nsp_button_action(1, &a) == 0, "DETACHED parses");
    CHECK(!a.toggle_relay && a.report_manager && !a.publish_custom,
          "DETACHED reports to the manager, never touches the relay");

    CHECK(nsp_button_action(2, &a) == 0, "CUSTOM_MQTT parses");
    CHECK(!a.toggle_relay && !a.report_manager && a.publish_custom,
          "CUSTOM_MQTT publishes the custom topic only");

    CHECK(nsp_button_action(3, &a) == 0, "FOLLOW parses");
    CHECK(a.toggle_relay && a.report_manager && !a.publish_custom,
          "FOLLOW toggles AND reports");

    // unknown/glitched modes: no-op, never hardware
    for (int mode : {-1, 4, 5, 99, 12345}) {
        CHECK(nsp_button_action(mode, &a) == -1,
              "unknown mode rejected (no action)");
    }

    if (g_fail == 0) printf("ALL PASS\n");
    return g_fail == 0 ? 0 : 1;
}
