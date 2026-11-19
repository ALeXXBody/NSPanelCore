# NSPanel Core — "Build the screensaver" tab (full clock/date styling + weather) — Blueprint

Target: **app v0.2.7** (new minor, distinct from the pending `app-v0.2.6_4` hotfix that carries the pages-wording and blank-hardware-tabs repairs).
Status: **PLANNED — no code, no carriers, no release touched.**

## Objective

Add a third top-level Dashboard studio tab, **"Build the screensaver"**, that gives full style control over the panel's clock and date (size, weight/shape, colour, alignment) and adds weather details to the screensaver (outside temperature, room temperature, forecast, wind, rain, sunrise/sunset), with per-panel HA entity binding for the temperature sources. Everything must be live on the **native ESP-IDF firmware** the user's panels actually run (currently `0.1.13`), and visible in the studio's live preview.

## Locked decisions (user, 2026-11-19)

1. **Clock/date: full style control** — font/size, bold/weight, colour, alignment; not just format toggles.
2. **Weather: all of the above** — show/hide toggles for each detail, per-panel HA sensor binding for outside + room temperature, and native-firmware rendering (the legacy Arduino track is *not* the target).
3. **Version: 0.2.7** — a fresh minor bump of the integration carriers; firmware gets its own sequential bump (next after `0.1.13` → `0.1.14`) because firmware code changes.
4. The two pending repairs (PAGES wording; Panel-hardware sub-tabs) ship first as the `app-v0.2.6_4` hotfix, **on explicit go**, before 0.2.7 work is released.
5. No HA install/restart/config/state actions by the agent; the user handles HACS/Marketplace updates and HA restarts. No power cycling proposed.

## Standing rules (LEDGER — binding)

- Check `LEDGER.md` before and after every step; log every task and decision.
- No code ships without tests; new views/flows ship with tests in the same commit.
- Prove work by **executing real JS/DOM** (jsdom harnesses against HTML rendered by the real views), not by reading source.
- Changelogs say only what changed + install steps (no non-changes, test counts, verification, release mechanics) — P300.
- Releases only on explicit go; forward-only, no gaps/jumps/reuse/force-move; same-version hotfixes use suffixes.
- Carriers (`manifest.json`, `hacs.json`) bump together in the same commit (P228), except hotfixes (P296).

## Current-state facts (verified 2026-11-19; paths/line numbers at current HEAD `bb6f1f1`)

### The panels / firmware
- Panels run the **native ESP-IDF** track: `firmware-native/`, `src/protocol.h:10` `FW_VERSION "0.1.13"`. The Arduino `firmware/` track (`0.0.2`) is not deployed. The ledger's fw release sequence (P230–P280) is this native track.
- Native MQTT subscription set: `firmware-native/src/mqtt.cpp:26-33` — panel command topic, `TOPIC_MANAGER_COMMAND`, `nspanel/status/time`, `/date`, `/ampm`, relay commands. **`TOPIC_STATUS_WEATHER` is defined (`protocol.h:39`) but never subscribed or used.**
- Native clock/date writes: `firmware-native/src/display.cpp:198-211` (`nsp_display_set_clock/date/ampm`) → `screensaver.curTime` / `curDay` / `curAMPM` on both `screensaver` and `mini` pages, via `nsp_display_set_text()` (`display.cpp:181-196`, whitelist-sanitises to 24 chars, emits `object.txt="…"`).
- Native firmware **does not fetch/parse the server's `/api/get_nspanel_config` JSON** — that is the Arduino path. Settings reach the native panel only via MQTT.
- Panel's own NTC temperature is read (`temp_math.cpp`, `nsp_temperature()`) and reported in the status report (`mqtt.cpp:235-244`) but is **not** drawn on the screensaver.
- Hand-rolled JSON helpers exist and are host-tested: `json_string()` in `dash_cmd.cpp:27`, `nsp_json_command()` in `mqtt.cpp:121` — reuse this style for weather parsing; no third-party JSON lib needed.

