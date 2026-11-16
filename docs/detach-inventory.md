# Detach Inventory — module-by-module verdicts (Step 1)

Generated: 2026-11-16 (P134). Scope: the approved rewrite (blueprint 2026 stack).
Verdicts: **KEEP** (port as-is/verified), **REWRITE** (rebuild native, behavior
contract frozen by tests), **DROP** (dead weight, proven unused or harmful).

Baseline: 82 pytest green, firmware 0.1.186 builds clean on pioarduino
55.03.312-1 (Arduino 3.3.x / IDF 5.5.5) — frozen as the maintenance line.

## HA integration (`custom_components/nspanel_core/`, ~7.9k lines)

| Module | Lines | Verdict | Notes |
|---|---|---|---|
| manager.py | ~2k | REWRITE | Core coordinator. Keep: panel lifecycle, MQTT topics, OTA push, evergreen flow. Drop: Django-era message queue, blocking sync calls, overlay/shadowing complexity (P131 showed the serving path must be manifest-first, always). |
| dashboard.py | ~2k | REWRITE (split) | Legacy custom web UI. Keep routes the panel *needs* (OTA download/checksum, stomp log bridge). Move human UI to HA-native (entities + MQTTOR lovelace) — custom htmx dashboard is the single biggest maintenance liability. |
| stomp_server.py | ~500 | KEEP (isolate) | Live log/status bridge for the dashboard; only surviving piece if the dashboard shrinks. |
| firmware_store.py | ~400 | KEEP (port) | Manifest → download → md5-verify → activate. Proven by P131/P132 to be the correct serving model. Make it the ONLY source of served files (no bundled fallback ambiguity). |
| models.py | ~450 | REWRITE | Dataclasses; drop legacy fields (django ids); keep panel identity (mac, hostname, version, md5s). |
| config_flow.py | ~300 | KEEP (touch-up) | HA-native already. |
| platforms (light/switch/sensor/climate) | ~1.2k | KEEP (port) | HA entity platforms; modernize only API usage. |
| const.py / __init__.py | ~200 | KEEP | Topic builders are the wire contract — freeze them via tests (Step 2). |
| panel_pb + protobuf | ~1.5k | KEEP | Wire codec — contract-frozen, panel-side must match byte-for-byte. |

## ESP32 firmware (`firmware/`, ~4.3k lines + libs)

| Module | Verdict | Notes |
|---|---|---|
| NSPanel (display UART) | REWRITE | Native UART driver + Nextion-style protocol. Bake in: single-baud model (P110), absurd-offset guard (P104/P177), gentle-first boot (P122), no display → continue booting (P130 lesson). TFT uploader = chunked stream with offset validation. |
| WebManager (OTA) | REWRITE | Native esp_http_server + esp_ota_ops. The OTA rails are now LOAD-BEARING (P126–P133): fw/fs split across reboots, fs unmount before write, bounded retries, watchdog, checksum-first. Ship these as the ONLY path. |
| MqttManager | REWRITE | esp-mqtt native. Topic builders = wire contract. |
| NSPMConfig | REWRITE | Native NVS (config) + LittleFS (static assets). Kill the fs-config round-trip complexity. |
| MqttLog | REWRITE (tiny) | Ring buffer + topic publish; keep log_backlog behavior (dashboard uses it). |
| PageManager + pages | REWRITE vs HMI | With nxwright HMI, the ESP side only needs: page switching, component text/int updates, touch event decode. Most per-page C++ logic MOVES to the HMI file — massive line-count win. |
| RoomManager/Room/Scene | REWRITE (thin) | State containers only; heavy logic belongs to the integration. |
| ButtonManager, Light*, InterfaceConfig | REWRITE (thin) | Same reasoning. |
| HttpLib | DROP | Native esp_http_client. |
| InterfaceManager | REWRITE | Task orchestration only; drop the Django-ported update-state machinery. |
| ChunkDownloader (upstream) | — | Never ported; not ours. |

## Tooling / releases

| Piece | Verdict |
|---|---|
| publish.sh (evergreen) | KEEP — wrap in CI |
| recovery page (ESP Web Tools) | KEEP — becomes the cutover vehicle (full-ours image) |
| usb_recovery kit | KEEP, regenerated per release |
| littlefsbuilder + mklittlefs | KEEP (x86-64 4.1.0 verified) |
| Go mirror (rewrite/nspanelcore) | KEEP as mirror per Step 0 |

## Known liabilities being killed by the rewrite
1. Serving stale files (P131) → firmware_store manifest-first is the only path.
2. fs-OTA death class (P126–P133) → native esp_ota_ops + the rails as code.
3. Version-display staleness (P134 finding: panels never re-register; app shows
   v0.3.967 stale) → registration/version must be a periodic report, not a
   one-shot boot event. **Contract test required.**
4. Custom web dashboard (Django-ported) → HA-native UI.
5. Arduino shim + 20 inherited libs → native IDF.
6. Binary HMI blobs → nxwright text source.

## Open items for Step 2 (contract freeze)
- Enumerate every MQTT topic (integration↔panel) into `tests/test_detach_contract.py`.
- Registration/version staleness fix must land in BOTH generations (1.3.x and 2.0).
