# Installing NSPanel Core

There are two ways to run NSPanel Core. Pick based on your situation:

| | **HA Integration** (recommended going forward) | **HA Add-on** (legacy, separate repo) |
|---|---|---|
| Install method | HA Marketplace / copy a folder | Add-on store |
| Runs as | Inside Home Assistant | Docker container in Supervisor |
| Build/update pain | **None** — plain Python files | Docker image builds (slow, was unreliable) |
| Status | **In development** — panels register, lights/sensors work; mapping UI, scenes, thermostats still being ported | **v1.0.2 is the last verified-installable release**. Later tags (v1.0.4–v1.0.6) never published images and cannot be installed |

---

## Option 1: HA integration (recommended)

### Requirements

- The **MQTT integration** configured in Home Assistant (Settings → Devices & Services → MQTT)
- Panels already flashed and on the same network as the MQTT broker

### Install (HA Marketplace)

1. In Home Assistant, open **HA Marketplace** → add a **custom repository**:
   `https://github.com/ALeXXBody/NSPanelCore` (category: **integration**)
2. Install **NSPanel Core** from it.
3. Settings → Devices & Services → **Add Integration** → **NSPanel Core** → Submit.
   (No connection settings needed — it uses HA's own MQTT broker connection.)
4. Power-cycle your panels. They announce themselves on MQTT and register
   automatically; each panel appears as a device with sensors.

### Install (manual fallback)

If you prefer not to use a marketplace:

1. Copy the folder [`custom_components/nspanel_core/`](../custom_components/nspanel_core/)
   into your HA `config/custom_components/` directory.
2. Restart Home Assistant, then continue from step 3 above.

### What works today

- Panel registration and configuration (protobuf protocol, unchanged from the panels' side)
- Light mapping stored and driven through Home Assistant (panel → HA service calls)
- Panel sensors: temperature, humidity, pressure, RSSI
- Relay switches (button relays)

### In development

- Config UI for rooms / entity pages / scene mapping (currently storage-based)
- Scenes activation from panels
- Thermostat platform
- Web-app (browser kiosk) panel

Track progress in [BRIDGE_GO_REWRITE.md](../BRIDGE_GO_REWRITE.md) — the wire
contract documented there is exactly what the integration implements.

---

## Option 2: Add-on (legacy)

> **Note:** releases v1.0.4, v1.0.5 and v1.0.6 look available in the add-on
> store but have **no Docker images behind them** — installing them fails or
> silently keeps your current version. Use **v1.0.2** if you need the add-on.

1. Settings → **Add-ons → Add-on Store → ⋮ menu → Repositories**
2. Paste this URL and click **Add**:

   ```
   https://github.com/ALeXXBody/nspanel-core-addon
   ```

3. Open **NSPanel Core → Install → Start** (enable *Start on boot* and
   *Watchdog* — both default on)
4. Open the add-on's web UI and follow the initial setup guide
   (MQTT + Home Assistant connection)

### Requirements (add-on)

- An MQTT broker (e.g. the Mosquitto broker add-on)
- Docker host on **amd64**

### GHCR package visibility (one-time, add-on only)

If the add-on images were pulled while private, flip them to public once:

1. Open `https://github.com/ALeXXBody?tab=packages`
2. Open `nspanel-core-amd64` → **Package settings** → **Danger Zone** →
   **Change visibility** → **Public**.

---

## Panel flashing

Both options expect panels already running the NSPanel firmware. To flash a
panel over USB, use the web flasher from the upstream project documentation.
