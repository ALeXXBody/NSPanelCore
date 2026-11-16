#include "esp32-hal.h"
#include "nvs.h"
#include "nvs_flash.h"
#include <Arduino.h>
#include "freertos/portmacro.h"
#include <ButtonManager.hpp>
#include <HTTPClient.h>
#include <InterfaceManager.hpp>
#include <LittleFS.h>
#include <MqttLog.hpp>
#include <MqttManager.hpp>
#include <NSPMConfig.h>
#include <NSPanel.hpp>
#include <PageManager.hpp>
#include <PubSubClient.h>
#include <TftDefines.h>
#include <WebManager.hpp>
#include <WiFi.h>
#include <cmath>
#include <math.h>
#include <nspm-bin-version.h>
#include <string>

NSPanel nspanel;
InterfaceManager interfaceManager;
MqttLog logger;
NSPMConfig config;
WebManager webMan;
TaskHandle_t _taskWifiAndMqttManager;
WiFiClient espClient;
MqttManager mqttManager;

unsigned long lastRegistrationRequest = 0;
unsigned long lastStatusReport = 0;
unsigned long lastWiFiconnected = 0;
// Temperature sensing variables:
#define READ_TEMP_SENSE_DELAY_MS 1000
#define NUM_TEMP_SENSE_AVERAGE 30
float averageTemperature = 0;
uint8_t numberOfTempSamples = 0;
uint8_t temperatureSlotNumber = 0;
float tempSensorReadings[NUM_TEMP_SENSE_AVERAGE];

void readNTCTemperatureTask(void *param) {
  for (;;) {
    float temperature = analogRead(38);
    temperature = temperature * 3.3 / 4095.0;
    temperature = 11200 * temperature / (3.3 - temperature);
    temperature = 1 / (1 / 298.15 + log(temperature / 10000) / 3950);
    temperature = temperature - 273.15; // Celsius

    if (NSPMConfig::instance->use_fahrenheit) {
      temperature = (temperature * 9 / 5) + 32;
    }
    tempSensorReadings[temperatureSlotNumber] = temperature + NSPMConfig::instance->temperature_calibration;
    temperatureSlotNumber++;
    if (temperatureSlotNumber >= NUM_TEMP_SENSE_AVERAGE) {
      temperatureSlotNumber = 0;
    }
    if (numberOfTempSamples < temperatureSlotNumber) {
      numberOfTempSamples = temperatureSlotNumber;
    }

    float tempTotal = 0;
    for (int i = 0; i < numberOfTempSamples; i++) {
      tempTotal += tempSensorReadings[i];
    }
    int averageTempInt = (tempTotal / numberOfTempSamples) * 10;
    averageTemperature = float(std::round(averageTempInt)) / 10;
    vTaskDelay(READ_TEMP_SENSE_DELAY_MS / portTICK_PERIOD_MS);
  }
}

void sendMqttManagerRegistrationRequest() {
  // Only send registration requests with a 3 second interval.
  if (MqttManager::connected() && millis() >= lastRegistrationRequest + 3000) {
    LOG_DEBUG("Sending MQTTManager register request.");
    JsonDocument doc;
    doc["command"] = "register_request";
    doc["mac_origin"] = WiFi.macAddress();
    doc["friendly_name"] = NSPMConfig::instance->wifi_hostname.c_str();
    doc["version"] = NSPanelCoreFirmwareVersion;
    doc["md5_firmware"] = NSPMConfig::instance->md5_firmware;
    doc["md5_data_file"] = NSPMConfig::instance->md5_data_file;
    doc["md5_tft_file"] = NSPMConfig::instance->md5_tft_file;
    doc["address"] = WiFi.localIP();

    char buffer[512];
    serializeJson(doc, buffer);
    MqttManager::publish("nspanel/mqttmanager/command", buffer);
    lastRegistrationRequest = millis();
  }
}

