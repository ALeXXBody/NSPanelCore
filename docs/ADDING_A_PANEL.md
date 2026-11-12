# Adding an NSPanel to NSPanel Core

> Moving a panel from another system (original NSPanel Manager, ESPHome,
> Tasmota)? Start with [Transferring a panel to NSPanel Core](TRANSFER_TO_NSPANEL_CORE.md), then continue at Step 0 below.

This guide covers the full flow from the original NSPanel Manager app,
ported to **NSPanel Core** (the Home Assistant-native integration — no
add-on, no Docker, no separate process).

## What you need

1. **Home Assistant** with the **MQTT integration** configured
   (Settings → Devices & Services → MQTT). The broker must be reachable
   from your panels.
2. **NSPanel Core** installed (HACS → Integrations → NSPanel Core, or
   manual copy into `config/custom_components/`), plus the integration
   entry created under Settings → Devices & Services → NSPanel Core.
3. One or more Sonoff NSPanels flashed with the **NSPanel Core firmware**
   (`firmware/sonoff/firmware.bin`, `data_file.bin`, `gui.tft` in this
   repo, or the prebuilt `merged_flash.bin`).
4. The panels on the **same network** as Home Assistant and the broker.

## Step 0 — Point NSPanel Core at your network

Open the NSPanel Core sidebar panel → **Settings** and set:

| Field              | Value                                                          |
|--------------------|----------------------------------------------------------------|
| Manager address    | Your Home Assistant LAN IP (e.g. `192.168.1.10`)               |
| Manager port       | `8123` (your Home Assistant HTTP port)                         |

The panels download their configuration and firmware updates from
`http://<manager address>:<manager port>`, so these two fields must be
right or nothing else works. Save with the **Save** button (validation
errors are shown inline; nothing is stored until they pass).

Also set your location on the **Weather & Time** page (latitude/longitude)
if you want the clock, forecast and sunrise/sunset on the panel screensaver.

## Step 1 — Create at least one room

NSPanel Core refuses registrations while no rooms exist. Open
**Rooms** → **Create new room**, give it a name, save. Panels are assigned
to the first room when they register; you can move them later on the
panel's **Settings** page (`NSPanels → panel → Settings`).

## Step 2 — Power up the panel

A freshly flashed panel with Wi-Fi, MQTT broker and manager address
configured will, on boot:

1. Download its configuration from
   `http://<manager address>:<manager port>/api/get_nspanel_config?mac=<its MAC>`
   (retries until it succeeds).
2. Publish a registration request to the manager over MQTT.

No button-pressing is needed on the manager side — just power the panel on
the same network.

## Step 3 — Accept the panel

1. Open the **NSPanel Core** sidebar panel → **NSPanels**.
2. The new panel appears with a
   **"NSPanel '…' is requesting access."** overlay.
3. Press **Accept** (or **Deny** to block it — denied panels land on the
   **Denied NSPanels** page, where **Unblock** accepts them later).

On accept, NSPanel Core replies over MQTT and the panel reloads its
configuration. Within a few seconds the panel shows **online** and:

- Its status tiles (Wi-Fi signal, temperature, warnings) go live.
- It appears as a **Home Assistant device** with sensors
  (temperature, humidity, pressure, RSSI) and two **relay switches**.
- Its relays publish `r1/r2` state and respond to `r1/r2` commands.

## Step 4 — Map lights, scenes and rooms (optional)

- **Rooms** page: create rooms; each panel lives in one room.
- Panel **Settings** page: default page, screensaver, buttons, relays.
- Add lights on the entity pages so the panel can control them; light
  state flows back to the panel automatically.
- **Weather & Time** page: pick the temperature unit, clock style,
  wind/rain units and update interval.

## Keeping panels updated

NSPanel Core compares the checksums the panel reports at registration
time against its own files and triggers an update when they differ:

| File            | Upload in UI                          | Panel endpoint              |
|-----------------|---------------------------------------|-----------------------------|
| `firmware.bin`  | Settings → **Upload firmware**        | `/checksum_firmware`, `/download_firmware` |
| `data_file.bin` | Settings → **Upload data file**       | `/checksum_data_file`, `/download_data_file` |
| `gui.tft` / `gui_us.tft` | Settings → **Upload TFT file** | `/checksum_tft_file_eu|_us`, `/download_tft_eu|_us` |

Uploads are validated (board model allowlist, fixed filenames, 32 MB cap)
and take effect for the next registering or reloading panel. You can also
push an update immediately from the panel's page (**Firmware update** /
**GUI update** buttons) — the panel downloads, flashes and reboots by
itself.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Accept shows "Not authorized (HTTP 401)" | Your browser tab has no Home Assistant login (the panel pages render without one, so everything looks fine until you click something). A red banner at the top of the page says the same. Log in to Home Assistant at that address, hard-refresh, and Accept. |
| Panel never appears under NSPanels | Wrong manager address/port on the panel, or no MQTT route to the broker. Check the panel can reach `http://<manager address>:<manager port>/`. |
| "Cannot register NSPanel: no rooms exist" in the HA log | Create a room first (Step 1). |
| Panel accepted but stays offline | Status reports (`nspanel/<name>/status_report`) not arriving — check the broker ACLs/topics. |
| Weather/clock empty | Set latitude/longitude on the Weather & Time page; the panel polls every `weather_update_interval` minutes. |
| Upload rejected | Wrong board model selected, or file over 32 MB. |
| Inbox badge lit | Open the inbox (top bar) — NSPanel Core notifies you of panels requesting access. |

All UI controls that change anything require a logged-in Home Assistant
user; the panel-facing download endpoints only serve the fixed firmware
files and configs belonging to registered panels.
