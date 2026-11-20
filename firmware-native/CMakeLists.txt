# NSPanel Core — native ESP-IDF firmware (clean-room, no Arduino layer)
cmake_minimum_required(VERSION 3.16)

# Fixed project version — the git-describe default produced misleading
# "app-v0.1.2-dirty" app_init banners (R1 evidence from the serial console).
set(PROJECT_VER "0.1.5")
set(IDF_TARGET "esp32" CACHE STRING "Target ESP32")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(nspanel_core)
