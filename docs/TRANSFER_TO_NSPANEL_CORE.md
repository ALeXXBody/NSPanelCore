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

### Live remote transfer (no USB, same broker)

When the panel already talks MQTT on a broker that Home Assistant also
uses, no screwdriver is needed. This was validated against a live
NSPanel Manager 2.x setup (panel on old firmware, old manager on the same
broker as HA):

1. **Prepare NSPanel Core**: install/update it to the latest version,
   set the manager address to your Home Assistant LAN IP and the port to
   `8123` (Settings page), and make sure at least one room exists.
   Registration is refused without rooms, and the panel learns its manager
   address from the accept reply — so these must be right *before* the
   panel reboots.
2. **Stop the old manager** for the duration of the window. Both managers
   would otherwise answer the panel's registration and the winner is
   nondeterministic. (It can be removed for good once the panel is over.)
3. **Reboot the panel** (power cycle, or its own web UI). On boot it sends
   `register_request`, which only NSPanel Core answers now.
4. **Accept** the panel when it appears under NSPanels (you also get an
   inbox message). Nothing is flashed before this click — the OTA consent
   gate guarantees it.
5. On accept, NSPanel Core compares the checksums the panel reported with
   its own files and triggers `firmware_update` (plus data/TFT as needed).
   The panel downloads, flashes, reboots into NSPanel Core firmware,
   re-registers (already accepted), updates its display if needed, and
   shows **online**.
6. Verify sensors, relays, lights and weather on the panel, then repeat
   per extra panel and decommission the old system.

If the panel does not appear within a couple of minutes, reboot it once
more (a lost race with a still-running old manager is the usual cause —
it can only win while the old manager is up).

## From the original NSPanel Manager (add-on / bridge)

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

## If a panel goes dark during a remote update

A dark panel (no ping, no web UI at its old address, no MQTT traffic for
>10 minutes) is not coming back on its own. Steps in order:

1. **Power-cycle it** (unplug 10 seconds, plug back in) and wait 5 minutes.
   If it was stuck mid-download, it reboots into its previous firmware and
   reappears — tell your helper what version its web UI reports and stop
   here.
2. **Check for its setup access point.** A panel that lost its Wi-Fi
   settings (e.g. after a data-partition flash) falls back to AP mode and
   broadcasts an `NSPanelCore` Wi-Fi network. Seeing that network means the
   panel is **alive, not bricked** — it just needs its Wi-Fi re-entered
   (no USB needed). No such network anywhere near it + still dark after a
   power cycle means it needs step 3.
3. **AP setup (no USB):** join the `NSPanelCore` network from a phone or
   laptop, open `192.168.1.1`, enter the Wi-Fi details plus the MQTT broker
   address, username and password, then restart it. (Tip: create a
   dedicated MQTT user for panels in your broker instead of reusing old
   credentials.) It will register with NSPanel Core on its own — accept it
   in the UI as usual (Step 3 of the main flow).
4. **If it stays dark: USB serial reflash.** You need physical access, a
   3.3 V USB-serial adapter, and the `merged_flash.bin` attached to the
   NSPanel Core release matching (or newer than) your install:
   download it, open the panel, connect TX→RX, RX→TX, GND→GND at 3.3 V
   (**never 5 V**), put the ESP32 into download mode (GPIO0 held low at
   reset — on the NSPanel this is the onboard button), then run:
   `esptool.py --baud 921600 --port /dev/ttyUSB0 write_flash 0x0 merged_flash.bin`
   (adjust the port). This installs the app firmware, partition table and
   blank filesystem in one shot.
3. After a USB flash the panel has **no Wi-Fi credentials**: join its
   `NSPanelCore` access point from a phone/laptop, open `192.168.1.1`, enter
   the Wi-Fi details plus the MQTT broker address and a **dedicated panel
   MQTT user** (create one in your broker up front — e.g. in the Mosquitto
   add-on settings — instead of hunting down old passwords), then restart
   it. It will register with NSPanel Core on its own — accept it in the UI
   as usual (Step 3 of the main flow). Make sure NSPanel Core is on the
   latest version *before* the panel comes back, so it is served current
   files and never receives an automatic data-partition update.

## After the move

- Remap dashboards and automations to the new entity IDs.
- Confirm the panel shows **online** with live status tiles, and that its
  relays, lights and weather/clock update.
- Future firmware and display updates arrive automatically over the air
  from NSPanel Core (see [Adding a panel](ADDING_A_PANEL.md),
  "Keeping panels updated") — no more USB flashing.
