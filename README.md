<div align="center">

# NSPanel Manager — HA Edition

**Standardised smart home control for Home Assistant users, using the original Sonoff NSPanel.**

Custom software for the Sonoff NSPanel (not the NSPanel Pro) designed to be easy to use
day to day and to manage multiple NSPanels around your home — with an intuitive interface
on the panel itself for people of all ages and backgrounds.

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Upstream](https://img.shields.io/badge/fork%20of-NSPManager%2FNSPanelManager-orange)](https://github.com/NSPManager/NSPanelManager)
[![Backend](https://img.shields.io/badge/controller-Home%20Assistant-41b1f6)](https://www.home-assistant.io/)
[![Stack](https://img.shields.io/badge/stack-mono--repo%20%7C%20Docker-2496ED)](docker/)

</div>

---

## About this fork

This is a **hard fork** of [NSPManager/NSPanelManager](https://github.com/NSPManager/NSPanelManager)
(GPL-3.0). Full credit to the original NSPanel Manager team — this project exists because of
their excellent work. This fork is maintained independently with the following focus:

### What changed

| | |
|---|---|
| 🏠 **Home Assistant only** | OpenHAB support has been fully removed (~3,500 LOC across the manager and MQTT bridge). All integrations target Home Assistant. |
| 📦 **Single monorepo** | Manager, MQTT bridge, web UI and panel firmware live in this one repository (upstream split them across three). One clone, one PR surface, one release. |
| ⚡ **Performance** | Panel UI round-trips cut from ~150–300 ms to ~10–40 ms (serial command pipeline rewrite), MQTT bridge de-locked and event-driven (no more 100 ms sleep-poll), Django settings/queries cached (panel editor ~105 queries → ~2), firmware OTA now streams with proper HTTP Range support, web UI bundle 36 MB → 1.2 MB. |
| 🛡️ **Stability** | Fixed the unsynchronized TFT command queue (random reboots after days of uptime), task-per-event heap churn, config-reload memory leak, upstream panel-config API 500 errors (renamed field crash), scenes API `NameError`, missing HTTP timeouts, and more — with a behavioral comparison harness verifying **zero regressions** against upstream. |
| 🧪 **Tested** | 61-endpoint Django comparison vs pristine upstream (35 byte-identical, 9 documented improvements, 0 regressions), C++ unit suite 9/9 green (upstream's own suite was unbuildable — repaired), firmware builds verified against upstream byte budgets, web UI type-checks and builds clean. |

### Repo layout (monorepo)

| Component | Path |
|---|---|
| Manager backend (Django 5.1) | [`docker/web/nspanelmanager/`](docker/web/nspanelmanager/) |
| MQTT bridge (C++, protobuf) | [`docker/MQTTManager/`](docker/MQTTManager/) |
| Kiosk web UI (React 19 + Vite) | [`docker/web-ui/`](docker/web-ui/) |
| Panel firmware (ESP32 / PlatformIO) | [`firmware/`](firmware/) |
| Protobuf definitions | [`docker/protobuf/`](docker/protobuf/) |
| Panel TFT binaries (runtime) | [`docker/HMI_files/`](docker/HMI_files/) |

## Documentation

The original NSPanel Manager documentation still applies to everything except the removed
OpenHAB parts:

- 📖 Docs: [nspanelmanager.com](https://nspanelmanager.com) (upstream documentation)
- 🎥 Walkthrough & install guide (upstream): [YouTube demo](https://www.youtube.com/watch?v=EzDDtguwFd4)
- 💬 Community Discord (upstream): [discord.gg/RwXvAH56fE](https://discord.gg/RwXvAH56fE)

## Building & running

```bash
# Build the full appliance image (manager + bridge + UI)
cd docker
docker build -t nspanelmanager-ha .
```

The Dockerfile builds everything in-tree: the web UI from `docker/web-ui/`,
the C++ MQTTManager with Conan/CMake, and the Django app — no network
checkouts of third-party repos at build time.

To modify the panel firmware and flash a panel over USB:

```bash
cd firmware
pio run -t upload   # requires PlatformIO
```

TFT (screen) updates are flashed through the manager web interface — the compiled
`.tft` files for all panel variants are kept in `docker/HMI_files/`.

> **Note:** the HMI design sources (XCF/GIMP + automation scripts) that generate the
> `.tft` files are not part of this repo; the compiled binaries are kept so panels
> can always download their theme.

## Support

If this fork has been useful to you, consider supporting the maintainer:

<div align="center">

### ☕ [Buy Me A Coffee — ALeXXBody](https://buymeacoffee.com/alexxbody)

*All support goes into hardware parts and tokens for building more free tools for the community.*

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-alexxbody-FFDD00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/alexxbody)

</div>

And if you run the *original* upstream project anywhere, the original NSPanel Manager team
also deserves your support: [buymeacoffee.com/nspanelmanager](https://buymeacoffee.com/nspanelmanager) ☕

## License

This project is licensed under the **GPL-3.0** — same as upstream, which it is derived from.
See [LICENSE](LICENSE).

Original project © the NSPanel Manager team ([NSPManager](https://github.com/NSPManager)).
This fork © Bogdan Turlea ([ALeXXBody](https://github.com/ALeXXBody)) and contributors.
