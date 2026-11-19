idf_component_register(
    SRCS "main.cpp" "mqtt.cpp" "ota.cpp" "display.cpp" "wifi.cpp" "setup_ap.cpp" "relay.cpp" "form_parse.cpp" "scan_json.cpp" "provision.cpp" "provision_parse.cpp" "accept_parse.cpp" "touch_decode.cpp" "temp_math.cpp" "relay_cmd.cpp" "logbuf.cpp" "webui_pages.cpp" "webui.cpp" "dash_cmd.cpp" "screensaver_parse.cpp"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi nvs_flash mqtt esp_http_client esp_timer driver esp_partition esp_adc esp_http_server app_update esp_event esp_netif mdns
)
