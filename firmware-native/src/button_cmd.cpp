/* NSPanel Core — physical button action decision (pure, host-testable). */

#include "button_cmd.h"

int nsp_button_action(int mode, NspButtonAction *out) {
    switch (mode) {
    case 0:  // DIRECT
        out->toggle_relay = true;
        out->report_manager = false;
        out->publish_custom = false;
        return 0;
    case 1:  // DETACHED — the manager routes the press to the HA entity
        out->toggle_relay = false;
        out->report_manager = true;
        out->publish_custom = false;
        return 0;
    case 2:  // CUSTOM_MQTT
        out->toggle_relay = false;
        out->report_manager = false;
        out->publish_custom = true;
        return 0;
    case 3:  // FOLLOW — local toggle + the manager stays informed
        out->toggle_relay = true;
        out->report_manager = true;
        out->publish_custom = false;
        return 0;
    default:
        return -1;  // unknown mode: NO-OP (never actuate hardware on a glitch)
    }
}
