# Release scheme (P143 — disambiguation)

Two independent release trains. Version numbers never collide across them:

| Train | Format | Examples | Where it releases |
|---|---|---|---|
| **App** (HA integration) | `vX.Y.Z` | v0.0.1 (epoch baseline) | GitHub release `app-*` + HACS |
| **Panel firmware** (Arduino line, live) | `0.0.Y` | v0.0.1 (epoch baseline) | evergreen `firmware-latest` + manifest.json |
| **Panel firmware** (native line) | `0.1.Y` | fw-v0.1.0-alpha | GitHub pre-release `fw-*` |

Rules:
1. Every firmware release tag carries the `fw-` prefix (pre-releases use
   `fw-v…`). App releases never carry it.
2. The recovery page labels state which train each button installs.
3. The app's dashboard shows the PANEL's reported firmware version next to
   the panel — the app's own version lives in HACS.

## Epoch restart (P144)
The 0.1.x firmware and 1.x app series predate the first fully-stable state,
so both trains restarted at zero: app v0.0.1 and firmware v0.0.1 are the
baselines. The native line lives at 0.1.x. History of pre-epoch releases was
deleted; the code lineage lives in git history and the LEDGER.