void onWiFiEvent(WiFiEvent_t event) {
  Serial.printf("[WiFi-event] event: %d\n", event);

  switch (event) {
  case ARDUINO_EVENT_WIFI_READY:
    Serial.println("WiFi interface ready");
    break;
  case ARDUINO_EVENT_WIFI_SCAN_DONE:
    Serial.println("Completed scan for access points");
    break;
  case ARDUINO_EVENT_WIFI_STA_START:
    Serial.println("WiFi client started");
    break;
  case ARDUINO_EVENT_WIFI_STA_STOP:
    Serial.println("WiFi clients stopped");
    break;
  case ARDUINO_EVENT_WIFI_STA_CONNECTED:
    Serial.println("Connected to access point");
    break;
  case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
    Serial.println("Disconnected from WiFi access point");
    break;
  case ARDUINO_EVENT_WIFI_STA_AUTHMODE_CHANGE:
    Serial.println("Authentication mode of access point has changed");
    break;
  case ARDUINO_EVENT_WIFI_STA_GOT_IP:
    Serial.print("Obtained IP address: ");
    Serial.println(WiFi.localIP());
    break;
  case ARDUINO_EVENT_WIFI_STA_LOST_IP:
    Serial.println("Lost IP address and IP address is reset to 0");
    break;
  case ARDUINO_EVENT_WPS_ER_SUCCESS:
    Serial.println("WiFi Protected Setup (WPS): succeeded in enrollee mode");
    break;
  case ARDUINO_EVENT_WPS_ER_FAILED:
    Serial.println("WiFi Protected Setup (WPS): failed in enrollee mode");
    break;
  case ARDUINO_EVENT_WPS_ER_TIMEOUT:
    Serial.println("WiFi Protected Setup (WPS): timeout in enrollee mode");
    break;
  case ARDUINO_EVENT_WPS_ER_PIN:
    Serial.println("WiFi Protected Setup (WPS): pin code in enrollee mode");
    break;
  case ARDUINO_EVENT_WIFI_AP_START:
    Serial.println("WiFi access point started");
    break;
  case ARDUINO_EVENT_WIFI_AP_STOP:
    Serial.println("WiFi access point  stopped");
    break;
  case ARDUINO_EVENT_WIFI_AP_STACONNECTED:
    Serial.println("Client connected");
    break;
  case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED:
    Serial.println("Client disconnected");
    break;
  case ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED:
    Serial.println("Assigned IP address to client");
    break;
  case ARDUINO_EVENT_WIFI_AP_PROBEREQRECVED:
    Serial.println("Received probe request");
    break;
  case ARDUINO_EVENT_WIFI_AP_GOT_IP6:
    Serial.println("AP IPv6 is preferred");
    break;
  case ARDUINO_EVENT_WIFI_STA_GOT_IP6:
    Serial.println("STA IPv6 is preferred");
    break;
  case ARDUINO_EVENT_ETH_GOT_IP6:
    Serial.println("Ethernet IPv6 is preferred");
    break;
  case ARDUINO_EVENT_ETH_START:
    Serial.println("Ethernet started");
    break;
  case ARDUINO_EVENT_ETH_STOP:
    Serial.println("Ethernet stopped");
    break;
  case ARDUINO_EVENT_ETH_CONNECTED:
    Serial.println("Ethernet connected");
    break;
  case ARDUINO_EVENT_ETH_DISCONNECTED:
    Serial.println("Ethernet disconnected");
    break;
  case ARDUINO_EVENT_ETH_GOT_IP:
    Serial.println("Obtained IP address");
    break;
  default:
    Serial.println("Unknown WiFi event happened!");
    break;
  }
}

// AP fallback state (owned by the WiFi task only).
static bool _apActive = false;

// OTA watchdog state (owned by the WiFi task loop). P133: if an update
// task ever stalls with frozen progress, the loop below force-reboots.
// Mid-write reboots are recovery-safe: firmware writes target the
// INACTIVE ota partition (otadata untouched -> old app boots), and data
// writes only risk the config fs, which re-initializes on boot.
static uint8_t _last_ota_progress_pct = 255;
static uint32_t _last_ota_progress_ms = 0;

