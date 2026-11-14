# NSPanel Core — Master Ledger (Guide & Rule Book)

> **RULE: Before starting ANY development, modification, or removal task,
> write the request in this ledger first, then begin work.**
> If this ledger is not respected, the repository will be audited 100 times.

---

## 1. What is NSPanel Core?

NSPanel Core is a **Home Assistant-native replacement** for the NSPanel Manager add-on.
It manages Sonoff NSPanel panels over MQTT using the same protobuf/JSON wire protocol
the panels' firmware already speaks. No separate process, no WebSocket client, no token.

**Architecture:**
- **Panel ↔ Integration**: MQTT, protobuf + JSON (same topics as the original add-on)
- **Integration ↔ HA**: event bus (state changes), service calls
- **UI**: Original NSPanel Manager web UI ported to Jinja2, served by the integration
- **Zero external dependencies**: hand-rolled protobuf codec (byte-identical to generated code)

**Repository:** `ALeXXBody/NSPanelCore` (GitHub)
**Current version:** v1.3.3
**License:** GPL-3.0
**Credits:** Original NSPanel Manager team (upstream)

---

## 2. Ledger — What the user wants/needs

### 2.1 Integration (HA custom component)

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| I1 | Panel registration flow (register_request → accept → config) | ✅ Done | 1:1 with original add-on |
| I2 | Light state machines (HA events, service calls, optimistic mode) | ✅ Done | Brightness, color temp, RGB |
| I3 | Room aggregation (NSPanelRoomStatus protobuf) | ✅ Done | Ceiling/table light counts, dim levels |
| I4 | Entity pages (NSPanelRoomEntitiesPage protobuf) | ✅ Done | Slot positions, scene pages |
| I5 | Command routing (light, toggle, first-page, save scene, thermostat) | ✅ Done | All command types handled |
| I6 | Scene activation (HA scenes/scripts + NSPM saved states) | ✅ Done | 1:1 with original |
| I7 | Weather polling (open-meteo → NSPanelWeatherUpdate protobuf) | ✅ Done | Configurable units, every N minutes |
| I8 | Time/date publishing (minute-aligned) | ✅ Done | US/24h style, date format |
| I9 | Firmware OTA (checksum comparison → firmware_update command) | ✅ Done | Binary committed (5.2MB) |
| I10 | Data-file OTA (checksum comparison → data_file_update command) | ✅ Done | Binary committed |
| I11 | TFT OTA (checksum comparison → tft_update command) | ✅ Done | TFT files committed (12MB each) |
| I12 | Thermostat support (climate service calls, state publishing) | ✅ Done | HA climate integration |
| I13 | Relay groups (group on/off controls all bound relays) | ✅ Done | Model + manager method |
| I14 | Panel sensors (temperature, humidity, pressure, RSSI as HA entities) | ✅ Done | Sensor platform |
| I15 | Relay switches (button1/button2 as HA switch entities) | ✅ Done | Switch platform |
| I16 | STOMP server (live UI updates, MQTT mirroring) | ✅ Done | Base64 payload mirroring |
| I17 | Original UI (all 9 pages ported from Django to Jinja2) | ✅ Done | Served by aiohttp views |
| I18 | Panel settings page (edit_nspanel template) | ✅ Done | Save flow wired |
| I19 | Rooms page (create, delete, list) | ✅ Done | Full CRUD |
| I20 | Web app (PWA browser preview at /webapp) | ✅ Done | Served via views |
| I21 | Brand icons for HA Marketplace | ✅ Done | brand/ + www/brand/ directories |
| I22 | Panel registration without black header bar | ✅ Done | panel_custom(embed_iframe=True) |
| I23 | Responsive layout | ✅ Done | w-screen → w-full |
| I24 | No external dependencies | ✅ Done | Hand-rolled protobuf codec |
| I25 | Messages support | ⚠️ Partial | Model exists, UI not fully wired |

### 2.2 Firmware (ESP32)

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| F1 | WebSocket client with masked pong frames | ✅ Done | Critical fix for connection stability |
| F2 | Ping timeout configuration (60s) | ✅ Done | Prevents premature disconnections |
| F3 | Pre-built firmware binaries committed | ✅ Done | sonoff + custom models |
| F4 | OTA partitioning (ESP-IDF) | ✅ Done | Firmware/data/TFT updates |
| F5 | Panel registration (register_request every 3s) | ✅ Done | JSON on nspanel/mqttmanager/command |
| F6 | Status reporting (temp, humidity, pressure, RSSI) | ✅ Done | JSON on nspanel/<mac>/status |
| F7 | Command handling (light, scene, thermostat, etc.) | ✅ Done | Protobuf on nspanel/<mac>/command |
| F8 | Config reception (NSPanelConfig protobuf) | ✅ Done | On nspanel/<mac>/config (retained) |

### 2.3 Request — sidebar panel blank page / refresh (2026-11-12)

