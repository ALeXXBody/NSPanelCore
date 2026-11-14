# NSPanel Core — Go Rewrite (in progress)

Same app, properly engineered. Not a platform swap, not a shortcut.

## Why Go for the backend

Home Assistant only loads Python custom components, so the HA shim stays
Python (thin: entities + UI proxy). All business logic — MQTT routing, OTA
decisions, protobuf codec, config persistence — moves to a single static Go
daemon:

- Builds in seconds, cross-compiles with one env var, no Conan/CMake/Boost
- Pure-Go SQLite (modernc.org/sqlite) — zero CGO
- Single static binary, goroutines for event loops, `go vet` + `go test` clean
- 1:1 behavioral clone: same topics, same wire bytes, same storage keys

ESPHome was rejected: it throws away the app (rooms, scenes, relay groups,
custom TFT pinning, STOMP UI). This rewrite keeps every feature.

## Layout

- `topics/` — `panel_mqtt_base`/`panel_mqtt_topic`/`topic_safe` byte-exact port
- `pcode/` — `panel_pb/codec.py` port (varint, tags, floats, zigzag, base64)
- `config/` — `models.py` port (JSON storage, tolerant load, panel normalize)
- `ota/` — `firmware_store.py` + OTA cache port (atomic staging, hash-verify,
  exact-file pinning; sync map return — the v1.3.43 coroutine lesson)
- `manager/` — routing + OTA-decision pure logic (hostname-first, drift warn,
  data never auto-flashes)

## Verify

```sh
cd rewrite/nspanelcore && go test ./... && go vet ./...
```

## Status

P50 in LEDGER.md. Integration untouched until the Go daemon reaches
integration-test parity (traffic diff vs Python manager), then the Python
shim thins to entities + UI proxy.
