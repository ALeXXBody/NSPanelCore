idf_component_register(
    SRCS "main.cpp" "mqtt.cpp" "ota.cpp" "display.cpp" "wifi.cpp"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi nvs_flash esp-mqtt esp_http_client esp_timer driver esp_partition esp_littlefs
)
