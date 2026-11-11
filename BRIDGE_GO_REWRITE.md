# NSPanel Core — Go Bridge Rewrite Specification

Goal: replace the C++ MQTTManager (11.8k LOC, Conan/CMake, Boost/Protobuf/OpenSSL) with a
1:1 behavioral clone in Go. Drop-in replacement: same binary path
`/MQTTManager/build/nspm_mqttmanager`, same startup contract, same external behavior.

## Why Go
- Build in seconds, cross-compile with one env var, no Conan/CMake/Boost ever again
- Pure-Go SQLite driver (modernc.org/sqlite) → zero CGO → trivial cross-compilation
- Single static binary, stable runtime, goroutines for the event loops

## External contract (must be preserved exactly)

### 1. Process contract (from Django `web/apps.py`)
- Django starts: `subprocess.Popen(["/MQTTManager/build/nspm_mqttmanager"], cwd="/usr/src/app/", env=...)`
  - env contains `LOG_LEVEL` (error|warning|info|debug|trace)
  - env contains `IS_HOME_ASSISTANT_ADDON` ("true"/"false")
- Config reload: Django sends **SIGUSR1** → reload config from DB → republish `nspanel/config/reload` = "1"
- Restart: Django kills the process (SIGKILL) and starts a new one

### 2. Database (SHARED SQLite with Django — direct access, NOT REST)
- Path: `/data/nspanelmanager_db.sqlite3` (or `/tmp/nspanelmanager_db_test.sqlite3` in TEST_MODE)
- Tables read: `web_settings` (id,name,value), `web_nspanelsettingholder` (id,name,value,nspanel_id),
  `web_nspanel` (id, mac_address, friendly_name, model, room_id, version, button1_detached_mode_entity_id,
  button1_mode, button2_detached_mode_entity_id, button2_mode, md5_data_file, md5_firmware, md5_tft_file,
  denied, accepted), `web_room` (id, friendly_name, room_temp_provider, room_temp_sensor, display_order),
  `web_scene` (id, room_id, friendly_name, scene_type, backend_name, room_view_position, entities_page_id),
  `web_scenelightstate` (id, light_level, color_mode, color_temperature, hue, saturation, light_id, scene_id),
  `web_roomentitiespage` (id, display_order, page_type, is_scenes_page, room_id), `web_entity`
  (id, entity_type, friendly_name, entities_page_id, room_view_position, room_id, entity_data JSON),
  `web_relaygroupbinding` (id, relay_num, nspanel_id, relay_group_id) + relay_groups tables
- Tables written: `web_entity.entity_data` (JSON blob of live entity state), nspanel md5 checksums
- Settings keys: see MQTT_MANAGER_SETTING enum (buttons, clock, HA address/token, weather, screensaver,
  MQTT server/port/user/pass, manager address/port, timezone, log level, optimistic mode, ...)

### 3. MQTT topics (paho → eclipse/paho.mqtt.golang)
Panel-facing (`{mac}` = panel MAC):
- Subscribe: `nspanel/+/status`, `nspanel/+/command`, `nspanel/+/status_report`
- Publish (retained): `{mac}/status`, `{mac}/status_report`, `{mac}/log`, `{mac}/log_backlog`,
  `{mac}/temperature`, `{mac}/humidity`, `{mac}/pressure`, `{mac}/screen_state`, `{mac}/screen_cmd`,
  `{mac}/screensaver_mode_state`, `{mac}/screensaver_mode_cmd`, `{mac}/relay1_state|cmd`,
  `{mac}/relay2_state|cmd`, `{mac}/home_page_all`
- Command payloads: **protobuf** `NSPanelMQTTManagerCommand` (base64), `NSPanelConfig` (base64)

Manager-facing (`{addr}` = manager address setting):
- `nspanel/mqttmanager/command` (sub), `nspanel/mqttmanager_{addr}/command` (sub)
- `nspanel/mqttmanager_{addr}/status/status`, `.../status/time` (retained, every minute),
  `.../status/ampm`, `.../status/date`, `.../status/weather`
- `nspanel/mqttmanager_{addr}/room/{id}/state` (protobuf NSPanelRoomStatus)
- `nspanel/mqttmanager_{addr}/room/{id}/temperature_state`
- `nspanel/mqttmanager_{addr}/entity_pages/{id}/state` (protobuf NSPanelRoomEntitiesPage)
- `nspanel/mqttmanager_{addr}/entities/lights/{id}/state` (protobuf NSPanelEntityState)
- `nspanel/mqttmanager_{addr}/entities/thermostats/{id}/state`
- `nspanel/mqttmanager_{addr}/all_rooms_status`
- `nspanel/status/weather`
- Browser register flow: JSON `register_request` on `nspanel/mqttmanager/command` → reply JSON (base64)
  register_accept on `nspanel/{mac}/command`

