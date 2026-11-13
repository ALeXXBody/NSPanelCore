# Display files (TFT/HMI) — remaining editor work

All claims below were verified by parsing the HMI binaries and the firmware
sources (2026-11-13). Nothing here is guessed.

## 1. US display file: rebrand done, compile pending

- Patched project: `/tmp/opencode/nxwork/us/gui.HMI` (backup `gui.HMI.bak`).
  All 48 boot frames were byte-swapped with the rebranded set from
  `/tmp/opencode/coreframes_us/` (verified: rebranded bytes present,
  originals gone). Same proven method as the shipped EU file.
- To finish: open the patched HMI in Nextion Editor 1.68.x → File → TFT
  file output. Verify the header: editor bytes `01 44`, vendor `0x4E`,
  resolution `e0 01 40 01` (480×320), orientation flag `0x02` (portrait),
  internal size field `@0x3C` equals the actual file size.
- Ship the result as `custom_components/nspanel_core/tft/gui_us.tft`,
  publish via `firmware/publish.sh` (it re-hashes + verifies).
- Blocked 2026-11-13: the build host has no working X server (Xvfb and Xvnc
  both abort with `double free or corruption`), so the editor GUI cannot
  run there. Needs any machine with a display (or a working Xvfb build).

## 2. Missing display pages (EU and US HMI alike)

The HMI projects contain exactly 12 pages (verified by enumerating the
`O!\x00` page-table markers): bootscreen, cleanscreen, dropdown, home,
items12, items4, items8, lights, page0, screensaver, screensaver2,
thermostat. The firmware navigates to pages that do not exist:

| Firmware target | HMI has it? | Impact |
|---|---|---|
| `home` | yes | OK |
| `bootscreen` | yes | OK |
| `screensaver`, `screensaver2` | yes | OK |
| `thermostat` | yes | OK (no firmware consumer of modes 4/5; dormant) |
| `lights` (fixed 2026-11-13, was `Lights`) | yes (lowercase, components match) | FIXED in fw 0.1.162 |
| `Scenes` | NO | tapping Scenes on-device no-ops (Nextion ignores unknown `page` target) |
| `Room` | NO | tapping a room on-device no-ops |
| `settings` | NO | never navigated to by firmware (define only) — dormant |

Dead reference inside the HMI itself: event code contains `page partytime`
but no `partytime` page exists.

Missing components referenced by firmware event/code strings: `curIcon`,
`curRoomtemp` (0 hits in HMI). Present: `curTempIcon`, `roomTemp`,
`t_loading`, `t_ip`, `curTemp`, `b_scenes`.

### What the editor work needs (component shopping list from TftDefines.h)

- **Scenes page** (`Scenes`, id 6): labels `scenes_current` (14),
  `scene1..scene4` (ids 1–4) + save buttons `scene1_save..scene4_save`
  (ids 5–8), back (9), prev (10), next (11), `slider_save`.
- **Room page** (`Room`, id 4): label `room_current`, back (25),
  prev room (26), next room (28). (Full component list: see
  `ROOM_PAGE_*` defines in `firmware/lib/InterfaceManager/TftDefines.h`.)
- **Settings page** (`settings`, id 3): back (4), label `label`.
- Fix/verify `curIcon` + `curRoomtemp` components wherever the home page
  addresses them.

Until those pages exist in the HMI, on-device room/scene browsing stays
inert. HA-side control (app, automations, voice) is unaffected — this is
display-only.
