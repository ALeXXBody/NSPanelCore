# Transferring a panel to NSPanel Core

This guide moves a Sonoff NSPanel from **another system** to
**NSPanel Core**. It applies whether the panel currently runs the original
**NSPanel Manager**, **ESPHome**, **Tasmota**, or anything else.

The rule is simple: **NSPanel Core only talks to panels running the
NSPanel Core firmware** (the JSON-over-MQTT protocol in this repo). A panel
on any other firmware must be reflashed first. Everything below that point
— registration, configuration, updates — is then identical (see
[Adding a panel](ADDING_A_PANEL.md)).

> **Back up first.** Flashing replaces the panel's firmware completely.
> Screenshot or export anything you want to keep: entity names, room
> assignments, button actions, automations and dashboards that reference
> the panel's current entities. Entity IDs will be **different** after the
> move — plan to remap dashboards and automations.

## What you need

- A USB-to-serial adapter (3.3 V) and a way to open the panel for the
  first flash (stock/foreign firmware cannot install ours over the air).
- `esptool.py` (`pip install esptool`) or the PlatformIO setup in
  `firmware/` (`pio run -t upload -e esp32dev`).
- The NSPanel Core images from this repo:
  `custom_components/nspanel_core/firmware/sonoff/merged_flash.bin`
  (ESP + filesystem in one image).
- Home Assistant with the MQTT integration, NSPanel Core installed, and
  the manager address/port set to your HA host (see
  [Adding a panel](ADDING_A_PANEL.md), Step 0). Create at least one room
  before you start.

## Step 1 — Flash the NSPanel Core firmware (USB serial)

1. Open the panel, connect the serial adapter (TX→RX, RX→TX, GND→GND,
   3.3 V — **never 5 V**), and put the ESP32 into download mode.
2. Full-erase first when coming from a foreign system (different
   partition layout than ESPHome/Tasmota/stock):
   `esptool.py --port /dev/ttyUSB0 erase_flash`
   (adjust the port to your machine).
3. Flash the merged image at offset zero:
   `esptool.py --baud 921600 --port /dev/ttyUSB0 write_flash 0x0 merged_flash.bin`
4. Reassemble and power the panel from mains.

> The panel's touchscreen (Nextion display) is updated separately: on
> first boot the panel downloads `gui.tft` / `gui_us.tft` from NSPanel Core
> over HTTP and flashes its own screen — no SD-card step needed. Keep the
> panel powered and on the network until the screen shows the NSPanel UI.

## Step 2 — Give the panel its network settings

The panel needs three things: **Wi-Fi credentials**, the **MQTT broker**
(usually your existing broker — reuse it so nothing else has to move),
and the **manager address/port** (`<HA LAN IP>:8123`, i.e. what you set
in NSPanel Core → Settings). Enter them via the panel's own setup
(display prompts / device AP), then let it reboot.

## Step 3 — Accept it in NSPanel Core

From here the flow is identical for every panel, new or transferred:

1. NSPanel Core → **NSPanels**: the panel appears as
   *"NSPanel '…' is requesting access."*
2. Press **Accept** (or **Deny** to block it; denied panels can be
   unblocked later from **Denied NSPanels**).
3. The panel downloads its configuration, reloads, and shows **online** —
   with sensors (temperature, humidity, pressure, RSSI) and two relay
   switches appearing as Home Assistant entities.

Full details: [Adding a panel](ADDING_A_PANEL.md), Steps 3–4
(rooms, lights, weather, OTA).

## System-specific notes

### From the original NSPanel Manager (add-on / bridge)

- Easiest case: your panels already speak the same JSON protocol family.
  Still reflash with the NSPanel Core image so ESP, filesystem and display
  versions match what this repo serves over OTA.
- The old manager's address (`mqttmanager_<name>`) no longer exists.
  Point everything at NSPanel Core's manager address instead.
- Rooms, lights, scenes and button mappings live in the old manager's
  storage and **do not migrate** — recreate them in the NSPanel Core UI.
  Keep the old UI open side-by-side while you copy the mapping over.
- MQTT topics change shape (`nspanel/<name>/…` stays, but anything under
  the old `mqttmanager_<address>` prefix moves to NSPanel Core's). Update
  any external MQTT automations accordingly.
- When the last panel is moved, the old add-on/bridge can be stopped and
  removed. Your MQTT broker stays — NSPanel Core uses HA's MQTT
  integration.

### From ESPHome

- An ESPHome panel cannot be converted in place: flashing the NSPanel Core
  image over USB replaces ESPHome entirely (Step 1).
- Before flashing, note which ESPHome entities the panel exposed (sensors,
  switches, display pages) so you can rebuild the equivalent in
  NSPanel Core (relays become switches, temperature becomes a sensor).
- After the move, the ESPHome device entry will show offline — delete it
  from the ESPHome dashboard to keep things tidy. If you compiled the
  ESPHome firmware yourself, no YAML changes are needed anywhere: the
  device is simply gone.
- ESPHome automations referencing the panel must be rewritten against the
  new NSPanel Core entities (different entity IDs by design).

### From Tasmota or other ESP32 firmware

- Same as ESPHome: full erase + USB flash of `merged_flash.bin` (Step 1).
  Tasmota OTA cannot install this image — use the serial method.
- Tasmota rules, timers and MQTT topics (`tele/`/`stat/`/`cmnd/`) do not
  transfer. Rebuild the behavior with NSPanel Core rooms/lights/scenes
  and Home Assistant automations.
- If the panel was part of a larger Tasmota fleet, nothing else is
  affected — only the flashed panel changes identity.

## After the move

- Remap dashboards and automations to the new entity IDs.
- Confirm the panel shows **online** with live status tiles, and that its
  relays, lights and weather/clock update.
- Future firmware and display updates arrive automatically over the air
  from NSPanel Core (see [Adding a panel](ADDING_A_PANEL.md),
  "Keeping panels updated") — no more USB flashing.