// Bring the setup AP up in AP+STA mode. Called the moment STA fails (and
// again whenever the STA drops later). The AP STAYS UP while the STA
// retries in the background, so the panel is always reachable at
// http://192.168.1.1 when its configured network is unreachable.
static void ensureAP() {
  if (_apActive) {
    return;
  }
  IPAddress local_ip(192, 168, 1, 1);
  IPAddress subnet(255, 255, 255, 0);
  WiFi.mode(WIFI_AP_STA);
  if (WiFi.softAP("NSPanelCore", NULL) && WiFi.softAPConfig(local_ip, local_ip, subnet)) {
    Serial.println("Soft-AP started: SSID 'NSPanelCore', http://192.168.1.1");
    _apActive = true;
    // Start the first WiFi scan right away so the setup page has networks
    // to show on its first poll.
    WiFi.scanNetworks(true);
    webMan.init(NSPanelCoreFirmwareVersion);
  } else {
    LOG_ERROR("Failed to start Soft-AP!");
  }
}

// Drop the setup AP once the STA has joined the configured network.
// Restored automatically by ensureAP() if the STA drops again later.
static void dropAPOnceSTAConnected() {
  if (!_apActive || !WiFi.isConnected()) {
    return;
  }
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  _apActive = false;
  Serial.println("WiFi connected - setup AP stopped.");
}

