# 7. Updates

## Firmware

The panel checks the manager's manifest **every 5 minutes on its own** —
no MQTT command dependency, a flapping link cannot strand an update. When
a new firmware is published:

1. The panel fetches the new image over HTTP and flashes itself
2. Reboots into the new firmware
3. Re-registers and re-syncs the whole configuration from the manager

The update is announced on the panel's log topic and visible in its web
console.

## The display image

The display (the TFT) updates the same way — the manager compiles your
design and the panel streams it to the display's flash. The delivery's
safety rails:

- The delivery is confirmed by the **display's own boot announcement** —
  a partial image is never recorded as delivered
- A failed delivery is **retried automatically** (the display is
  power-cycled and the image re-sent)
- The manager re-delivers automatically if the panel ever reports a
  different image than the one you sent

## The manager

The manager updates through HACS like any custom integration. **Restart
Home Assistant after every manager update** — the code loads at startup.
