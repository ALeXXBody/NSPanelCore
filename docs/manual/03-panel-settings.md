# 3. Panel hardware settings

The **Panel hardware** tab (inside the Dashboard studio, under the
preview) holds everything physical:

| Setting | What it does |
|---|---|
| Panel type | EU/US — affects the stock layout orientation |
| Default room | The room the panel belongs to |
| Button 1/2 mode | Direct / Detached / Custom MQTT / Follow (see below) |
| Detached entity | The HA entity the press routes to (Detached mode) |
| Custom MQTT topic/payload | Published on press (Custom MQTT mode) |
| Relay 1/2 default mode | The boot state of each relay ("always on" = the relay closes at every power-up) |
| Relay 1/2 as Switch/Light | The HA platform for the relay entity |
| Reverse relays | Swaps the relay order (the wiring compensation) |
| Show relay buttons on home page | The relay tiles on the delivered home page |
| Screen / screensaver brightness | The backlight levels (0–100) |
| Screensaver activation timeout | Seconds of no touch before the screensaver returns (0 = never) |
| Temperature calibration | The panel's own sensor offset |

Every save is **re-asserted to the panel at its next check-in** — the
panel always converges to what the studio says.

## The button modes, in practice

- **Direct** — the switch toggles the relay on the panel itself. No HA
  round-trip; works even if HA is down.
- **Detached** — the switch does NOT touch the relay; the press is sent to
  the manager, which routes it to the bound HA entity. This is the mode
  for "switch controls a HA light that isn't wired to the relay".
- **Custom MQTT** — full control: your own topic and payload.
- **Follow** — the relay toggles locally AND the manager is informed.

The relay boot state ("always on") is applied **at the panel's boot** —
the relay closes before the HMI even loads, so devices powered by the
relay never lose power during panel updates.
