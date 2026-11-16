# Release scheme (P143 — disambiguation)

Two independent release trains. Version numbers never collide across them:

| Train | Format | Examples | Where it releases |
|---|---|---|---|
| **App** (HA integration) | `vX.Y.Z` | v1.3.53 → v2.0.0 at cutover | GitHub release + HACS |
| **Panel firmware** (Arduino line, live) | `0.1.Y` | 0.1.187 | evergreen `firmware-latest` + manifest.json |
| **Panel firmware** (native v2 line) | `0.2.Y` | fw-v0.2.0-alpha.1 | GitHub pre-release `fw-*` |

Rules:
1. Every firmware release tag carries the `fw-` prefix (pre-releases use
   `fw-v…`). App releases never carry it.
2. The recovery page labels state which train each button installs.
3. The app's dashboard shows the PANEL's reported firmware version next to
   the panel — the app's own version lives in HACS.
