# NSPanel Core: Detach-from-Upstream + Optimized Recreation — Blueprint

## Objective
Recreate the NSPanel Core stack (HA integration + ESP32 firmware + TFT HMI)
as a native, upstream-independent codebase with everything optimized —
keeping every proven behavior (R1-tested), dropping every upstream-inherited
liability documented in LEDGER P37–P107.

## Non-negotiables (from standing rules)
- R1: every step ships with unit + end-to-end tests green before release.
- R2: check LEDGER before each step; stop on contradiction.
- R3: answer everything; say what can't be answered.
- R4: finish every request; queue = log + continue.

## Step 0 — Scope decision (USER GATE, no code)
- Q1: wire protocol — KEEP MQTT/protobuf topics (recommended: field panels
  keep working, zero reflash risk) vs BREAK (clean-sheet protocol, needs
  coordinated ESP+integration flash, orphans old panels).
- Q2: HMI — adopt official nxwright source workflow (proven P97) vs keep
  Editor-built blobs.
- Q3: Go rewrite — promote `rewrite/nspanelcore` to the ship vehicle vs keep
  as mirror.
- Default recommendation: KEEP protocol, nxwright HMI, Go stays mirror
  until integration is clean. Record decision in LEDGER before Step 1.

## Step 1 — Evidence inventory (cold-start safe)
- Catalog every upstream-derived module + the liability it carries
  (protocol codec, TFT uploader, Django-ported UI, HMI blobs, baud logic).
- Output: `docs/detach-inventory.md` with keep/rewrite/drop per module.
- Verify: `pytest tests/ -q` green before touching anything (baseline).

## Step 2 — Contract freeze (the anti-regression net)
- Lock behavior contracts: MQTT topic matrix, OTA flows, UI routes, template
  vars, panel web UI fields (extend W1–W7 + P76 audit into a contract suite).
- New: `tests/test_detach_contract.py` — fails on ANY behavior drift.
- Verify: full suite green; Playwright page-load sweep 200s.

## Step 3 — Integration rewrite (native, no Django-isms)
- Rewrite `custom_components/nspanel_core` module by module against the
  frozen contracts: manager, dashboard/views, firmware_store, STOMP bridge,
  platforms. Kill: overlay/shadowing complexity, in-memory-only backlogs,
  unauthed views, blocking calls in event loop, log-spam warnings.
- Keep: evergreen publish flow, HACS release flow (RELEASING.md).
- Verify: contract suite + P76 audit script clean + HA restart test.

## Step 4 — ESP firmware rewrite (native, protocol-compatible)
- Rewrite `firmware/` against the same wire contract: WebManager, MqttLog,
  NSPanel (uploader with P103/P104 guards baked in, not bolted on),
  single-baud model, LittleFS data fs.
- Delete: legacy fallbacks that no panel uses (prove unused first).
- Verify: pio builds esp32dev+sonoff, audit suite green, panel OTA
  to a test build, 100% TFT flash + boot on the bench panel.

## Step 5 — HMI native source (nxwright-first)
- Rebuild the display UI as nxwright text source in-repo
  (`hmi/rebrand/`), no binary blobs: pages/components/fonts/pictures
  versioned as text + assets. CI compiles to .tft (nxwright, pinned).
- Verify: `nxwright check` + compile clean, tft-listing diff vs intent,
  flash + boot on hardware with screen-photo verdict.

## Step 6 — Optimization pass (measured, not vibes)
- Each optimization needs a before/after number: flash image size,
  ESP heap/RAM, HA event-loop blocking, page weight/data dir budget,
  MQTT chatter rate, OTA duration at 115200.
- Output: `docs/detach-perf.md` with the numbers table.
- Verify: budgets enforced by tests (like the 24KB data-dir test).

## Step 7 — Cutover + release
- App release v2.0.0 (breaking-surface audit: anything renamed/removed
  listed in release notes), evergreen firmware publish, staged rollout:
  bench panel → DemoPanel with user watching.
- Verify: R1 full matrix (pytest + Go + Playwright + hardware flash+boot).

## Rollback per step
- Steps 1–2: docs/tests only — revert commit.
- Steps 3–4: keep old modules beside new until contract suite passes on
  new; panel reflash to last evergreen on failure.
- Step 7: HACS downgrade to v1.x + evergreen republish of last 1.x
  firmware; blank.tft recovery path stays staged at all times.

## Parallelism
- Steps 1→2 serial. Steps 3, 4, 5 parallel after Step 2 (disjoint trees:
  custom_components/ vs firmware/ vs hmi/). Step 6 after 3–5. Step 7 last.

## Adversarial review notes (self-check)
- [ ] No step flashes the user's only working panel without explicit go.
- [ ] No step breaks the wire protocol unless Q1 explicitly says so.
- [ ] Every step has a verification command, not a vibe.
- [ ] Blank-TFT + last-evergreen recovery staged before any flash step.
- [ ] Single-version rule respected (no reused numbers).
