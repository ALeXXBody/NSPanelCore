# 6. The panel's own web UI

Every panel serves its own page at `http://<panel-ip>/` — open it directly
from a browser on the same network.

![The panel's web UI](https://raw.githubusercontent.com/wiki/ALeXXBody/NSPanelCore/panel-webui.png)

## Status

The live state: the firmware version, the stored checksums, the WiFi
signal, the heap, the temperature, the MQTT state, the manager it's
adopted, and the OTA state.

## Actions

- **Reboot** — a clean restart
- **FW update** — the panel fetches the manager's firmware and flashes
  itself over the air
- **Display restart** — power-cycles the display module and re-handshakes
  (the recovery step for a stuck/frozen display)
- **Factory reset** — wipes the config and reboots into the setup access
  point

## Debug console

Toggle the console to see the panel's last 64 events in real time — every
OTA milestone, every MQTT command, every touch. This is the first place
to look when something behaves oddly.

## Setup access point

On a factory-reset panel (or a fresh one), the panel serves its own
`NSPanelCore` access point: connect, open the config form, enter your
WiFi, the MQTT broker and the manager address. The panel reboots into
station mode and registers with the manager.