| # | Request | Status |
|---|---------|--------|
| P1 | Sidebar panel must never render blank | ✅ Done (v1.3.3, browser-verified) |
| P2 | Refreshing `/nspanel_core` must stay inside HA's content area (no bounce to `/`, no full takeover) | ✅ Done (v1.3.3, browser-verified) |
| P3 | No HA `hass-subpage` title bar above the UI; navbar stays | ✅ Done (v1.3.0) |
| P4 | Logo slightly bigger; version read from `manifest.json` with `v` prefix; responsive | ✅ Done (v1.3.3: 40px logo, v1.3.3, 820px viewport OK) |
| P5 | Verify in a real browser (Playwright + Chromium), not by inspection | ✅ Done (direct load + reload, 1184×900) |
| P6 | A new release must never be masked by a stale browser cache: panel module + UI assets must be cache-busted per version | ✅ Done (v1.3.4, stale-cache simulation verified) |
| P7 | Full audit — every linkage, every file, every piece of code; app is currently a mess | 🔄 In progress (audit pass 6) |
| P8 | Fix audit findings in order 1–6 | ✅ All 6 done, committed, browser/MQTT-verified (v1.3.5) |
| P9 | User guide: how to add NSPanel devices, based on the original app flow, branded NSPanel Core | ✅ Done (docs/ADDING_A_PANEL.md, all claims verified against code; docs-only, no version bump) |
| P10 | Firmware check: is it working + branded NSPanel Core? Test everything in a venv | ✅ Done (branding sweep; 11-test contract suite green; esp32dev build SUCCESS) |
| P11 | Migration guide: transfer a panel from NSPanel Manager / ESPHome / other apps | ✅ Done (docs/TRANSFER_TO_NSPANEL_CORE.md, cross-linked from ADDING_A_PANEL.md) |
| P12 | Simple transfer/first-use guide in readme.md | ✅ Done (README "First use" section, links both guides) |
| P13 | Remote firmware update to transfer the live panel (.23) from NSPanel Manager (.20:8000) to NSPanel Core | ⚠️ Panel went dark during OTA flash (~15:05 UTC) and hasn't returned. Awaiting user power-cycle; USB reflash prepped (fresh 0.1.152 merged image in repo) |
| P14 | Accept fails: browser sent no valid token (server log 401s) + toast hid real errors | ✅ Done: v1.3.7 visible errors + proactive refresh; v1.3.8 override (reverted); v1.3.10+ login banner; v1.3.12 sessionStorage lookup; v1.3.13 live-token postMessage path |
| P15 | Investigate: working HA + sidebar access yet no hassTokens in localStorage | ✅ Root cause: unchecked "Remember me" keeps tokens in sessionStorage only; fixed by reading both stores |
| P16 | Panel dark post-OTA | ✅ Panel came back on its own running OUR 0.1.152 firmware (JSON reports on hostname topics, entities live: temp + rssi updating). No USB needed. Remaining: TFT display file still old (needs explicit tft_update + EU/US variant confirm), panel hostname is default "NSPanelCore". |
| P17 | Live-transfer runbook validated end-to-end on real hardware | ✅ Done (accept → auto OTA → re-register → entities live), documented in TRANSFER_TO_NSPANEL_CORE.md "Live remote transfer" + recovery sections |
| P17 | Branding leftovers: panel setup page title + About dialog still referenced old project | ✅ Done v1.3.15 (rebuilt littlefs + merged images, content bytes verified) |
| P18 | REDO ALL FIRMWARES: clean full rebuild from current source (fresh ESP fw 0.1.152 + rebranded web UI data fs + merged images), class rename, verified byte-for-byte; TFT display files cannot be rebuilt here (need Windows Nextion Editor + rebranded HMI) — documented honestly | ✅ Done, needs release |
| P19 | Full firmware audit + rebranded display file COMPILED (Nextion Editor 1.68.2 headless via Wine+sztupy toolchain), verified (181 pics, CRCs ok, dims match project), shipped as gui.tft via evergreen manifest (no app release) | ✅ Done, needs panel flash with user watching |
| P20 | Decouple firmware from app releases (COMPLETE): evergreen assets + publish.sh + RELEASING.md rule; bogus v1.3.28 app release for firmware-only change DELETED (release+tag), version strings reverted to 1.3.27 | ✅ Done |
| P26 | Remote access dead (Nabu Casa/reverse proxy): STOMP URL built as host: + empty port; fixed with conditional port, sandbox-verified | ✅ Done, needs release |
| P29 | Firmware tab removed: hardcoded manifest URL + 6h auto-check with Messages inbox notify; manual check/install in Actions menu; fixed blocking-I/O | ✅ Done, released v1.3.31 |
| P30 | Per-panel update buttons clarified: ESP (warns it wipes WiFi) vs display (~15 min); user asked why both exist | ✅ Done, needs release |
| P31 | Remove lower Actions dropdown (keep header one); moved bulk firmware/GUI updates + restart into header menu | ✅ Done, released v1.3.35 |
| P30 | Panel firmware version on each card (small, discrete; hidden when unknown) | ✅ Done, needs release |
| P31 | Black screen root causes: (1) panel.hostname/panel.name split (space) black-holed all MQTT both ways — reunited on KitchenPanel name; (2) screen_dim_level default 0 blanked backlight at boot — default 100 + brightness push | ✅ Done, needs release |
| P32 | Kill dead NSPM-flag handshake (no display file ever sent it; permanent bogus warning): real comok-based display check, _display_ready rename, honest warning text (fw 0.1.160, no app release) | ✅ Done |
| P27 | Save POST shadowed by action route (rename always 400 "Unknown action"): dedicated /api/panel_save/{id} endpoint, verified 404-proper on sandbox | ✅ Done |
| P28 | STOMP auth ERROR loop (dead token retried forever, blank cards): beforeConnect re-reads token every attempt, ERROR decodes+refresh+reconnect, login banner after 3 | ✅ Done, verified in harness |
| P21 | Push OTA to panels immediately on firmware activation (same OTA path as TFT) + per-panel update_firmware/update_tft actions | ✅ Done, needs release |
| P22 | Fix duplicated reboot; unpopulated UI values: forward rssi/temperature/heap/ip to STOMP status topic (verified merge), heap inversion fix, new ip/heap sensors, capability-gated humidity/pressure | ✅ Done, released |
| P23 | UI cleanup + ESP dark mode | ✅ + follow-up: toggle was dead (missing </script> killed page JS); fixed, verified click→dark→persist, CSS cache-busted (fw 0.1.159) |
| P24 | Per-panel rooms UI — REVERTED, user never asked for it; awaiting concrete dashboard spec | ❌ Reverted |
| P25 | Customisable panel dashboard (A rooms shown, C button modes+MQTT topics now save+serve, B home widget visibility fw+config+UI) | ✅ Done, needs verify+release |

> **P13 recon (read-only, 2026-11-12):**
> - Panel `.23:80` serves its own config UI: `wifi_hostname=KitchenPanel`,
>   fw `0.3.1102`, MQTT `.20:1883` user `ALeXX`, manager `.20:8000`
>   ("Accepted"). No manager field, no upload endpoint on the panel.
> - Old manager `.20:8000` = NSPanel Manager v2.1.9-beta3, public UI, same
>   broker (`.20:1883`), has firmware upload + per-panel OTA.
> - LAN scan: only `.20` and `.200` (sandbox) have 1883 open → HA's Mosquitto
>   add-on broker IS `.20:1883`, shared by panel + old manager + HA.
> - Proven live on the shared broker via HA WS `mqtt/subscribe`: panels
>   `E4:65:B8:49:A1:00` (= KitchenPanel, id 2) and `B0:CB:D8:99:37:54`
>   (= DressingRoom, id 3) publish status/relay/screen/config traffic.
> - Our firmware takes `manager_address` ONLY from `register_accept`
>   (RAM, re-acquired every boot AFTER register — no persistence trap).
> - Consent gate added (v1.3.6): OTA fires only for accepted panels, and is
>   evaluated at accept time from stored md5s (sandbox-verified: none while
>   unaccepted, firmware+data+tft after accept).
>
> **Runbook (needs: Core v1.3.6 on prod, manager address = HA LAN IP,
> port 8123, ≥1 room; then during the window):**
> 1. User stops the old NSPanel Manager (kills the accept race; both
>    managers would otherwise reply and last-writer-wins per reboot).
> 2. User reboots the panel (power cycle; its web UI stays up as fallback).
> 3. Panel registers → appears in NSPanel Core as awaiting accept (+ inbox
>    message). No flash happens before accept (gate).
> 4. User accepts → accept+reload sent → checksums differ → firmware_update
>    (+ data/TFT as needed) → panel flashes, reboots into NSPanel Core,
>    re-registers (already accepted), TFT updates, online.
> 5. Verify entities/control in HA; then decommission the old manager.
> 6. Same flow per extra panel (DressingRoom).

> **P6 evidence (2026-11-12, on the user's real HA 192.168.50.20, HA 2026.11.1 /
> frontend 20261028.5):** the panel rendered fine in a clean browser profile,
> yet stayed blank in the user's browser. Cause: `/nspanel_core/static/*` is
> registered with `cache_headers=True`, so HA serves `panel.js` with
> `Cache-Control: public, max-age=2678400` (31 days), and the panel's
> `module_url` never changed between releases. A browser that had cached the
> v1.3.2 `panel.js` (which pointed its iframe at `/nspanel_core`, the SPA route)
> kept running that old file forever: the panel iframe recursed into the SPA
> and showed a blank page. Reproduced with Playwright by serving the cached
> v1.3.2 file: frames `[..., '/nspanel_core', ..., 'about:blank']`, zero UI,
> no error. With the current file the same URL renders the UI (159 nodes).
> Fix: version the module URL (`panel.js?v=<version>`) and version every
> UI static reference (`?v={{ version }}` instead of `?refresh=1`).
>
> **P6 verification (2026-11-12, exact stack HA 2026.11.1 + frontend
> 20261028.5):**
> - Panel config now reports `module_url=/nspanel_core/static/panel.js?v=v1.3.4`.
> - Browser requests only the versioned URL; the stale unversioned URL is never
>   fetched (route counter 0/0 while an old v1.3.2 file was planted at the
>   unversioned URL), and the panel renders 159 nodes with `v1.3.4` on load and
>   on reload.
> - All 8 UI pages render with every static reference versioned
>   (`?version=v1.3.4`), `refresh=1` gone, 19/19 referenced assets HTTP 200.
> - Responsive check: 1440×900 and 820×1180, no horizontal overflow,
>   40px logo, version `v1.3.4`.
> - Also fixed during the audit: 4 status components imported hybrids from
>   `/static/...` (missing `/nspanel_core` prefix → 404 when those tiles
>   render).

