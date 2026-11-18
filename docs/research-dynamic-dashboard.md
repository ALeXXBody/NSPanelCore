# Research: Dynamic Room Dashboard for NSPanel Core

*Status: RESEARCH ONLY — nothing implemented, nothing released. Awaiting user decisions (P232 rule: prepare, verify, wait).*

## Goal (the user's words, restated)

The panel can live in different rooms. The user chooses a room; the background
picture represents that room (bathroom, kitchen, living room…). The user chooses
which entities the panel shows (light switch, climate, RGB LED, …). All of it
customizable from the manager — no reflashing by hand, no code edits.

## What we already have (grounding in the repo)

| Piece | State |
|---|---|
| HMI source (`hmi/nspanel-core-native/`) | 7 pages (page0, screensaver, home, mini, room, spare, scenes), compiled locally with `nxwright` — **we own the toolchain, no Windows** |
| `room` page | exists with hotspots, currently a static stub |
| Backgrounds | 4 baked pictures (~88 KB source); the full-UI TFT is 696,276 B |
| `PanelConfig` | already carries `room_id`, `default_page` (MAIN/SCENES/ROOM), `lock_to_default_room` — the room *concept* exists in the data model |
| Firmware display commands | `page <name>`, `<obj>.txt="…"`, relay state pictures, screensaver — narrow but proven |
| TFT delivery | block-protocol streamer over MQTT-triggered OTA; no ESP flash cost for the TFT (streamed through RAM) |
| Manager | runs inside HA (can read `hass.states` and call `hass.services` internally — **no token needed**), serves per-panel actions |

## How the display actually works (the physics we must design within)

1. **Pages and components are COMPILED into the TFT.** A running display cannot
   add or remove a button. Everything interactive must be *pre-authored* as a slot.
2. **But pictures swap at runtime**: Nextion's documented mechanism is
   `p0.pic=<id>` (picture component) and page-background `.pic=` on the page
   itself (avoids full-screen redraw flicker — Nextion Editor Guide §2.7).
   `picq x,y,w,h,id` can crop-draw regions. So **backgrounds and icons are
   dynamic without a reflash**.
3. **Text is dynamic**: `<obj>.txt="…"` — already proven by our `.txt=` fix.

## What the established projects do (evidence)

- **NSPanel Lovelace UI (joBr99)** — the market standard: a fixed display
  firmware full of slots (cardGrid/cardEntities/cardThermo/cardMedia + light and
  cover detail popups); a backend maps HA entities to slots and renders via
  serial commands; YAML/web-editor configured; "no need to code or touch Nextion
  Editor". Confirms: **dynamic content = slot mapping, not TFT reflashing.**
- **NSPanel HAUI (happydasch)** — visual editor inside HA, 13 panel types for
  room displays, background pictures + icon/color overrides, gestures, live
  preview. Same architecture: hub renders, panel relays touches.
- **NSPanel HA Blueprint (Blackymas)** — 32 buttons over 4 pages, button design
  auto-generated per entity type, long-press detail menus.
- All of them keep **user-supplied backgrounds** out of the compiled slot logic:
  backgrounds change by re-uploading a TFT (their users do this via a web
  download), never per-entity.

## The size math (why this is feasible)

Full-screen 16-bit background at 480×320 = **307,200 B**.

| TFT contents | Size | Upload time @921600 |
|---|---|---|
| today's full UI (4 bgs) | 696 KB | ~1 s over LAN + HTTP |
| + 6 room backgrounds | ~1.84 MB more | still seconds; stock NSPanel TFTs are ~1.7 MB, and the display's flash holds them |

The ESP32 streams the TFT through RAM (already implemented), so TFT size costs
**nothing in panel flash** — only download time. NVS only stores the tiny
room→slot mapping.

## Three architecture options

### Option A — slot mapping only (all established projects' core)

Pre-author the `room` page with N generic slots (e.g. 2 relay tiles + 4
small tiles). Manager assigns entity + widget type per slot; a `dashboard`
MQTT command ships the mapping; firmware stores it (NVS) and routes state
updates/touches. Backgrounds: a small set of baked stock room images, swapped
via `.pic=`.

- ✅ instant config changes, no TFT re-upload, smallest risk
- ❌ backgrounds limited to baked stock images; slot layout frozen

### Option B — per-panel TFT regeneration (the "fully custom" end game)

The manager keeps the HMI source, injects the user's own room photos and the
chosen slot layout per panel, compiles with `nxwright` (runs on the HA host or
.200 — no Windows), serves a **panel-specific TFT** over the existing internal
channel; the panel reflashes it via the block protocol.

- ✅ truly custom: your kitchen photo behind your kitchen buttons
- ❌ every background/layout change = recompile + ~1 min upload; needs
  per-panel TFT serving (the manifest today is version-based)

### Option C — hybrid (superseded)

