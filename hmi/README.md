# HMI — nxwright source (Step 5)

The display UI lives here as TEXT, versioned and diffable — no binary blobs.

## Layout
- `nspanel-core-native/` — the source: `program.nx` (code), `pages/`, `fonts/`,
  `pictures/`, `app.toml`, `defaults.toml` (device: NX4832F035).
- The compiled display file (`*.tft`) is a RELEASE ARTIFACT, never committed.

## Pipeline
1. `nxwright check hmi/nspanel-core-native` — validate (CI runs this).
2. `nxwright build hmi/nspanel-core-native /tmp/out.hmi --overwrite` — emit the
   Nextion project file.
3. The HMI→TFT compile runs in the release toolchain (Nextion compiler);
   the compiled TFT is uploaded to the evergreen release and served to panels
   via the integration's tft_update flow.

## Current state (P140)
The source carries the rebranded NSPanel Core UI (boot splash verified on
hardware, 461,084-byte TFT). Live clock/date on the splash is the next
authored change — baby steps, verified with a screen photo after every flash.