**Root cause found (evidence):** `MainPageView` was registered at the exact
path `/nspanel_core`, the same path `panel_custom` reserves for HA's SPA.
A direct load/refresh of `/nspanel_core` therefore returned the integration's
own Jinja page instead of HA's SPA; that page contained
`if (window.self === window.top) location.href = "/"`, which bounced the
browser out of the panel. Inside the iframe the page was fine, which is why
the panel sometimes looked blank/missing after a refresh on newer HA.

**Fix under test:** serve the UI at `/nspanel_core/ui`, leave `/nspanel_core`
to HA's SPA (panel route), delete the redirect script, and point the panel
iframe at the new UI path.

### 2.4 Cross-cutting

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| C1 | MQTT topic consistency | ✅ Done | Same topics as original add-on |
| C2 | Protobuf wire format compatibility | ✅ Done | Byte-identical to generated code |
| C3 | Firmware needs no reflashing | ✅ Done | Same MQTT/protobuf protocol |
| C4 | Panel registration flow 1:1 with original | ✅ Done | Verified against C++ bridge |
| C5 | Zero secrets in codebase | ✅ Done | Audited |
| C6 | GPL-3.0 license preserved | ✅ Done | README credits upstream |

---

## 3. Rules for development

0. **HIGH PRIORITY RULE R1 (user-ordered 2026-11-14): EVERYTHING implemented or changed
   must be PROPERLY TESTED before any release. No exceptions.**
   "Properly tested" means: unit tests AND end-to-end verification of every
   user-facing path the change touches (pages actually opened, flows actually
   executed against a live panel/manager — not just data-level checks).
   A release without this is a defective release. Violations found: v1.3.48
   (Denied page 500 — unit test passed, page never opened).
0.1. **HIGH PRIORITY RULE R2 (user-ordered 2026-11-14): BEFORE starting any given task, go through the ledger and check the info already known. If something in the task contradicts known info, STOP and tell the user before doing anything.** No exceptions.
0.2. **HIGH PRIORITY RULE R3 (user-ordered 2026-11-14): ANSWER EVERYTHING THE USER ASKS. Every point, every question in a message gets an answer — never cherry-pick the easy technical bit and silently drop the rest. If something cannot be answered yet, say so explicitly instead of skipping it.** No exceptions.
0.3. **HIGH PRIORITY RULE R4 (user-ordered 2026-11-14): FINISH EVERY REQUEST. Every user request runs to completion — never leave work half-done, parked, or silently dropped. The ONLY legal stops are: the user explicitly says STOP or PAUSE. "Add to queue" means: write the item into the ledger queue AND CONTINUE the in-progress work in the same session — queued is not paused. Backgrounded waits (watches, builds, long polls) do not end the request: use the wait for independent pre-validation, then resume and finish on notification.** No exceptions.
1. **Write in this ledger FIRST** before starting any task
2. **Verify every change** — run full audit after every modification
3. **Test end-to-end** — check that integration and firmware work together
4. **No hardcoded IPs** — ever
5. **No quick dirty fixes** — do it properly
6. **Verify entity IDs** against the actual HA entity registry
7. **Verify MQTT topics** match between firmware and integration
8. **Verify state payloads** match between publisher and subscriber
9. **Verify command handlers** are registered and match
10. **Bump version** and create release after every change
    - Bug fixes → increment patch (v1.3.1 → v1.3.2)
    - Major improvements → increment minor (v1.3.x → v1.4.0)
    - Breaking changes → increment major (v1.x.x → v2.0.0)
11. **Never reuse a version number** for different changes
12. **Verify templates render** after any template change
13. **Verify imports resolve** after any code change
14. **Run full audit** after every change — no exceptions

---

## 4. Audit history

| Pass | Date | Issues found | Issues fixed |
|------|------|-------------|-------------|
| 1 | 2026-11-11 | Missing _on_relay_state, merged classes, 14 template errors | v1.3.1 |
| 2 | 2026-11-12 | sensor.py attribute access, _send_panel_config pages filtering, division by zero, date format, apply_settings await, _manager null guard, model to_dict/from_dict, blocking I/O | v1.3.1 |
| 3 | 2026-11-12 | Blocking I/O, sensor attribute access, _send_panel_config, _manager guard, apply_settings await, kelvin_pct guard, date_format, model to_dict/from_dict, EditRoomView, hs_color bounds | v1.3.2 |
| 4 | 2026-11-12 | Route collision (`/nspanel_core` UI shadowed HA SPA → refresh bounce), redirect script, hardcoded version, blocking manifest read | v1.3.3 |
| 5 | 2026-11-12 | Stale 31-day browser cache masking new panel.js (blank panel), unversioned UI assets, 4 status components importing hybrids from `/static/...` (404) | v1.3.4 |
| 6 | 2026-11-12 | Full audit, 5 lanes: unauthenticated API/WS, entities crash at setup, protobuf/JSON + MAC/hostname wire mismatch, ~25 dead UI actions, unvalidated persistence, storage write per state event, sync OTA hashing | v1.3.5 |

---

## 5. Pending / future work

### High priority
- [ ] Wire up messages (MessageConfig → UI notifications)
- [ ] Config UI for rooms/lights mapping (currently form-based dashboard)
- [ ] Thermostat entity platform (expose thermostats as HA climate entities)
- [ ] Scenes platform (expose scenes as HA scene entities)
- [ ] Relay groups UI (create, edit, delete, add relays)
- [ ] Weather settings save (location, units, interval)

### Medium priority
- [ ] Browser kiosk preview (web app improvements)
- [ ] TFT file upload via UI
- [ ] Firmware upload via UI
- [ ] Panel denied/unblock functionality
- [ ] Relay group light registration (register_as_light)

### Low priority / Phase 2
- [ ] Multi-room panel support (panel.rooms list)
- [ ] Button detached mode entity mapping
- [ ] Outside temperature sensor from HA entities
- [ ] Alarm/weather alerts
- [ ] Energy monitoring
- [ ] Go bridge completion (10/12 stages)

### Known issues to investigate
- [ ] Panel registration requires at least one room (user must create room first)
- [ ] md5 comparison for OTA uses "sonoff" model by default (should use panel.model)
- [ ] Weather polling uses UTC for sunrise/sunset (should use location timezone)
- [ ] _publish_panel_status only updates STOMP, not MQTT (panel status is published by panel itself)

---

## 6. Version history

