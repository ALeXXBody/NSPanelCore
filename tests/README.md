# NSPanel Core host-side tests

Two layers:

1. **Contract tests** (`test_fw_contract.py`) — no HA needed. Run with
   system python: `python3 -m pytest tests/test_fw_contract.py -v`.
   Verifies MQTT topic helpers, the protobuf codec, manager↔firmware
   topic coverage, and that every config key the firmware reads is
   emitted by the manager builders.

2. **Regression tests** (`test_handlers.py`, `test_platforms.py`,
   `test_templates.py`) — need `homeassistant` importable. Run with an
   HA dev venv:
   `/tmp/opencode/ha-venv-2611/bin/python -m pytest tests/ -v`
   These execute the real handler/platform code with fakes and would
   have caught the v1.3.37 light-platform setup crash (UnboundLocalError
   from a misordered comprehension that only triggers with panels
   present — py_compile and imports were green, execution was not).
   Lesson: never trust compile/import checks alone.

`pytest.ini` sets `asyncio_mode = auto` for the async tests.
