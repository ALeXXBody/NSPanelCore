# 8. Troubleshooting

## The display is not responding

The panel's status shows "No response from the display" when the display
module's serial doesn't answer. Steps:

1. **Display restart** (the panel's web UI → Actions) — power-cycles the
   display module and re-handshakes
2. **Full power cycle** — cut the mains power for 60 seconds
3. **Reseat the ribbon cable** — open the front face, pull the ribbon,
   reseat it firmly

## The screen shows "System-Data-ERROR"

The display's stored image failed its own validation (a partially written
flash). The panel's firmware **detects and repairs this automatically**:
the delivery is retried and the image is re-sent. If it persists, a full
mains power cycle + the display restart clears it.

## A command doesn't reach the panel

The manager publishes commands to `nspanel/<hostname>/command`. If the
panel was re-provisioned with a different hostname, the manager adopts
the panel's actual hostname at its next check-in — give it one cycle
(up to 5 minutes), or reboot the panel.

## The relays don't match the studio

The device config (the button modes, the relay boot states) is
**re-asserted at every check-in**. If a relay misbehaves: check the
Panel hardware tab — the mode ("always on"), the button mode (Direct vs
Detached) — and save. The panel converges at its next check-in.

## The send fails with "the display is not responding"

The manager refuses a TFT delivery toward a display that isn't answering
(a delivery would wedge the panel). Press **Display restart** on the
panel's web UI first, then Send again.

## The screensaver doesn't appear

Check the **Screensaver activation timeout** on the Screensaver tab —
0 means never sleep. The panel navigates to the screensaver after N
seconds without a touch.

## The photo doesn't show

The photo is processed at upload; if it failed, the studio says so
("could not be loaded — re-upload it"). Re-upload the photo from the
page's photo control.