| Version | Date | Key changes |
|---------|------|-------------|
| v1.0.0 | 2026-11-11 | Initial release |
| v1.1.0 | 2026-11-11 | Full app conversion |
| v1.2.0 | 2026-11-11 | All pages ported, firmware OTA |
| v1.3.0 | 2026-11-12 | Panel header removal, responsive, brand icons |
| v1.3.1 | 2026-11-12 | Full audit fixes (25+ bugs) |
| v1.3.2 | 2026-11-12 | Audit round 2: 18 more bugs fixed |
| v1.3.3 | 2026-11-12 | UI moved to `/nspanel_core/ui` (fixes refresh bounce/blank panel), dynamic version, 40px logo |
| v1.3.4 | 2026-11-12 | Cache-busted panel module + all UI assets (fixes blank panel caused by a 31-day cached panel.js), fixed 4 status components importing hybrids from `/static/...` |
| v1.3.5 | 2026-11-12 | Full-audit remediation: authenticated API + STOMP token + XSS fixes; entities load; topic_safe + accept-to-MAC + STOMP fanout; JSON/hostname wire contract vs field firmware; OTA routes at firmware paths + dead-link/typo cleanup; validated settings, working forms/uploads, storage debounce, OTA hash cache |
| v1.3.6 | 2026-11-12 | OTA consent gate (never flash unaccepted panels) + eval on accept from stored md5s |
| v1.3.7 | 2026-11-12 | Visible HTTP error toasts; proactive HA token refresh |
| v1.3.8 | 2026-11-12 | Manual token override (later reverted in favor of proper login flow) |
| v1.3.9 | 2026-11-12 | Legacy (protobuf) status reports + OTA cooldown |
| v1.3.10 | 2026-11-12 | Login banner for missing sessions |
| v1.3.11 | 2026-11-12 | Diagnostic login banner with recheck |
| v1.3.12 | 2026-11-12 | sessionStorage token lookup (unchecked Remember-me) |
| v1.3.13 | 2026-11-12 | Live-token postMessage path + banner-hide fix |
| v1.3.14 | 2026-11-12 | Fresh 0.1.152 firmware build shipped; auto data-file OTA disabled (wipes remote WiFi) |
| v1.3.15 | 2026-11-12 | Panel setup page + About dialog rebranded to NSPanel Core; rebuilt data fs + merged images |
| v1.3.16 | 2026-11-12 | Fix OTA progress display (manager published "progress", UI read "update_progress" — always blank); verified live render |
| v1.3.36 | 2026-11-13 | Audit repair batches 1+2 + pass-2 deep audit: STOMP await (SEND+last-will+fanout), base.js token scope, save radio/enum/orientation/float fixes, phantom-flag wipe, weather context+knots, reorder/get_ip endpoints, rooms redirects, relay/switch cleanup, modals include, fw 0.1.161 (TFT/ESP OTA robustness, full config guards); sandbox+unit+binary verified |
| v1.3.37 | 2026-11-13 | Fix-them-all: hostname-tracked MQTT routing (rename-proof) + MAC-keyed relay state, relay-as-light platform, detached-light backend wired, thermostat/screensaver-temp dead UI removed, auto-TFT gating toggle, fw 0.1.162 (detached guards, lights page rename) |

---

## 7. How to use this ledger

