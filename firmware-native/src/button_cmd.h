/* NSPanel Core — physical button action decision (pure, host-testable).
 *
 * The canonical button-mode enum (single source of truth, matches the UI):
 *   0 = DIRECT       — press toggles the mapped relay on-panel
 *   1 = DETACHED     — press is REPORTED to the manager; the manager routes
 *                      it to the bound Home Assistant entity
 *   2 = CUSTOM_MQTT  — press publishes the button's custom topic/payload
 *   3 = FOLLOW       — press toggles the mapped relay AND is reported
 *                      (the manager stays in the loop for automations)
 */

#pragma once

struct NspButtonAction {
    bool toggle_relay;   // drive the mapped relay GPIO
    bool report_manager; // publish the press on nspanel/<hostname>/button
    bool publish_custom; // publish the button's custom topic/payload
};

/* Decide what a press does for the given mode.
 * Returns 0 and fills `out` on success; -1 for an unknown mode (out
 * untouched — the caller must treat unknown modes as no-op, never as
 * toggle: a config glitch must not actuate hardware). */
int nsp_button_action(int mode, NspButtonAction *out);
