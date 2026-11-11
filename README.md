<div align="center">

<img src="branding/nspanel-core-logo.png?v=3" alt="NSPanel Core" width="380">

**Smart Wall OS for the Sonoff NSPanel — as a native Home Assistant integration.**

Custom software for the Sonoff NSPanel (not the NSPanel Pro) that turns your panels
into first-class Home Assistant devices — no Docker, no add-on, no build pipeline.

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Home%20Assistant-41b1f6)](https://www.home-assistant.io/)
[![Install](https://img.shields.io/badge/install-HA%20Marketplace-00CC66)](INSTALL_HA.md)

</div>

---

## What it does

- **Registers panels automatically** — panels announce themselves on MQTT and
  appear as devices in Home Assistant
- **Controls your home from the wall** — panel buttons and page interactions
  drive your real HA lights and scenes through native service calls
- **Real HA entities for panel hardware** — temperature/humidity/pressure/RSSI
  sensors and relay switches per panel
- **Speaks the panels' own protocol** — same MQTT/protobuf contract the panel
  firmware already uses; no panel reflashing needed

## Installation

Full guide: **[INSTALL_HA.md](INSTALL_HA.md)**

1. Requires the **MQTT integration** configured in Home Assistant
2. Install via **HA Marketplace** (add `https://github.com/ALeXXBody/NSPanelCore`
   as a custom repository, category *integration*) or copy
   [`custom_components/nspanel_core/`](custom_components/nspanel_core/) into
   HA's `config/custom_components/`
3. Add the **NSPanel Core** integration, then power-cycle your panels

## Status

- ✅ Panel registration & configuration
- ✅ Light control (brightness / color temperature / RGB)
- ✅ Panel sensors + relay switches
- 🚧 Room/entity-page configuration UI
- 🚧 Scenes, thermostats

## Firmware

Panel firmware sources live in [`firmware/`](firmware/). The panels' screen
protocol and MQTT contract are documented in [`BRIDGE_GO_REWRITE.md`](BRIDGE_GO_REWRITE.md).

## Support

If NSPanel Core has been useful to you, consider supporting the maintainer:

<div align="center">

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-alexxbody-FFDD00)](https://buymeacoffee.com/alexxbody)

</div>

## License

GPL-3.0 — see [LICENSE](LICENSE). Based on the NSPanel Manager project by the
NSPManager team.