### The display image (HMI kit)
- `custom_components/nspanel_core/hmi_kit/fonts/` contains **only** `NotoSans24.zi` and `NotoSans64.zi`.
- `hmi_kit/app.toml:44-47` lists those two fonts; `hmi_kit/pages/screensaver.page.toml` has only `bg`, `curTime` (64px, `#c8cbce`), `curDay` (24px, `#8b93a1`), `curAMPM` (24px, `#39c8e8`), `wake` hotspot — **no weather components at all**. `mini.page.toml` is the clock/date-only minimal variant.
- `hmi_generate.py` copies fonts verbatim (`generate_source`, ~line 121) and **hardcodes** the two font names into generated `app.toml` (~lines 93-97) — that hardcode must become data-driven.
- `defaults.toml:1018-1052` documents the runtime-settable text attributes: `font`, `pco`, `bco`, `xcen`, `ycen`, `sta`, `pw`, `x/y/w/h`. Colour/alignment/weight are runtime-settable via Nextion commands; **glyph size is not — it requires more compiled `.zi` fonts.**
- TFT delivery is decoupled from firmware flashing (P251 rule B): a TFT-only change carries the binary over untouched; a firmware-code change requires a fw bump.

### Integration side
- Weather already polled and published: `manager.py:_poll_weather()` 2124-2243 → retained `nspanel/status/weather` JSON `{icon,temp,wind,sunrise,sunset,maxmin,prepro,forecast[5]}`; HA outside-temp override at 2203-2214 via `GlobalSettings.outside_temp_sensor_entity`.
- Time/date published: `manager.py:_publish_time()` 2297-2316 → `nspanel/status/time|date|ampm`.
- Per-panel settings: `models.py:PanelConfig` 139-233 (screensaver mode/timeout/dim/calibration, `inside_temperature_sensor_topic` 191, `temperature_unit` 190); `RoomConfig.temp_sensor_entity` 92.
- Panel-settings form: `_panel_settings_fields.html` `[data-section="screen"]` 576-645; studio loads it via `DashboardPanelSettingsView` (`dashboard.py:702-724`) and `loadPanelSettings()` in `dashboard.html:827-866`.
- Save path: `SavePanelSettingsView` 727-858 (`field_map` 743-763, bool parsing 781-797, screensaver validation 804-809); note the warning at 798-800 about not writing bools that have no form control.
- Studio tabs: `dashboard.html` 242-245 (`.studio-tab`, only "Build the dashboard" / "Panel hardware"), `setTab()` 330-336 derives pane id as `pane_` + `data-tab`; preview clock `tickClock()` 1028-1039; screensaver preview `#pvs_clock`/`#pvs_date` 213-214.
- Routes registered in `dashboard.py`; views use the `@_gated` auth decorator.

## Step 0 — Wire contract + data model (foundation)

**Context:** Define the exact MQTT payload and persisted fields first; everything else depends on this shape. No UI/firmware work yet.

- Add to `PanelConfig` (`models.py`): `clock_style` fields (font key, bold, colour, alignment for clock and date — use small string enums with safe defaults), `screensaver_weather` show/hide flags (outside temp, room temp, forecast, wind, rain, sunrise/sunset), and per-panel HA entity overrides (`outside_temp_sensor_entity`, `room_temp_sensor_entity`).
- Define a single canonical payload builder in `manager.py`, e.g. `_panel_screensaver_config(panel, settings) -> dict`, emitting style + weather flags + resolved entity ids. Publish it retained to a new per-panel topic `nspanel/<hostname>/screensaver` (add the helper to `protocol.h` and freeze it in `tests/test_detach_contract.py`).
- Publish on: panel save, register, and settings change (mirror `_publish_time` cadence where useful).
- Tests: model round-trip/defaults; payload builder exact keys and resolved HA entities; contract test for the new topic helper.

