#!/bin/bash
# Host-side unit tests for the native firmware's pure logic (R1).
# Fails the shell if any test fails — wire into the release checklist.
set -e
cd "$(dirname "$0")"
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t1 test_form_parse.cpp ../src/form_parse.cpp
/tmp/opencode/nsp_t1
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t2 test_scan_json.cpp ../src/scan_json.cpp
/tmp/opencode/nsp_t2
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t3 test_relay_cmd.cpp ../src/relay_cmd.cpp
/tmp/opencode/nsp_t3
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t4 test_accept_parse.cpp ../src/accept_parse.cpp
/tmp/opencode/nsp_t4
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t5 test_touch_decode.cpp ../src/touch_decode.cpp
/tmp/opencode/nsp_t5
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t6 test_logbuf.cpp ../src/logbuf.cpp
/tmp/opencode/nsp_t6
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t7 test_webui_pages.cpp ../src/webui_pages.cpp
/tmp/opencode/nsp_t7
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t8 test_provision_parse.cpp ../src/provision_parse.cpp
/tmp/opencode/nsp_t8
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t9 test_dash_cmd.cpp ../src/dash_cmd.cpp
/tmp/opencode/nsp_t9
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_t10 test_screensaver_parse.cpp ../src/screensaver_parse.cpp
/tmp/opencode/nsp_t10
# P311 FULL-APP/FIRMWARE AUDIT — edge cases for the paths nothing covered
g++ -std=c++17 -Wall -Wextra -o /tmp/opencode/nsp_edge ../../tests/test_edge_cases.cpp ../src/form_parse.cpp ../src/provision_parse.cpp
/tmp/opencode/nsp_edge
