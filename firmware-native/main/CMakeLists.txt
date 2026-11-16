set(COMPONENT_SRCDIRS "main")
set(COMPONENT_ADD_INCLUDEDIRS "main")
idf_component_register(
    SRCS "main/main.c" "main/mqtt.c" "main/ota.c" "main/display.c" "main/wifi.c"
    INCLUDE_DIRS "main"
    REQUIRES esp_wifi nvs_flash esp_mqtt esp_http_client esp_ota_ops esp_timer driver esp_littlefs
)