**Verify:** `pytest tests/test_detach_contract.py tests/test_models*.py -q` green; no existing topic contract broken.
**Exit:** payload shape frozen and tested; no UI/firmware changes yet.

## Step 1 — Font assets + HMI components (TFT layout)

**Context:** The panel can only draw what is compiled into its TFT. This is the highest-risk step; resolve the font question first.

- Provide a small set of real `.zi` fonts for size/weight choice (e.g. 24/32/48 regular + a bold variant). Font generation is achievable without the Nextion Editor via `stg/nextion_zi_font_tools` (reads/writes `.zi`, converts BMFont output) — use a BMFont generator over the Noto TTF already implied by the kit, and add a repeatable `scripts/make_screensaver_fonts.py` so the assets are reproducible. **Risk gate:** verify each generated `.zi` compiles in a real nxwright build before exposing it; if generation fails, fall back to the two existing fonts as "small"/"large" and document the limit honestly — never claim a size the panel cannot render.
- Make `hmi_generate.py` read the font list from the kit instead of hardcoding it, and add weather components to `screensaver.page.toml` (+ `mini.page.toml` where appropriate): current icon/temp/wind/maxmin, room temp, sunrise/sunset, and forecast rows sized to fit a 480×320 layout without covering the clock/date.
- Keep component names in sync with `TftDefines.h`-style constants used by native firmware; add a generator test that compiles a real per-panel TFT and asserts the new components/fonts are present.

**Verify:** `pytest tests/test_hmi_generate*.py -q` incl. a real nxwright compile; TFT size/md5 recorded; clock/date components unchanged in id/order so wake logic survives.
**Exit:** a fresh generated TFT visibly contains selectable fonts and weather slots.

## Step 2 — Native firmware: weather + style commands (fw 0.1.14)

**Context:** Native firmware must subscribe to the new payload and to the already-published weather topic, then write attributes to the compiled components.

- In `mqtt.cpp`: subscribe `nspanel/status/weather` and the new `nspanel/<hostname>/screensaver` topic; dispatch to new pure, host-testable handlers.
- Add `screensaver_style` parsing → write `screensaver.curTime.font/pco/bco/xcen/ycen/sta` and the same for `curDay`/`curAMPM` on both pages, using the existing `nsp_display_set_text()` command path. Values must be whitelisted/clamped (font ids, 6-digit hex colours, alignment ints) — never pass raw payload into a display command.
- Add weather JSON parsing (reuse `json_string`-style helpers) → write `curTemp`, `curIcon`, `curWind`, `curMaxmin`, `curRain`, `curSunrise`, `curSunset`, room temp, and forecast rows, honouring the show/hide flags. Sanitise every string to the component's 24-char limit.
- Respect `no_screensaver` mode already sent by the manager (`_publish_time` 2321-2333) so weather writes do not wake a dark screen.
- Bump `FW_VERSION` in `protocol.h` to 0.1.14 and follow rule B (firmware code changed → binary rebuilt + TFT regenerated).
- Host tests: style command parsing/sanitisation, weather JSON parsing, display-command emission, both with adversarial payloads.

**Verify:** `bash firmware-native/tests/run_host_tests.sh` → `ALL PASSED`; version carriers truthful; no raw payload reaches the UART command.
**Exit:** firmware can render the full style + weather set; tests green.

## Step 3 — Integration endpoints + publish-on-save

**Context:** The studio needs GET/POST endpoints for the new tab and must publish changes to the panel.

- New view pair in `dashboard.py`: `GET /dashboard/screensaver_settings?panel_id=` (renders a new partial) and `POST /api/screensaver_save/{panel_id}`, both with `@_gated` and the same defensive `studioJson` transport used elsewhere.
- New partial `_screensaver_fields.html`: style controls (font/size, bold, colour, alignment for clock + date), weather show/hide toggles, and HA entity pickers for outside + room temperature, fed from the same entity source as the studio's item cells.
- Extend `_panel_settings_context()` with the new fields and entity lists; extend `SavePanelSettingsView`-style parsing (typed, enum-validated, no accidental bool wipes) in the new save view; call `_panel_screensaver_config()` publish after save.
- Tests: real-view GET renders the partial with real values; POST parses/validates and publishes; invalid enum → 422; auth gate behaves like the other studio endpoints.