1. **Before any task**: Write the request in section 2 (or a new subsection)
2. **During work**: Update status as you go (building → done)
3. **After work**: Verify end-to-end, update version, create release
4. **Rules**: Follow section 3 — no exceptions
5. **Audit**: Run full audit after every change
6. **Version**: Follow semver (bug fix = patch, feature = minor, breaking = major)
7. **Never reuse a version number** for different changes
8. **Never skip verification** — if you skip, you audit 100 times
| P33 | FULL AUDIT (user-ordered): integration core, dashboard/UI, STOMP+realtime, ESP firmware, webUI+OTA+delivery, display files — verify every claim, fix confirmed bugs | ✅ Done (batches 1+2 fixed, verified; pass-2 deep audit done, all real finds fixed) |
| P34 | REPAIR ALL (user-ordered): fix every verified audit bug batch 1 integration + batch 2 firmware 0.1.161, then redo audit deeper | ✅ Done — v1.3.36 + fw 0.1.161 published; sandbox + unit + binary verified |
| P35 | FIX THEM ALL (user-ordered): remaining open items — hostname-vs-name topic split, dead controls backend (relay-is-light/detached/thermostat/screensaver-temp), US TFT rebrand, auto-TFT gating | ✅ Done — v1.3.37 + fw 0.1.162; US HMI patched, compile pending editor run |
| P36 | US TFT COMPILE (user-ordered): fix the broken X stack or provision a Windows VM, compile patched US HMI with Nextion Editor, ship gui_us.tft | ✅ Done — NVIDIA EGL root-caused + mesa workaround, compiled 0 errors, verified header, published |
| P37 | EU TFT System Data ERROR (photo): corrupt flash from pre-0.1.161 range bug (model NX4832F035 confirmed correct in editor, EU project landscape); panel on 0.1.162 retrying at progress 0 because bricked display never answers comok — add no-comok recovery fallback (fw 0.1.163 published) | ✅ Done, panel needs one power-cycle then auto-recovers |
| P38 | Panel ignores remote firmware_update (reboot works): ESP OTA task never starts while TFT task runs — recover via power-cycle → register → manual firmware_update push on fresh boot → 0.1.163 → TFT fallback reflash | ✅ Done via manager firmware_install push (0.1.163 live); TFT init answers 0xFF to everything — new prime suspect: corrupt flash reset stored baud to Nextion default 9600, init never tries it |
| P39 | TFT 0xFF-no-answer: add 9600 to init baud rotation (115200→upload→9600, 2 cycles) so a baud-reset bricked display can hear whmi-wris (fw 0.1.164) | ✅ Done — verified rotating in live log, still silent everywhere |
| P40 | Upstream check (user-ordered): Nextion v1.2 spec confirms silence==continue (our ack-strike abort was WRONG, kills healthy uploads); fix streaming to tolerant + baud sweep diagnostic + blind-stream last resort (fw 0.1.166) | ✅ Done — full 16MB streamed, screen unchanged: display hears nothing |
| P41 | Display hears nothing at any baud: whmi-wris-first probe at 6 bauds (fw 0.1.167) | ✅ Done — probe ran silent at all bauds; blind stream completed, screen unchanged |
| P42 | ORIGINAL TFT TEST (user-ordered): serve upstream archive gui.tft (24985602) instead of rebrand to eliminate our file as brick cause; trigger+watch | 🔄 In progress (streaming) |
| P43 | Community research (user-ordered): ESPHome #870/#3082 — blank-TFT recovery, v1.0-vs-v1.2 protocol, power-supply cause; implement v1.0-fallback probe + 3s power-cycle, serve official blank TFT as fast test vehicle (fw 0.1.168) | 🔄 In progress |
| P44 | EXACT-FILE UPLOAD (user-ordered): TFT/firmware/datafile upload dialogs were dead (nothing opened them); wire Actions-menu Upload buttons, pin upload over overlay shadow, record proof metadata, served-file readout in Actions + firmware_status | ✅ Done — v1.3.38 released, unit+render verified |
| P45 | FULL AUDIT NOW (user-ordered): verify every shipped change actually works — imports, handlers, templates, JS, entities, firmware — find and fix anything broken | ✅ Done — found+fixed light-platform setup crash (would brick whole integration on update); 34/34 tests green incl. new regression suite; firmware builds; sandbox clean |
| P46 | UPLOAD-PATH AUDIT (user-ordered): test what the app does with uploaded firmware/TFT/data files — byte-identity, overlay shadowing, cache — fix anything broken | ✅ Done — found+fixed served-file mislabel + overlay shadow for firmware/data uploads; 39/39 tests green |
| P47 | FULL AUDIT ROUND 2 (user-ordered): 360° sweep, 5 parallel audits (manager/STOMP, dashboard/UI, entities, firmware, OTA+delivery+repo) — 19 confirmed bugs fixed: STOMP auth bypass gate, MQTT sub leak on reload, OTA cooldown stamp + startup race, overlay hash stale at boot, firmware/data upload not pinned over overlay, activation re-shadowing custom TFT, non-atomic overlay swap, scene RGB restore, screensaver "global" raw publish, MQTT-config MQTT publish infinite loop, TFT OTA 0x08 misparse + unbounded wait + offset-0 abort, double status publish, remove_panel cache leak, room-sensor wipe on rename, custom-MQTT field wipe, NaN telemetry, temp unit, navbar 401s, dead upload close buttons, rooms N-dup POSTs, repo hygiene (node_modules untracked, stale binaries, hacs version, publish.sh guards, CI workflow) | ✅ Done — 39/39 tests, firmware builds, sandbox 200s/0 errors |
| P48 | UPLOAD MODAL FIXES (user-reported): exclamation mark = empty alert icon (no message); wrong label (Screensaver mode -> TFT file type); file-selected feedback dead (subtext id duplicated with dead modal, drop wrote into file input); dead malformed update_tft_file_modal removed; filename .html -> .text | ✅ Done — v1.3.42, tests 39/39 |
| P49 | UPLOAD 500 BUG (user-reported: Upload goes to settings, nothing happens): startup scheduled async refresh_ota_cache in executor -> _ota_md5 became a coroutine -> every upload 500 "coroutine does not support item assignment"; fix + regression test | ✅ Done — v1.3.43, sandbox POST now 302 + cache dict, 40/40 tests |
| P50 | FULL APP REWRITE (user-ordered): same app rewritten better/optimised/bug-free, upgraded language not downgrade — Go core daemon + thin Python HA shim (ESPHome rejected: throws away rooms/scenes/groups/pinning/STOMP) | 🔄 In progress — topics/pcode/config/ota/manager ported 1:1, go test + vet green |
| P51 | GO CORE MILESTONE 1 (rewrite/): topics(=const.py byte-exact), pcode(=codec.py), config(=models.py tolerant load), ota(=firmware_store atomic+pin, sync-map v1.3.43 lesson), manager(routing/hostname-first/drift/never-auto-data) — 5 pkgs, go test ./... ok, go vet clean, integration untouched | ✅ Done |
| P52 | GO REWRITE MILESTONE 2 (user-approved “Go ahead”): mqttstore (wildcard +/# match, retained replay/delete), stomp (frame codec first-header-wins/content-length + CONNECT-public/SUBSCRIBE-SEND-authed gate), timepub (EU/US + date-format fallback), weather (icons/temp/wind/units/URL/coords) — 9 pkgs go test ok, vet clean | ✅ Done |
| P53 | GO REWRITE MILESTONE 3: ha (WS builders, turn_on payload, brightness/kelvin maps), entities (ingest/publish/relay parse), command (register/set/scene parse, STOMP SEND normalize), cmd/nspanelcore daemon skeleton (config load, SIGUSR1 reload, startup self-check, go build ok) — 12 pkgs green, vet clean | ✅ Done |
| P54 | FINISH THE WHOLE PROCESS: publish (bounded retry 3x/backoff-cap), parity (Go↔Python vectors: topics/OTA/versions/light/commands/STOMP-gate/wildcards/weather/brightness), cmd daemon (config+SIGUSR1+self-check, go build ok), Dockerfile (distroless static) — 14 pkgs test ok, vet+build clean | ✅ Done (code-complete; prod rollout needs HA restart + panel watch) |
| P55 | FULL AUDIT ON NEW GO CODE: attacked all 14 pkgs — FOUND+FIXED 6: (1) ha payload used brightness/kelvin, Python sends brightness_pct/color_temp_kelvin + state follows brightness>0 + hs zero-fill + toggle override [ApplyLightCommand + 5 regression tests]; (2) config lost Python non-zero defaults on old files (port/kelvin-bounds/light type+mode/thermo step/page_type/panel timings/temp-unit) [ApplyDefaults + test]; (3) weather half-away rounding vs Python banker’s at x.5 [roundHalfEven + test]; (4) command dropped string ints (panels send strings) [toInt strings/Number + test]; (5) timepub missing %e/%k/%l/%j verbs [added]; (6) stale fmt import in ha [removed]; edge tests added: negative varint 10B parity, whitespace-hostname→panel, #/+/level matching | ✅ Done — 14 pkgs test ok, vet+build clean |
| P56 | FIRMWARE AUDIT: 5 real finds fixed — F1 UART-mutex tick×ms wait (RX overrun) → pdMS_TO_TICKS(5); F2 0x71 short-read corruption → bounded 7-byte wait; F3 bare-tick vTaskDelay(20) (10× timing error at 100Hz) → pdMS_TO_TICKS(20); F4 zero-tick yield (busy loop at 100Hz) → pdMS_TO_TICKS(1); F5 upload-baud form typo (baud silently read as 0) → renamed both sides + comment typos | ✅ Done — tests/test_firmware_audit.py 6/6 green, esp32dev PlatformIO build SUCCESS, Go fwupdate protocol locks (rotation/neighbors/0x08-offset/chunk) green |
| P57 | TEST RELEASE: rewrite-preview-1 (pre-release, test only) — Go daemon binary attached, integration untouched at v1.3.43, firmware 0.1.170 NOT published (panels unaffected). Smoke-tested: loads config, reports counts, exit 0 | ✅ Done — awaiting user go-ahead for production swap |
| P58 | LIVE APP: cmd/nspanel-live (Go, gorilla WS) ran against production HA WS read-only — authenticated, streamed 70 panel frames/60s with zero publishes. Proved live: KitchenPanel rssi/temp, Dressing Room climate/humidity, conservatory panel uptime/WiFi. Note: this HA does not forward mqtt.subscribe to WS (state_changed stream used); direct-topic branch kept | ✅ Done — binary in rewrite-preview-1, needs rebuild to include live cmd |
| P59 | LIVE DEMO PAGE (user chose option 1, then STOPPED before build) — not built | ❌ Stopped by user |
| P60 | CHECKPOINT RELEASE v1.3.44: cut, pushed, released. Go tests + 21 pytest green. HACS trial ready; revert = redownload v1.3.43 + restart | ✅ Done |
| P61 | REWRITE MUST FIX, NOT COPY: admitted faithful-port gaps, fixed 4 — (1) OTA gating missing entirely (no cooldown/in-flight guard/report aliases → re-trigger loops) [ota_guard + 3 tests]; (2) relay fallback write-only + keyspace mixing [RelayStore typed split + 3 tests]; (3) legacy scene “color” silently lost [NormalizeColorMode + ApplyScene + 3 tests]; (4) remove/rename purge helpers [PurgeMAC/PurgeTopic/PurgeStringMap] | ✅ Done — 15 pkgs green, vet+build clean |
| P62 | ACTIONS AUDIT bit by bit (12/12 traced live in sandbox+browser): WORKING as designed — reboot/Settings/Visit/fw-update/display-update/Flash-all/Restart/uploads-TFT. FIXED 3 audit-misses: (1) Delete bypassed remove_panel — per-MAC relay/telemetry/OTA/listener state leaked on every delete [route now calls remove_panel + purge regression test]; (2) FW/data uploads never pinned over overlay + recorded zero proof (and CLOBBERED the TFT proof with the firmware digest) [per-kind custom_fw/custom_data proof fields, views call note_custom_file, served_firmware_info + firmware_status + Show readout, sandbox-verified 302+proof]; (3) TFT proof clobber (same fix) | ✅ Done — 48/48 pytest green, sandbox live-verified |
| P63 | COMPACT ACTIONS + RELEASE: per-panel OTA merged to one “Update panel” row (ESP\|Display side-by-side, IDs kept for Flash-all); header 3 upload rows merged to one “Upload files” row (Display/ESP/Data!, WiFi-wipe warning kept as tooltip); 48/48 pytest, template-render checks, sandbox 200 smoke | ✅ Done — v1.3.45 |
| P64 | KILL THE REAL BUG: hardware interface VERIFIED against teardowns (Blakadder/ESPHome/Tasmota) — UART RX17/TX16 + GPIO4 T_RST + DRAKJHSUYDGBNCJHGJKSHBDN escape all correct in our firmware; pins are NOT the bug. REAL GAP FOUND+FIXED: (1) 1.2s post-reset settle shouted whmi-wris at a still-booting display → 3s; (2) blind stream 115200-only, unheard by a corrupt-flash display sitting at Nextion default 9600 → silent small-file pass now retries blind at 9600 (16MB exempt, needs USB-TTL); stream loop extracted to testable _streamTFTFile with heard_any tracking | ✅ Done — esp32dev build SUCCESS, 8/8 firmware audit tests, fwupdate green. NOT published — needs user approval (publish auto-flashes panel ESP) |
| P65 | PUBLISH + TAKEOVER: firmware 0.1.170 BUILT+PUBLISHED (manifest verified, evergreen live). ESP 0.1.170 CONFIRMED on panel (web UI). Go daemon nspanel-manage proven on live traffic (raw nspanel/# via message-type subscribe; reboot delivered; register evaluated fw=false correctly on empty served cache — prod runs v1.3.44 without served_firmware endpoint). Panel is updating_tft progress 1% with the NEW recovery code RIGHT NOW — user to check physical screen | ✅ Done (delivery); screen verdict pending user eyes |
| P67 | DISPLAY: ESP 0.1.171 CONFIRMED live on panel (updating_fw 100% seen, web UI proves it). TFT recovery RUNNING monotonically 0→8% under ladder code (no more 0-7% hover/resets) but SLOW (~5min/% — heavy NAKs or slow chunk fetch; full blank ≈ hours). Letting it run; screen verdict still needs user eyes | 🔄 Running |
| P66 | INSTALL-500 ROOT CAUSE (found during P65 delivery): `import nspanel_core` in firmware_store re-pin — dev sys.path artifact, ModuleNotFoundError in prod HA (package is custom_components.nspanel_core), uncaught → 500 on every install while a TFT pinned. Fixed via package __file__ + extracted maybe_repin_custom_tft + repo-wide import guard + functional tests | ✅ Done — 54/54 green |
| P68 | “NOT REGISTERED” IN HA APP: _handle_register_request published awaiting_accept UNCONDITIONALLY — every reboot re-branded the accepted panel (template had no branch → “Unknown state awaiting_accept!” alarm). Fixed: re-register asserts real state (online/awaiting); template shows “Waiting for acceptance” for genuinely new panels | ✅ Done — 56/56 green, sandbox 200, v1.3.47 |
| P69 | ONLINE SOLUTION SEARCH (user-ordered): Blackymas issue #2929 = IDENTICAL symptoms (TFT stuck partial %, System Data ERROR, blank also fails) — RESOLVED by FULL mains power-down, not GPIO4 soft power-cycle: “power went out… tried again… successfully uploaded (3 attempts)”. Also jirkovynavody: erase-flash fixes stuck panel. Action: user cuts 230V at the wall 60s, panel reboots, auto-retries TFT from cold display | 🔄 Waiting for user power-cycle |
| P70 | VERDICT REACHED (full evidence chain): display FLASH WRITE is dead — at 9600 (most tolerant baud, talk==param, cold-booted display, community-proven file) the display accepts ~1 block then re-requests it forever (progress pinned 0-1%, 540s). Short frames WORK (progress bar renders = display CPU alive + command received), bulk commit fails at every baud (115200/57600/9600), both protocols (v1.0+v1.2), warm and cold, proven file. Conclusion: display module flash chip failed; no baud/file/protocol/ESP fix can commit bytes. Remaining: USB-TTL direct to TF_RX/TF_TX pads (isolates module; Nextion Editor verdict) or replace NX4832F035 module (~$30 Itead). Panel relays/sensors still fully functional | ✅ Diagnosis complete |
| P71 | DISPLAY FIXED BY USER (upstream test vindicated): upstream app flashed the display SUCCESSFULLY at 921600/p1.2 — display hardware fine. My P70 “flash chip dead” verdict was WRONG. Real culprit: OUR ESP firmware TFT streaming (NSPanel.cpp) desyncs from the display. Panel now runs upstream software, user set 115200, working | ✅ User resolved |
| P72 | DELETE/DENY BUGS (user-found, “is not working!!!”): v1.3.48 shipped a 500-broken Denied page (dropped local asdict import → NameError on every visit — the deny flow was unusable in production; my earlier sandbox check tested the grid but never opened the Denied page). FIXED + FULLY LIVE-TESTED end-to-end with a real panel registering every 3s: delete → row gone, MAC ignored, stays deleted through 20s+ of live registers, visible under “Deleted panels” with Allow again (verified round-trip: allow → re-registers fresh); deny → row off main grid, on Denied page with Unblock, holds through repeated registers; denied page renders 200. 60/60 tests green | ✅ Done — v1.3.49 |
| P73 | VENV COMPARISON (user-ordered): cloned NSPanelManager-firmware (true upstream of our ESP fw) and diffed the whole TFT path — _readDataToString identical; 5 divergences found, ROOT CAUSE = per-block response window 500ms (ours) vs 5000ms (upstream): a late 0x08 retransmit request is missed → stream diverges → garbage flash → System Data ERROR. Plus offset-0 rewind (upstream ignores), abort-on-incomplete-0x08, 20-try chunk abort, blind ladder (all ours, all divergence amplifiers). Lower baud = worse (slower replies). Full report: /tmp/opencode/fw-compare/FINDINGS.md. Fix = restore upstream semantics; NOT applied yet | 🔄 Awaiting approval |
| P74 | FIRMWARE REPAIRED (user-ordered “repair then port”): 0.1.172 restores ALL five upstream semantics in _initTFTUpdate/_streamTFTFile — 5000ms window, 0x08 honored with offset-0 ignored (no rewind), unbounded offset wait + infinite chunk retry (no attempt aborts), init recurses the two bauds until comok (no cap, no blind ladder, no probes), upstream escape settle restored. Old blind/probe helpers deleted. 11/11 fw audit tests, 59/59 pytest, Go mirror updated (ResponseWindowMs/ShouldJump), esp32dev build SUCCESS, PUBLISHED to evergreen (md5 a1a982fd) | ✅ Done — port sequence next: needs old NSPanel Manager (port 8000) stopped to win the accept race |
| RULE-R1 | HIGH PRIORITY RULE (user-ordered): everything implemented/changed must be properly tested (unit + end-to-end on every touched user-facing path) BEFORE any release. Violations: v1.3.48 (denied page 500) | 📌 Permanent rule |
| P75 | BUTTONS-DEAD ROOT CAUSE (user-reported: “delete/deny does nothing” — v1.3.41 repo hygiene dropped tracked node_modules → htmx.min.js AND hybrids ES module 404 in the browser since then: EVERY hx-post/hx-delete button dead, all live status widgets broken; API worked, browser didn’t — why all browser-facing audits missed it). FIX: vendored htmx 1.9.12 → static/htmx.min.js, hybrids 9.1.5 src → static/vendor/hybrids/src/, all 11 template refs updated, node_modules refs deleted, missing HMI example images restored from upstream. RULE R1 verification: all static refs 200, Playwright on real UI: htmx LOADED, Deny click → POST with Bearer → 200 → panel leaves grid → on Denied page, zero pageerrors; 60/60 pytest | ✅ Done — v1.3.50 |
| P76 | QUEUED (user-ordered, do later): full button audit for the P75 failure class — EVERY button/control in the UI checked for silently-dead handlers (missing static assets, unloaded libs, dead JS bindings, no-op onclick). Method: inventory all clickables, verify each fires its request with auth in a real browser (Playwright), fix+regress. Do NOT start without user go-ahead | ⏳ Queued |
| P77 | HACS INSTALL FAILURE (user-reported): my HMI restore copied 8 FULL gui.tft files (52MB) into ui/static. FIXED per user order WITHOUT version bump: v1.3.51 release+tag deleted, tree fixed, v1.3.50 re-released on fixed code (explicit user-ordered exception to the never-reuse-a-version rule). Install 1.3.50 fresh | ✅ Done |
| P78 | PANEL REVIVAL — HOW THE USER DID IT (user-ordered correction: P71 recorded the outcome, not the method): (1) user proposed the test themselves (“i want to try something, but you have to update esp with upstream firmware”); (2) agent downloaded stock upstream ESP firmware.bin (1,718,432 bytes, md5 9badd2d0d7cf1b851615f098340c8aae) + data_file.bin from NSPanelManager/docker/web/nspanelmanager/firmware/sonoff/; (3) first upload crashed the integration (HTTP 500, UI dead, restart attempt 502); (4) USER re-enabled the integration themselves (“ok... i sill enable it”); (5) re-upload succeeded (302, served checksum = upstream md5), force-flash via panel/1/update_firmware → 200; (6) the upstream app then flashed the DISPLAY at 921600 baud upload, protocol v1.2; (7) panel came online working with the upstream software, display alive — user set 115200 afterwards; (8) user’s verdict, later confirmed by the P73 code diff: our ESP+TFT firmware was the fault, not hardware — P70 retraction stands | ✅ Done (record only; no code change) |
| RULE-R2 | HIGH PRIORITY RULE (user-ordered): BEFORE starting any given task, go through the ledger and check the info already known. If something contradicts known info, STOP and tell the user before doing anything. No exceptions | 📌 Permanent rule |
| RULE-R3 | HIGH PRIORITY RULE (user-ordered): ANSWER EVERYTHING THE USER ASKS — every point, every question in a message gets an answer. Never cherry-pick; if something cannot be answered yet, say so explicitly | 📌 Permanent rule |
| RULE-R4 | HIGH PRIORITY RULE (user-ordered): FINISH EVERY REQUEST unless user says STOP/PAUSE. "Add to queue" = log to ledger AND CONTINUE in-progress work — queued is not paused. Backgrounded waits don't end the request: pre-validate meanwhile, resume on notification | 📌 Permanent rule |
| P79 | BAUD VERDICT (user asked: 1 baud vs 2 — “same baud for both, no 2 tabs”): keep TWO phases, ONE user setting. Reasoning: the bug was never the count, it was talk≠param divergence (0.1.171 blind path). Discovery (unknown bricked-display baud) inherently needs >1 attempt baud; transfer needs the fast one. 0.1.172 already implements the synthesis: single upload-baud setting, handshake always 115200 first then configured, talk==param enforced structurally at every step. No second UI tab needed. PROOF LIVE: rebrand streaming 0→26%+ monotonic at 921600 with 5000ms windows, no resets | ✅ Design locked (no code change needed) |
| P80 | SINGLE-BAUD FIRMWARE (user-proven: upstream flash that revived the panel ran both phases at one rate; “no 2 tabs”) — ONE configured baud (`tft_upload_baud`, default 115200) now drives init Serial2.begin, handshake, whmi-wris param and streaming via single `_tftBaud()` helper: talk==param by construction, 0.1.171 divergence class impossible. Removed: init baud param, two-baud retry alternation, pre-stream baud-switch block. Kept: 5000ms window, offset-0 ignore, unbounded 0x08 wait, infinite chunk retry, upstream escape settle. Version header 0.1.173 (NOT published — panel untouched per user order). esp32 image SUCCESS, 11/11→12/12 fw audit tests (incl. new single-baud rule test), 60/60 pytest, Go SingleBaud mirror+test, full suite green | ✅ Done (local only; panel untouched) |
| P81 | REBRAND FLASH OUTCOME: streamed monotonically to 73% at 921600 with repaired protocol (no rewinds — 5000ms fix held), then ended; panel now reports warnings:"No response from the display" (_display_ready=false), idle 191-byte reports, screen per user = bricked again. Rebrand file remains unproven past 73%; blank (proven) untouched by this attempt. Next ONLY on user order: (a) upstream-app blank reflash (proven recovery path), or (b) offline rebrand-vs-upstream byte-region diff | ⏳ Awaiting user decision; panel untouched |
| P82 | REBRAND vs UPSTREAM COMPARISON (user-ordered “proper check, then update both if clear”): block-entropy structural scan ours-vs-upstream across 73%-region shows same uncompressed-structured profile, no corrupt/zeroed blocks — files analogous, rebrand unproven on HW only. Byte-23 header field differs (ours 0002/9af7 vs 0001/9afc in upstream+blackymas+blank) — consistent with rebrand resource-count change, meaning unverified. SAFETY FIRST: auto-TFT turned OFF via minimal save_settings POST (verified False checked) so no auto-flash can collide with user upstream reflash; manual push path unaffected. Served EU TFT remains our rebrand (233cbc92, 16MB), served ESP 0.1.172 (a1a982fd) | ✅ Done — awaiting user upstream flash + verdict |
| P83 | PUSH 0.1.173 (user-ordered “push the latest esp firmware”): R2 pre-checks passed — panel online+idle on our 0.1.172 (no TFT in flight, safe window), KitchenPanel id 4, served ESP already staged? No — rebuilt fresh from tree (md5 6a22b769), published to evergreen (manifest 0.1.173 verified), pushed via panel/4/update_firmware (HTTP 200). Single-baud firmware now live-flashing; watching for updating_fw → re-register on 0.1.173. auto-TFT stays OFF; no TFT action until user orders | 🔄 Watching |
| P84 | RECOVERY FLASH: blank TFT completed 100% (monotonic progress, no stalls — single-baud 0.1.173 + 921600 verified end-to-end on real hardware). Display ALIVE on blank UI. Panel on 0.1.173, re-registered clean, auto-TFT still OFF. The 0.1.171 divergence bug is closed for real this time: the failure was never the wire or the file, it was our talk≠param + 500ms-window protocol | ✅ Done — display recovered |
| P85 | TWO-PHASE BAUD, ONE SETTING (user: “same baud for both — no 2 tabs”): comm+handshake hardcoded 115200 (HMI default); single _tftBaud() used ONLY for whmi param + post-accept switch — talk==param at every step, no second UI field. Also corrects my P80 overreach (single-baud-everywhere would have broken normal HMI comms whenever they differed). esp32dev SUCCESS, 12/12 fw audit tests, 60/60 pytest, Go mirror updated (CommBaud/UploadBaud). Local build only — panel untouched, nothing published | ✅ Done |
| P86 | TWO-PHASE BAUD, ONE SETTING (user: “same baud for both — no 2 tabs”; verified against upstream behavior): fixed 115200 for init + handshake + normal comms; single _tftBaud() used ONLY for whmi-wris param + post-accept Serial2 switch. Corrects my P85 overreach (single-baud-everywhere would have broken normal HMI comms). Matches upstream ESPHome pattern (115200 talk, fast-baud flash, back to 115200 after reboot — which happens naturally via init). Bumped to 0.1.174, esp32dev SUCCESS, 12/12 fw audit tests, 60/60 pytest, Go CommBaud/UploadBaud already matched (no change needed). Local build ONLY — NOT published, panel untouched | ✅ Done |
| P85 | REBRAND RE-PUSH (user-ordered): verified served EU TFT is our rebrand 233cbc92 (16MB), panel idle (no updating_tft in 45s traffic), KitchenPanel id 4 accepted; fired POST /api/panel/4/update_tft (200). Watching progress | 🔄 In progress |
| P87 | FULL GUI REDESIGN (user-ordered): new dark UI for the panel display — new style/layout, compact+organised, NSPanel Core branded in logo colours (bg ~(13,16,22), accent #39C8E8 cyan, teal secondary, light-grey text), no useless text. Inventory: brand pipeline exists (logo/splash/HMI-pictures/fonts scripts), NO editable .HMI source in repo (compiled gui.tft only; nextion-hmi-format is read-only by design) → real build needs Nextion Editor under Wine (prefix currently empty). Awaiting: (1) design approval, (2) explicit go to install Wine+Nextion toolchain | ⏳ Queued for approval |
| P88 | ESP WEB UI REWRITE (user-ordered; CORRECTED scope: panel-hosted setup page, not the Nextion TFT): full rework of firmware/data/index.html + main.css — compact single-column cards, dark-first NSPanel Core branding (bg #0d1016, cyan #39c8e8), no useless text. FIXED while here: duplicate element id (popup-modal/not_connected_modal), duplicate value attr on legacy radio, " 0" log-level value, dead doConnectionCheck flag (now a real 5s HEAD poller), dead reboot.js deleted (referenced nonexistent /connection_test + missing jQuery), empty tbody gets proper empty-state row. KEPT intact: all 10 form field names, all 12 %template% placeholders, all JS element IDs, /available_wifi_networks + /do_reboot + /factory_reset endpoints. Contract verified by script + real Chromium render+screenshots (dark+light, zero JS errors). Compact v2 (user-ordered no-scroll rearrange): horizontal label+input rows, slim one-line header, set-and-forget items moved into collapsible Advanced details (log level, upload protocol+baud, factory reset), sticky Save/Reboot action bar. Collapsed page height 900px at 414px wide = no scroll. BUG FOUND+FIXED during verify: theme init used classList.add only so light theme never applied — now calls nspanel_apply_theme(is_dark) both directions, verified dark/light/toggle in Chromium with zero JS errors; form POST serializes all 10 fields. Guards: W1–W5 + 24KB layout budget in tests/test_firmware_audit.py. 66/66 pytest + Go test/vet green. Data dir 57KB→20KB. NOT DEPLOYED anywhere. Live preview (verified rendering, zero JS errors): https://alexxbody.github.io/NSPanelCore/ | 🔄 In review |
| P89 | DEPLOY COMPACT WEB UI v2 (user-approved "proceed"): publish ESP 0.1.174 (two-phase baud P85/P86 + rewritten compact page P88). PRE-FLIGHT READ-ONLY CHECK (nspanel-live 90s WS watch, 19:37 UTC): KitchenPanel STILL in updating_tft, progress FROZEN at 87% across all reports (ESP alive: temp 26.1C, rssi ~-63, heap 50%, ip .23, panel web UI 200). TFT stream STALLED, not complete. Consequence: firmware/data OTA trigger is DEFERRED — manager auto-skips updating panels, so publish itself is panel-safe, but no ESP OTA will (or must) fire until TFT resolves. Plan: build bins locally + publish.sh 0.1.174 (no panel contact) → full test suite → commit. Panel OTA trigger only after user screen verdict on TFT. | ✅ Published 0.1.174 (evergreen, all 6 assets re-download-verified, manifest on main). 66/66 pytest + 15 Go pkgs + vet green. OTA trigger still DEFERRED — panel frozen at updating_tft 87%. |
| P90 | TFT DONE BUT SAME ERROR (user report — INVESTIGATED via panel settings logs, i.e. STOMP log_backlog, 50 entries): ESP side HEALTHY (WiFi/IP .23, config downloads from our /api/get_nspanel_config, sensors fresh 19:43-19:46 UTC). Display side DEAD: repeated "Failed to initiate NSPanel" (main.cpp:372, nspanel.init false) + getComponentIntVal no-response — display never answers "connect" after GPIO4 power-cycle, exactly matching a Nextion stuck on System Data ERROR. Verdict: byte-stream reached 100% but bytes-sent!=bytes-written, so the display holds a garbled/partial image. Two side-notes: (1) no "TFT successful/failed" line survives in the 50-entry window (rolled out); (2) 17:56 UTC external failed-auth probe from 37.235.122.35 to /nspanel_core/firmware_status (curl) — blocked, no access. Next options: re-push rebrand TFT (now under 0.1.174 two-phase uploader once ESP auto-updates), or blank.tft recovery first. Awaiting user screen verdict/decision. | ⏳ Awaiting user decision |
| P91 | APP LIVE LOG HAS NO TIMESTAMPS (user-ordered, queued): panel settings log page shows blank time on every line. Root-caused (not fixed): firmware MqttLog::logToMqtt builds "MAC;LEVEL; file:line f(func) msg" with no timestamp field (firmware/lib/MqttLog/MqttLog.hpp), and integration _on_panel_log (manager.py) parses into {"time": "", ...} without ever stamping receipt time — verified live, all 50 backlog entries have "time": "". Fix options: (a) stamp time on receipt HA-side (no flash needed, arrival time), (b) add millis() in firmware (needs ESP OTA; uptime-only, no wall clock). | ⏳ Queued |
| P92 | RE-PUSH REBRAND TFT (user-ordered "do (1)"): panel auto-updates ESP to 0.1.174 first (two-phase uploader), then re-trigger update_tft and monitor to 100%. Rule restated by user: queued items are logged AND work continues — every request runs to completion unless user says stop/pause. | 🔄 In progress — ESP-update watch |