*(Historical: stock-baked slots + opt-in regeneration. Superseded by the user's direction — Option D below is the chosen architecture.)*

### Option D — per-panel generated TFT (USER'S DIRECTION — RECOMMENDED)

**The integration keeps the HMI source. The user customizes their dashboard in
the manager (rooms, background photos per room, which entities on which
buttons, layout). The manager generates the panel's HMI from that config,
compiles it with nxwright, and sends the finished TFT to that panel over the
existing internal channel (block-protocol reflash).**

Why this wins for THIS project:

1. **We own the toolchain** — nxwright compiles locally; no other NSPanel
   project can do this for their users (they're locked to fixed slot grids
   precisely because their users can't compile).
2. **Smaller firmware, not bigger.** The manager generates the layout, so the
   manager knows every component→entity mapping. The panel only reports
   "component pressed" events; the manager resolves them to entities and calls
   HA services internally (`hass.services` — no token needed). No `dashboard`
   command, no NVS mapping storage — the firmware barely changes.
3. **No customization ceiling**: any background per room, any entity anywhere,
   any number of pages.

Tradeoff (accepted): every customization change = recompile (seconds) +
TFT upload (~1 min @921600, boot splash during). Live values (clock, temps,
states) always ride the runtime command channel — the TFT carries structure,
the manager pushes values.

Storage: each panel's generated TFT lives on the HA host (~2 MB each —
trivial). A generic fallback TFT (the current release) covers panels with no
custom dashboard yet.

## Design (Option D — the user's direction)

### Data model (manager — the single source of truth)

```
Room:            id, name, background_image (user photo, stored by the manager)
PanelDashboard:  per PanelConfig — pages[] each with items[]
Item:            geometry + widget_type (light | switch | climate | rgb_light |
                 scene | sensor) + entity_id + label
Generated:       per-panel HMI source folder + compiled TFT + the component→
                 entity map (kept by the manager, never stored on the panel)
```

Manager UI: per-panel "Dashboard" page — pages/rooms on the left, a visual
layout of the 480×320 screen, entity picker per item (from `hass.states`,
native, no token), photo upload per room. **Save → generate → compile → send.**

### Protocol (what changes — almost nothing)

- Runtime values: existing command channel (`<obj>.txt=`, state pictures) — unchanged
- Touch: the panel already reports presses; the manager resolves component →
  entity from the map IT generated — unchanged firmware behavior
- TFT delivery: existing block-protocol reflash, triggered per panel —
  unchanged mechanism, per-panel artifact

### Where the compile runs — THE open decision

| Path | How | Pro | Con |
|---|---|---|---|
| **Inside HA** | nxwright as a manifest requirement (pure-Python pip dep) + fonts/PNGs shipped in the integration package | self-contained; no dependency on .200 | needs nxwright pip-installable + verified in the HA container |
| **On .200** | manager POSTs the generated HMI to a small build service on .200; gets the TFT back | .200 already has nxwright working | external dependency: dashboards can't regenerate while .200 is down |

Default proposal: **inside HA** (self-contained), .200 as fallback.

### Widget types, phased

1. **light/switch** — dual-state tile (exists today on home page)
2. **climate** — tile showing current temp; tap → detail page (+/− setpoint hotspots)
3. **rgb_light** — tile + detail page with brightness slider + preset color swatches (baked pictures; full color wheel = 6 swatches + slider is the practical ceiling on a 3.5" screen)
4. **sensor** — label + value tile
5. **scene** — one-tap scene activation

### TFT asset growth

Stock set: kitchen, bathroom, living, bedroom, hallway, custom-generic
(6 × 307 KB ≈ 1.8 MB) — shipped with the next TFT release; per-panel custom
photos are only in that panel's regenerated TFT.

## Risks / open points

1. **nxwright in the HA container** — must verify it pip-installs and compiles
   there (fonts, PNG assets ship inside the integration package). If not, the
   .200 build service is the fallback.
2. **Compile+upload latency** per change (~1 min) — acceptable for deliberate
   customization; values stay instant via commands. Mitigation for heavy users:
   batch edits, then one send.
3. **US panel orientation** — portrait layout needs its own geometry template.
4. **TFT sizes** are per-panel now — the display-flash check (one ~2.5 MB burn)
   still worth doing once.
5. **Entity↔component resolution** lives in the manager — regenerate must
   happen before serving a TFT that references new components (keep the
   generated map atomic with each TFT artifact).

## Phased roadmap (each phase independently releasable)

| Phase | Content | Ship vehicle |
|---|---|---|
| 1 | Manager dashboard editor (rooms + items + entity picker) + HMI generator + nxwright compile + per-panel TFT send via the existing block channel; touch → entity routing | app minor (fw likely unchanged) |
| 2 | Climate + RGB widget templates (detail pages generated on demand) | app minor |
| 3 | Custom background photo uploads per room | app minor |
| 4 | US portrait geometry template | app minor |

## Decision needed from the user

1. Compile inside HA (default) or on .200?
2. Widget priority order (climate before RGB, or the reverse)?
3. Is the ~1-minute send-per-change acceptable, or should the editor batch
   changes and only send on an explicit "Send to panel"?