**Verify:** `pytest tests/ -q` green (new tests included); Jinja parse OK.
**Exit:** the new tab's data round-trips through real views and reaches the panel payload.

## Step 4 — Studio tab + live preview

**Context:** The visible feature the user asked for. Add the third top-level tab and make the preview show the styling/weather immediately.

- In `dashboard.html`: add `.studio-tab[data-tab="screensaver"]` and `#pane_screensaver`; `setTab()` already derives the pane id, but add the on-demand settings load like the Panel tab has. Keep PAGES terminology (no "room" word).
- Move/copy the screensaver picture picker context into this tab if it helps the flow, but do not remove the working picker from step 1 without an equivalent (P305 regression guards).
- `loadScreensaverSettings()` injects the partial, binds behaviour, and `saveScreensaverSettings()` posts it; both use `nspanelFetch`/`studioJson`.
- Live preview: make `#pvs_clock` / `#pvs_date` reflect the chosen font/weight/colour/alignment via inline CSS, and render a weather strip in `#pvs_scr` from the chosen toggles/entities, so changes are visible before saving.
- Tests: real-DOM harness (real inline JS + real rendered partial + real jQuery + panel_settings.js) — tab switching, controls present, preview updates, save payload correct, zero JS/jsdom errors.

**Verify:** harness output captured; `pytest tests/test_dashboard_screensaver*.py -q` green; Jinja parse OK.
**Exit:** the new tab is usable end-to-end in the real page, with a truthful live preview.

## Step 5 — Full-stack proof + regression sweep

- One integrated real-DOM run covering: tab → change style → preview updates → save → payload published → panel-side handler parses it (firmware host test consumes the same payload fixture).
- Full suites: `pytest tests/ -q` (expect ≥238 + new tests); firmware host suite `ALL PASSED`; real nxwright compile; Jinja parse.
- Adversarial checks: no "room" word in `dashboard.html`; no raw payload into display commands; no version carrier bumped prematurely.

**Verify:** all green, evidence appended to `LEDGER.md`.
**Exit:** feature complete in source, unreleased.

## Step 6 — Version + release (USER GATE — explicit go required)

- Before any release: publish `app-v0.2.6_4` (the two pending repairs), per the suffix rule, forward-only, base tags untouched.
- Then bump integration carriers to `0.2.7` in one commit; bump firmware carriers to `0.1.14`; create sequential tags + GitHub Releases; changelog says only what changed + install steps (P300).
- Verify both the tag tree **and** the Releases API show the new version first (P294); carriers truthful; no HA install/restart/config/state actions by the agent.

**Exit:** released only after the user's go; proof logged in `LEDGER.md`.

## Dependency graph / parallelism

```
Step 0 (contract+model)
   ├── Step 1 (fonts+HMI) ──┐
   └── Step 3 (endpoints)   │
                            ├── Step 2 (firmware) ──┐
Step 3 ─────────────────────┴───────────────────────├── Step 4 (studio tab)
                                                    └── Step 5 (proof)
                                                          └── Step 6 (release, gated)
```
Steps 1 and 2 can be parallelised after Step 0; Step 3 is independent of 1/2; Step 4 needs 1+3 (and 2 for truthful preview); Step 5 needs all; Step 6 is always gated.

## Rollback

- Every step is a separate commit; revert only that commit. No tag/force-move.
- Font/HMI step: keep the old `.zi` files and page TOMLs; generator test compares against the pre-change compile.
- If font generation fails the risk gate, ship the two existing fonts as small/large rather than fabricating a size option.
