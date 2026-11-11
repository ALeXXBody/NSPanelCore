# Installing NSPanel Core

The NSPanel Core integration runs **inside Home Assistant** — no Docker,
no add-on, no build pipeline. The legacy Docker add-on has been retired to a
separate repository ([nspanel-core-addon](https://github.com/ALeXXBody/nspanel-core-addon))
and is not needed.

## Requirements

- The **MQTT integration** configured in Home Assistant
  (Settings → Devices & Services → MQTT)
- Panels already flashed and on the same network as the MQTT broker

## Install (HA Marketplace)

1. In Home Assistant, open **HA Marketplace** → add a **custom repository**:
   `https://github.com/ALeXXBody/NSPanelCore` (category: **integration**)
2. Install **NSPanel Core** from it.
3. Settings → Devices & Services → **Add Integration** → **NSPanel Core** → Submit.
   (No connection settings needed — it uses HA's own MQTT broker connection.)
4. Power-cycle your panels. They announce themselves on MQTT and register
   automatically; each panel appears as a device with sensors.

## Install (manual fallback)

If you prefer not to use a marketplace:

1. Copy the folder [`custom_components/nspanel_core/`](custom_components/nspanel_core/)
   into your HA `config/custom_components/` directory.
2. Restart Home Assistant, then continue from step 3 above.


Both options expect panels already running the NSPanel firmware. To flash a
panel over USB, use the web flasher from the upstream project documentation.

## Status

- ✅ Panel registration & configuration
- ✅ Light control (brightness / color temperature / RGB)
- ✅ Panel sensors + relay switches
- 🚧 Room/entity-page configuration UI
- 🚧 Scenes, thermostats