void taskManageWifiAndMqtt(void *param) {
  LOG_INFO("taskWiFiMqttHandler started!");
  Serial.print("Configured to connect to WiFi: ");
  Serial.println(config.wifi_ssid.c_str());
  Serial.print("with hostname: ");
  Serial.println(config.wifi_hostname.c_str());
  WiFi.onEvent(onWiFiEvent);

  if (!NSPMConfig::instance->wifi_ssid.empty()) {
    for (;;) {
      // P133 seatbelt: an OTA task that stalls with frozen progress gets
      // force-rebooted instead of wedging the panel into a dead state.
      if (WebManager::getState() == WebManagerState::UPDATING_FIRMWARE ||
          WebManager::getState() == WebManagerState::UPDATING_LITTLEFS) {
        uint8_t ota_pct = WebManager::getUpdateProgress();
        if (ota_pct != _last_ota_progress_pct) {
          _last_ota_progress_pct = ota_pct;
          _last_ota_progress_ms = millis();
        } else if (_last_ota_progress_pct != 255 && millis() - _last_ota_progress_ms > 120000) {
          LOG_ERROR("OTA progress frozen for 120s — forcing reboot to recover.");
          Serial.println("OTA stalled — rebooting.");
          ESP.restart();
        }
      } else {
        _last_ota_progress_pct = 255;
      }
      if (!WiFi.isConnected()) {
        LOG_ERROR("WiFi not connected!");
        Serial.println("WiFi not connected!");
        // AP comes up IMMEDIATELY in AP+STA mode and stays up while the
        // STA retries in the background — the panel is always reachable
        // at http://192.168.1.1 when its configured network is unreachable.
        ensureAP();
        WiFi.setHostname(config.wifi_hostname.c_str());
        for (uint8_t wifi_connect_tries = 0; wifi_connect_tries < 10 && !WiFi.isConnected(); wifi_connect_tries++) {
          Serial.print("Connecting to WiFi ");
          Serial.println(config.wifi_ssid.c_str());
          WiFi.begin(config.wifi_ssid.c_str(), config.wifi_psk.c_str());
          vTaskDelay(2000 / portTICK_PERIOD_MS);
          if (!WiFi.isConnected()) {
            LOG_ERROR("Failed to connect to WiFi. Will try again in 5 seconds");
            Serial.println("Failed to connect to WiFi. Will try again in 5 seconds");
            vTaskDelay(5000 / portTICK_PERIOD_MS);
          }
        }

        if (WiFi.isConnected()) {
          dropAPOnceSTAConnected();
          Serial.println("Connected to WiFi!");
          LOG_INFO("Connected to WiFi ", config.wifi_ssid.c_str());
          Serial.print("Connected to WiFi ");
          Serial.println(config.wifi_ssid.c_str());
          LOG_INFO("IP Address: ", WiFi.localIP().toString());
          LOG_INFO("Netmask:    ", WiFi.subnetMask().toString());
          LOG_INFO("Gateway:    ", WiFi.gatewayIP().toString());

          // We successfully connected to WiFi. Init the rest of the components.
          webMan.init(NSPanelCoreFirmwareVersion);
          mqttManager.start();
        }
      }
      if (WiFi.isConnected() && MqttManager::connected()) {
        // P135: re-register periodically (every 5 min), not just once per
        // boot — the manager must always know the running version.
        static unsigned long lastPeriodicRegistration = 0;
        if (!InterfaceManager::hasRegisteredToManager || millis() - lastPeriodicRegistration > 300000) {
          sendMqttManagerRegistrationRequest();
          lastPeriodicRegistration = millis();
        }
        bool force_send_mqtt_update = false;
        // Reused across iterations — was `new JsonDocument` on every loop,
        // one alloc/free pair per second, forever.
        static JsonDocument status_report_doc;
        status_report_doc.clear();
        // P135: report the running version with EVERY status report — the
        // app's version display went permanently stale when the one-shot
        // registration was the only source.
        status_report_doc["version"] = NSPanelCoreFirmwareVersion;
        if (NSPanel::instance->getUpdateState()) {
          force_send_mqtt_update = true;
          status_report_doc["state"] = "updating_tft";
          status_report_doc["progress"] = NSPanel::instance->getUpdateProgress();
        } else if (WebManager::getState() == WebManagerState::UPDATING_FIRMWARE) {
          force_send_mqtt_update = true;
          status_report_doc["state"] = "updating_fw";
          status_report_doc["progress"] = WebManager::getUpdateProgress();
        } else if (WebManager::getState() == WebManagerState::UPDATING_LITTLEFS) {
          force_send_mqtt_update = true;
          status_report_doc["state"] = "updating_fs";
          status_report_doc["progress"] = WebManager::getUpdateProgress();
        }
        // Online/Offline state is handled in /status topic managed by MQTTManager.

        if (force_send_mqtt_update || millis() >= lastStatusReport + 30000) {
          char display_temp[7]; // Displayed temperature should NEVER have to be more than 7 chars. Example, 1000.0 is 6 chars, -100.0 is 6 chars. Neither should happen!
          std::snprintf(display_temp, sizeof(display_temp), "%.1f", averageTemperature);
          status_report_doc["rssi"] = WiFi.RSSI();
          status_report_doc["heap_used_pct"] = 100 - round((float(ESP.getFreeHeap()) / float(ESP.getHeapSize())) * 100);
          status_report_doc["mac"] = WiFi.macAddress();
          status_report_doc["temperature"] = display_temp;
          status_report_doc["ip"] = WiFi.localIP().toString();

          std::string warning_string = NSPanel::instance->getWarnings();
          status_report_doc["warnings"] = warning_string.c_str();

          MqttManager::publish(NSPMConfig::instance->mqtt_panel_temperature_topic, display_temp);

          char buffer[512];
          uint json_length = serializeJson(status_report_doc, buffer);
          MqttManager::publish(NSPMConfig::instance->mqtt_panel_status_topic, buffer, true);

          // std::string display_temp = std::to_string((int)round(temperature));
          std::string display_temp_display = display_temp;
          display_temp_display.append("°");
          PageManager::GetScreensaverPage()->updateRoomTemp(display_temp_display);

          lastStatusReport = millis();
        }
      }

      if (WiFi.isConnected()) {
        lastWiFiconnected = millis();
      }
      yield();
      vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
  } else {
    // No WiFi SSID configured: the setup AP runs forever.
    ensureAP();
    for (;;) {
      vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.print("Starting NSPanel Core firmware v. ");
  Serial.println(NSPanelCoreFirmwareVersion);
  vTaskDelay(250 / portTICK_PERIOD_MS);
  // Load config if any, and if it fails. Factory reset!
  if (!(config.init() && config.loadFromLittleFS())) {
    config.factoryReset();
  }

  // P176 MIGRATION: seed the NVS namespace the native (IDF) line reads —
  // "nspcfg" carries WiFi/MQTT/manager so the native firmware boots with
  // the panel's EXISTING settings, no setup AP, no manual re-entry.
  // Runs once: skipped when the native's "ssid" key is already present.
  {
    nvs_handle_t nh;
    if (nvs_open("nspcfg", NVS_READWRITE, &nh) == ESP_OK) {
      char probe[8];
      size_t plen = sizeof(probe);
      if (nvs_get_str(nh, "ssid", probe, &plen) != ESP_OK) {
        auto setS = [&](const char *key, const std::string &v) { nvs_set_str(nh, key, v.c_str()); };
        setS("ssid", NSPMConfig::instance->wifi_ssid);
        setS("psk", NSPMConfig::instance->wifi_psk);
        setS("hostname", NSPMConfig::instance->wifi_hostname);
        setS("mqtt_server", NSPMConfig::instance->mqtt_server);
        nvs_set_i32(nh, "mqtt_port", (int32_t)NSPMConfig::instance->mqtt_port);
        setS("mqtt_user", NSPMConfig::instance->mqtt_username);
        setS("mqtt_pass", NSPMConfig::instance->mqtt_password);
        setS("manager", NSPMConfig::instance->manager_address);
        nvs_set_i32(nh, "manager_port", (int32_t)NSPMConfig::instance->manager_port);
        setS("md5_fw", NSPMConfig::instance->md5_firmware);
        setS("md5_fs", NSPMConfig::instance->md5_data_file);
        setS("md5_tft", NSPMConfig::instance->md5_tft_file);
        nvs_set_u8(nh, "reverse_relays", NSPMConfig::instance->reverse_relays ? 1 : 0);
        nvs_set_i32(nh, "btn1_mode", (int32_t)NSPMConfig::instance->button1_mode);
        nvs_set_i32(nh, "btn2_mode", (int32_t)NSPMConfig::instance->button2_mode);
        setS("btn1_topic", NSPMConfig::instance->button1_mqtt_topic);
        setS("btn1_payload", NSPMConfig::instance->button1_mqtt_payload);
        setS("btn2_topic", NSPMConfig::instance->button2_mqtt_topic);
        setS("btn2_payload", NSPMConfig::instance->button2_mqtt_payload);
        if (nvs_commit(nh) == ESP_OK) {
          Serial.println("MIGRATION: panel config seeded into NVS for the native firmware");
        }
      }
      nvs_close(nh);
    }
  }

  // Setup logging
  logger.init(&(NSPMConfig::instance->mqtt_log_topic));
  logger.setLogLevel(static_cast<MqttLogLevel>(config.logging_level));

  mqttManager.init();
  ButtonManager::init();
  xTaskCreatePinnedToCore(readNTCTemperatureTask, "readTempTask", 5000, NULL, 0, NULL, CONFIG_ARDUINO_RUNNING_CORE);

  vTaskDelay(250 / portTICK_PERIOD_MS);
  LOG_INFO("Initializing NSPanel communication");
  if (nspanel.init()) {
    LOG_INFO("Successfully initiated NSPanel.");
  } else {
    LOG_ERROR("Failed to initiate NSPanel.");
  }
  vTaskDelay(500 / portTICK_PERIOD_MS);
  PageManager::init(); // Attach event callbacks

  LOG_INFO("Starting tasks");
  interfaceManager.init();

  pinMode(38, INPUT);
}

void loop() {
  taskManageWifiAndMqtt(NULL);
}
