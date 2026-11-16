# Measured optimization numbers (Step 6)

Measured on the actual build machine / artifacts. Hardware-in-loop numbers
marked (H) pending bench validation.

## Flash image size (app binary)

| Build | Size | vs v1 |
|---|---|---|
| v1 Arduino build (0.1.187, live line) | 1,409,728 B | — |
| Upstream released (v0.3.967) | 1,718,432 B | +22% |
| **v2 native IDF (0.2.0-alpha.1)** | **956,576 B** | **−32%** |

The native build is 453KB lighter than the live v1 line and 45% smaller than
upstream's own release — mostly the dropped Arduino shim, HTTP/JSON stack
duplication, and the per-page C++ UI machinery (moving into the nxwright HMI).

## OTA transfer time (est. at 115 KB/s bench WiFi, (H) to confirm)

| Image | Download | Flash+verify |
|---|---|---|
| v1 | ~12.5 s | (H) |
| v2 native | ~8.5 s | (H) |

## RAM / heap (H) pending bench
ESP-IDF native idle heap to be measured on first bench boot; target ≥ 60%
free at idle with WiFi+MQTT connected.

## MQTT chatter
Unchanged by design (contract): status_report every 30 s, registration every
5 min (P135). The protocol is frozen; the rewrite optimizes the stack, not
the wire.

## Data partition budget
Native firmware config lives in NVS (config.h) — the 585,728-byte data
partition now serves ONLY the static web UI assets for the setup AP, removing
the config-json-in-fs write churn of v1 entirely.

## Test suite
128 tests in 2.3 s (contract suite + v2 conformance + HMI + firmware audits)
— runs on every push via CI.