### 4. STOMP-over-WebSocket server (port 8002) — kiosk UI
- nginx proxies `/websocket/stomp` → bridge :8002
- STOMP 1.2 subset over WebSocket text frames: CONNECT→CONNECTED, SUBSCRIBE/UNSUBSCRIBE,
  SEND (client→bridge, JSON commands), MESSAGE (bridge→client), receipts, DISCONNECT
- CONNECT headers: `last_will_topic`, `last_will_message`, `last_will_retained` (browser presence)
- Payload encodings: JSON strings (register/status commands) AND **base64-encoded protobuf**
  (NSPanelConfig, NSPanelRoomStatus, NSPanelRoomEntitiesPage, NSPanelEntityState,
  NSPanelStatusReport, NSPanelWeatherUpdate — decode via `atob` in web-ui)
- Topic registry with retained values + last-will semantics (StompTopic in C++)
- Virtual MAC registration: web browser acts as a panel with a generated MAC

### 5. Home Assistant integration
- WebSocket API client to `http(s)://<ha>/api/websocket` with long-lived access token
  (auth phase: `auth` → `auth_ok` → subscribe)
- Watches light/scene/thermostat state changes, drives entity state machines
- Calls HA services to forward light commands (turn_on/turn_off with brightness/color_temp/rgb)

### 6. Weather (open-meteo)
- Poll `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=temperature_2m,...`
  every WEATHER_UPDATE_INTERVAL minutes; format per settings (C/F, km/h / m/s / mph / knots,
  mm/inches); publish protobuf NSPanelWeatherUpdate to `nspanel/status/weather` (JSON?)

### 7. Time publisher
- Every minute (aligned to minute boundary): publish time/ampm/date retained to
  `nspanel/mqttmanager_{addr}/status/time|ampm|date` respecting CLOCK_US_STYLE + DATE_FORMAT

## Go implementation plan (stages)
1. `go.mod` + protobuf codegen (reuse the 4 .proto files verbatim via protoc-gen-go)
2. `db` package: settings + entities + rooms/panels queries (modernc.org/sqlite)
3. `mqtt` package: connect, publish/subscribe, topic builder, retained handling
4. `timepub`: minute-aligned publisher (trivial, testable)
5. `stomp` package: WebSocket + STOMP frame codec + topic registry (gorilla/websocket)
6. `entities`: light/thermostat/scene state machines (port from C++)
7. `ha`: HA WebSocket API client
8. `panels`: NSPanel state machine (status report, pages, screensaver, relays, OTA md5s)
9. `weather`: open-meteo client
10. `main`: wire everything, SIGUSR1 handling, LOG_LEVEL mapping
11. Integration test: run against live Django+MQTT, diff MQTT/STOMP traffic vs C++ bridge
12. Swap: Dockerfile copies Go binary to `/MQTTManager/build/nspm_mqttmanager`

## Entity layer contract (discovered)
- `web_entity.entity_data` JSON schema (Django writes config, bridge writes live state):
  `{controller: "home_assistant", home_assistant_name: "light.x", can_dim, can_color_temperature,
  can_rgb, is_ceiling_light, controlled_by_nspanel_main_page}` + live state fields the bridge
  adds (see light.cpp set_entity_data_json usage)
- Light types: ceiling/table (affects room aggregations), controlled_from_main_page
- HA event shape: `event.data.new_state` with `attributes` (brightness, color_temp, rgb_color...) —
  the light state machine maps HA attributes → NSPanelEntityState protobuf → MQTT manager topic

## Status
- [x] Inventory complete (this doc)
- [x] go.mod + protos (wire-identical bindings)
- [x] db package (full schema access + write-back)
- [x] mqtt package (client + exact topic builders)
- [x] timepub (minute-aligned publisher)
- [x] config loader (mirrors MqttManagerConfig::load)
- [x] stomp package (full STOMP 1.2 server port)
- [x] ha package (WS API client: auth, subscribe_events, get_states, call_service, observers)
- [x] weather package (open-meteo → NSPanelWeatherUpdate)
- [x] entities: lights (HA events, service calls, optimistic mode, protobuf publish, entity_data write-back)
- [x] entities: thermostats (options from entity_data, HA climate services)
- [ ] entities: scenes (activate scene → set lights to scene state)
- [ ] panels package (NSPanel state machine: status report, pages, screensaver, relays, OTA md5s)
- [ ] command routing (NSPanelMQTTManagerCommand dispatch: lights/thermostat/buttons/pages)
- [ ] integration test (traffic diff vs C++ bridge)
- [ ] Dockerfile swap (copy Go binary to /MQTTManager/build/nspm_mqttmanager)
