#include "freertos/portmacro.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <HttpLib.hpp>
#include <MqttLog.hpp>
#include <MqttManager.hpp>
#include <NSPMConfig.h>
#include <NSPanel.hpp>
#include <NSPanelReturnData.h>
#include <WiFiClient.h>
#include <cstddef>
#include <esp_task_wdt.h>
#include <math.h>
#include <string>
#include <vector>

void NSPanel::goToPage(const char *page) {
  std::string cmd_string = "page ";
  cmd_string.append(page);
  this->_sendCommandWithoutResponse(cmd_string.c_str());
}

void NSPanel::setDimLevel(uint8_t dimLevel) {
  uint8_t dimLevelToPanel = dimLevel;
  std::string cmd_string = "dim=";
  cmd_string.append(std::to_string(dimLevelToPanel));
  this->_sendCommandWithoutResponse(cmd_string.c_str());
}

void NSPanel::setSleep(bool sleep) {
  this->_sendCommandWithoutResponse(sleep ? "sleep=1" : "sleep=0");
}

void NSPanel::setComponentText(const char *componentId, const char *text) {
  std::string cmd = componentId;
  cmd.append(".txt=\"");
  // Nextion text commands break on embedded quotes/backslashes; sanitize.
  for (const char *p = text; *p; ++p) {
    if (*p == '"' || *p == '\\') {
      cmd.push_back(' ');
    } else if ((unsigned char)*p >= 0x20) {
      cmd.push_back(*p);
    }
    if (cmd.size() > 200) {
      break; // cap insanely long strings (weather/cloud data)
    }
  }
  cmd.append("\"");
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setComponentVal(const char *componentId, int16_t value) {
  std::string cmd = componentId;
  cmd.append(".val=");
  cmd.append(std::to_string(value));
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setTimerTimeout(const char *componentId, uint16_t timeout) {
  std::string cmd = componentId;
  cmd.append(".tim=");
  cmd.append(std::to_string(timeout));
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setComponentPic(const char *componentId, uint8_t value) {
  std::string cmd = componentId;
  cmd.append(".pic=");
  cmd.append(std::to_string(value));
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setComponentPic1(const char *componentId, uint8_t value) {
  std::string cmd = componentId;
  cmd.append(".pic1=");
  cmd.append(std::to_string(value));
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setComponentForegroundColor(const char *componentId, uint value) {
  std::string cmd = componentId;
  cmd.append(".pco=");
  cmd.append(std::to_string(value));
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::setComponentVisible(const char *componentId, bool visible) {
  std::string cmd = "vis ";
  cmd.append(componentId);
  cmd.append(",");
  cmd.append(visible ? "1" : "0");
  this->_sendCommandWithoutResponse(cmd.c_str());
}

void NSPanel::sendCustomCommand(const char *cmd) {
  this->_sendCommandWithoutResponse(cmd);
}

int NSPanel::getComponentIntVal(const char *componentId) {
  // Wait for command queue to clear (bounded — don't let a busy command
  // queue stall slider reads for seconds).
  unsigned long startDrain = millis();
  while (millis() - startDrain < 250) {
    if (xSemaphoreTake(this->_mutexCommandQueue, 10 / portTICK_PERIOD_MS) != pdTRUE) {
      break;
    }
    size_t queued = this->_commandQueue.size();
    xSemaphoreGive(this->_mutexCommandQueue);
    if (queued == 0) {
      break;
    }
    vTaskDelay(10 / portTICK_PERIOD_MS);
  }

  if (xSemaphoreTake(this->_mutexReadSerialData, 1000 / portTICK_PERIOD_MS) != pdTRUE) {
    LOG_ERROR("Failed to get Serial read mutex when reading response from panel!");
    return -255;
  }

  this->_clearSerialBuffer();

  std::string cmd = "get ";
  cmd.append(componentId);
  cmd.append(".val");
  this->_sendRawCommand(cmd.c_str(), cmd.length());

  // Wait for data to become available
  int value = -1;
  unsigned long _startWait = millis();
  while (Serial2.available() == 0) {
    vTaskDelay(2 / portTICK_PERIOD_MS);

    // 1.5 second timeout for reading data.
    if (millis() >= _startWait + 1500) {
      LOG_ERROR("1.5 second timeout while getting int value from display trigged. Return -253");
      value = -253;
      break;
    }
  }

  if (Serial2.available() > 0 && Serial2.read() == 0x71) {
    value = Serial2.read();
    value += Serial2.read() << 8;
    value += Serial2.read() << 16;
    value += Serial2.read() << 24;
    this->_clearSerialBuffer();
  } else {
    LOG_ERROR("Failed to get response, not expected return data.");
    value = -254;
  }

  xSemaphoreGive(this->_mutexReadSerialData);
  return value;
}

void NSPanel::restart() {
  this->_sendCommandWithoutResponse("rest");
}

bool NSPanel::init() {
  NSPanel::instance = this;
  this->_mutexReadSerialData = xSemaphoreCreateMutex();
  this->_mutexWriteSerialData = xSemaphoreCreateMutex();
  this->_mutexCommandQueue = xSemaphoreCreateMutex();
  this->_rxBuffer.reserve(128);
  this->_writeCommandsToSerial = true;
  this->_isUpdating = false;
  this->_update_progress = 0;

  Serial2.setTxBufferSize(256);
  Serial2.setRxBufferSize(256);
  Serial2.begin(115200, SERIAL_8N1, 17, 16);
  // Clear Serial2 read buffer
  // this->_clearSerialBuffer();

  // Pin 4 controls screen on/off.
  pinMode(4, OUTPUT);
  digitalWrite(4, HIGH); // Turn off power to the display
  vTaskDelay(1000 / portTICK_PERIOD_MS);
  digitalWrite(4, LOW); // Turn on power to the display
  vTaskDelay(1000 / portTICK_PERIOD_MS);

  // Drain any boot chatter from the display so the handshake below reads a
  // clean reply. (There used to be a 2.5 s wait here for a magic "NSPM"
  // string that no display firmware sends — dead logic, removed.)
  unsigned long silence_start = millis();
  while (millis() - silence_start < 1500) {
    while (Serial2.available() > 0) {
      Serial2.read();
      silence_start = millis();
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexWriteSerialData, portMAX_DELAY)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial write mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexReadSerialData, portMAX_DELAY)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial read mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  LOG_INFO("Trying to connect to display."); // Send bogus to the panel to make is "clear" any reading state
  Serial2.print("DRAKJHSUYDGBNCJHGJKSHBDN");
  NSPanel::_sendCommandEndSequence();
  vTaskDelay(10 / portTICK_PERIOD_MS); // Was a unit-bug mix of microseconds and ticks; 10ms is ample for the panel to process a baud change.
  // Clear Serial2 read buffer
  while (Serial2.available() > 0) {
    Serial2.read();
    if (Serial2.available() == 0) {
      vTaskDelay(250 / portTICK_PERIOD_MS);
    }
  }

  LOG_DEBUG("Sending final connect to panel");
  // A live display answers the connect handshake (typically "comok ...").
  // Retry a few times: a slow-booting screen needs a moment after its
  // power cycle. Any non-empty reply proves the serial link works.
  this->_display_ready = false;
  for (uint8_t attempt = 0; attempt < 3 && !this->_display_ready; attempt++) {
    Serial2.print("connect");
    NSPanel::_sendCommandEndSequence();
    vTaskDelay(1000 / portTICK_PERIOD_MS);
    std::string reply_data = "";
    unsigned long reply_deadline = millis() + 1000;
    while ((long)(reply_deadline - millis()) > 0) {
      while (Serial2.available() > 0) {
        reply_data.push_back((char)Serial2.read());
      }
      if (!reply_data.empty() && Serial2.available() == 0) {
        vTaskDelay(25 / portTICK_PERIOD_MS);
        if (Serial2.available() == 0) break;
      } else {
        vTaskDelay(25 / portTICK_PERIOD_MS);
      }
    }
    while (reply_data.length() > 3 && reply_data.back() == (char)0xFF) {
      reply_data.pop_back(); // Strip Nextion 0xFF terminators for the log.
    }
    if (!reply_data.empty()) {
      LOG_INFO("Got reply from display: ", reply_data.c_str());
      this->_display_ready = true;
    } else {
      LOG_WARNING("No reply from display on connect attempt ", String(attempt + 1).c_str());
      vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
  }

  if (NSPMConfig::instance->md5_tft_file.empty()) {
    LOG_WARNING("No stored MD5 for TFT. Is the panel flashed with NSPanel Core TFT?");
    // LOG_ERROR("TFT file not flashed! Will not init NSPanel communication further.");
    // return false;
  }

  LOG_INFO("Trying to init NSPanel.");
  xTaskCreatePinnedToCore(_taskSendCommandQueue, "taskSendCommandQueue", 5000, NULL, 1, &this->_taskHandleSendCommandQueue, CONFIG_ARDUINO_RUNNING_CORE);
  this->_startListeningToPanel();

  // Connect to display and start it
  this->restart();
  vTaskDelay(250 / portTICK_PERIOD_MS);
  this->_sendCommandWithoutResponse("bkcmd=0");
  this->_sendCommandWithoutResponse("sleep=0");
  this->_sendCommandWithoutResponse("bkcmd=0");
  this->_sendCommandWithoutResponse("sleep=0");

  xSemaphoreGive(NSPanel::instance->_mutexWriteSerialData);
  xSemaphoreGive(NSPanel::instance->_mutexReadSerialData);
  Serial2.onReceive(NSPanel::_onSerialData, false);
  LOG_INFO("NSPanel::init complete.");
  return this->_display_ready;
}

void NSPanel::_startListeningToPanel() {
  xTaskCreatePinnedToCore(_taskProcessPanelOutput, "taskProcessPanelOutput", 5000, NULL, 1, &this->_taskHandleProcessPanelOutput, CONFIG_ARDUINO_RUNNING_CORE);
}

void NSPanel::_stopListeningToPanel() {
  if (this->_taskHandleProcessPanelOutput != NULL) {
    vTaskDelete(this->_taskHandleProcessPanelOutput);
    this->_taskHandleProcessPanelOutput = NULL;
  }
}

void NSPanel::_sendCommandWithoutResponse(const char *command) {
  NSPanelCommand cmd;
  cmd.command = command;
  this->_addCommandToQueue(cmd);
}

void NSPanel::_sendCommandEndSequence() {
  // Nextion terminator, sent as a single write followed by the command bytes.
  // Do NOT call Serial2.flush() here: it blocks until the UART physically
  // drains (~1.5-3ms per command at 115200) and serializes every widget update.
  // The hardware TX ring buffer handles queueing transparently.
  static const uint8_t terminator[3] = {0xFF, 0xFF, 0xFF};
  Serial2.write(terminator, sizeof(terminator));
}

void NSPanel::_addCommandToQueue(NSPanelCommand command) {
  if (!NSPanel::instance->_writeCommandsToSerial) {
    return;
  }

  if (this->_taskHandleSendCommandQueue != NULL) {
    if (xSemaphoreTake(this->_mutexCommandQueue, 1000 / portTICK_PERIOD_MS) == pdTRUE) {
      this->_commandQueue.push(command);
      xSemaphoreGive(this->_mutexCommandQueue);
      xTaskNotifyGive(this->_taskHandleSendCommandQueue);
    }
  } else {
    LOG_ERROR("Task '", pcTaskGetName(xTaskGetCurrentTaskHandle()), "' is trying to add command to queue before a queue exists!");
  }
}

void NSPanel::_taskSendCommandQueue(void *param) {
  LOG_INFO("Starting taskSendCommandQueue.");
  for (;;) {
    // Wait for commands
    if (ulTaskNotifyTake(pdTRUE, portMAX_DELAY)) {
      while (NSPanel::_writeCommandsToSerial == false) {
        vTaskDelay(50 / portTICK_PERIOD_MS);
      }

      // Process all commands in queue
      while (true) {
        NSPanelCommand cmd;
        if (xSemaphoreTake(NSPanel::instance->_mutexCommandQueue, 1000 / portTICK_PERIOD_MS) != pdTRUE) {
          break; // Notifications will wake us up again if more commands arrived.
        }
        if (NSPanel::instance->_commandQueue.size() == 0) {
          xSemaphoreGive(NSPanel::instance->_mutexCommandQueue);
          break;
        }
        cmd = NSPanel::instance->_commandQueue.front();
        xSemaphoreGive(NSPanel::instance->_mutexCommandQueue);
        NSPanel::instance->_sendCommand(&cmd);
        // Command processed, remove it from queue
        xSemaphoreTake(NSPanel::instance->_mutexCommandQueue, portMAX_DELAY);
        NSPanel::instance->_commandQueue.pop();
        xSemaphoreGive(NSPanel::instance->_mutexCommandQueue);
        vTaskDelay(COMMAND_SEND_WAIT_MS / portTICK_PERIOD_MS);
      }
    }
  }
}

void NSPanel::attachTouchEventCallback(void (*callback)(uint8_t, uint8_t, bool)) {
  NSPanel::_touchEventCallback = callback;
}

void NSPanel::attachSleepCallback(void (*callback)()) {
  NSPanel::_sleepCallback = callback;
}

void NSPanel::attachWakeCallback(void (*callback)()) {
  NSPanel::_wakeCallback = callback;
}

void IRAM_ATTR NSPanel::_onSerialData(void) {
  if (xSemaphoreTake(NSPanel::instance->_mutexReadSerialData, 5 * portTICK_PERIOD_MS) != pdTRUE) {
    // Another task is busy with the UART. The next UART event will retry.
    return;
  }

  // _onSerialData runs in the highest-priority UART event task — no sleeps and
  // no blocking calls allowed or every other task in the system (and the
  // 256-byte RX ring buffer) suffers. Read what is available in chunks, append
  // to the frame assembler and return. Incomplete frames simply keep waiting
  // in _rxBuffer until their terminator arrives in a later event.
  uint8_t data[64];
  int available = Serial2.available();

  while (available > 0) {
    int to_read = (available < (int)sizeof(data)) ? available : (int)sizeof(data);
    int n = Serial2.read(data, to_read);
    if (n <= 0) {
      break;
    }

    for (int i = 0; i < n; i++) {
      NSPanel::instance->_rxBuffer.push_back((char)data[i]);
      if (data[i] == 0xFF) {
        NSPanel::instance->_rxFFCounter++;
        if (NSPanel::instance->_rxFFCounter >= 3) { // End of command, push it over to the processing task
          NSPanel::instance->_processQueue.push(NSPanel::instance->_rxBuffer);
          NSPanel::instance->_rxBuffer.clear();
          NSPanel::instance->_rxFFCounter = 0;
          if (NSPanel::instance->_taskHandleProcessPanelOutput != NULL) {
            xTaskNotifyGive(NSPanel::instance->_taskHandleProcessPanelOutput);
          }
        }
      } else {
        NSPanel::instance->_rxFFCounter = 0;
      }
    }

    available = Serial2.available();
  }

  xSemaphoreGive(NSPanel::instance->_mutexReadSerialData);
}

void NSPanel::_taskProcessPanelOutput(void *param) {
  for (;;) {
    // Wait for things that needs processing
    if (ulTaskNotifyTake(pdTRUE, portMAX_DELAY)) {
      while (!NSPanel::instance->_processQueue.empty()) {
        std::vector<char> itemPayload = NSPanel::instance->_processQueue.front();

        // Select correct action depending on type of event
        if (!itemPayload.empty()) {
          switch (itemPayload[0]) {
          case NEX_OUT_TOUCH_EVENT:
            if (itemPayload.size() >= 4) {
              if (NSPanel::_touchEventCallback != nullptr) {
                NSPanel::_touchEventCallback(itemPayload[1], itemPayload[2], itemPayload[3] == 0x01);
              }
            } else {
              LOG_ERROR("Read nextion touch event but there wasn't enough data to process.");
            }
            break;

          case NEX_OUT_SLEEP:
          case NEX_OUT_ENTERED_AUTO_SLEEP:
            if (NSPanel::_sleepCallback != nullptr) {
              NSPanel::_sleepCallback();
            }
            break;

          case NEX_OUT_WAKE:
          case NEX_OUT_LEFT_AUTO_SLEEP:
            if (NSPanel::_wakeCallback != nullptr) {
              NSPanel::_wakeCallback();
            }
            break;

          default:
            LOG_TRACE("Read type ", String(itemPayload[0], HEX).c_str());
            break;
          }
        }

        // Done with item, pop it off the queue
        NSPanel::instance->_processQueue.pop();
        // Brief yield to let other tasks run between events.
        vTaskDelay(1 / portTICK_PERIOD_MS);
      }
    }
  }
}

void NSPanel::_sendCommand(NSPanelCommand *command) {
  // Clear buffer before sending
  NSPanel::_clearSerialBuffer();

  while (!NSPanel::instance->_writeCommandsToSerial) {
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }

  if (command->expectResponse) {
    if (xSemaphoreTake(this->_mutexReadSerialData, 500 / portTICK_PERIOD_MS) != pdTRUE) {
      LOG_ERROR("Failed to get serial read mutex! Will not continue call.");
      return;
    }
  }

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexWriteSerialData, portMAX_DELAY)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial write mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  Serial2.print(command->command.c_str());
  NSPanel::instance->_sendCommandEndSequence();
  this->_lastCommandSent = millis();
  if (command->expectResponse) {
    unsigned int start_wait = millis();
    while (Serial2.available() == 0) {
      vTaskDelay(20);
      if (millis() - start_wait >= command->timeout) {
        break;
      }
    }

    // Call callback function for command when data is available at Serial2
    command->callback(command);

    // Give back serial read mutex.
    xSemaphoreGive(this->_mutexReadSerialData);
  }

  xSemaphoreGive(this->_mutexWriteSerialData);
}

void NSPanel::_sendRawCommand(const char *command, int length) {
  while (!NSPanel::instance->_writeCommandsToSerial) {
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexWriteSerialData, portMAX_DELAY)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial write mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  for (int i = 0; i < length; i++) {
    Serial2.print(command[i]);
  }
  NSPanel::instance->_sendCommandEndSequence();
  xSemaphoreGive(this->_mutexWriteSerialData);
}

bool NSPanel::startOTAUpdate() {
  // Re-entrancy guard: a duplicate tft_update (MQTT QoS1 redelivery or a
  // manager retry) used to spawn a SECOND streaming task sharing the same
  // static buffer and serial bus — interleaved writes = corrupt flash.
  if (NSPanel::instance->getUpdateState()) {
    LOG_ERROR("TFT update already running; ignoring duplicate request.");
    return false;
  }
  if (xTaskCreatePinnedToCore(_taskUpdateTFTConfigOTA, "taskUpdateTFTConfigOTA", 10000, NULL, 1, NULL, CONFIG_ARDUINO_RUNNING_CORE) != pdPASS) {
    LOG_ERROR("Failed to create task to update TFT.");
    return false;
  }
  return true;
}

void NSPanel::_clearSerialBuffer(NSPanelCommand *cmd) {
  NSPanel::_clearSerialBuffer();
  cmd->callbackFinished = true;
}

void NSPanel::_clearSerialBuffer() {
  while (Serial2.available() > 0) {
    Serial2.read();
    if (Serial2.available() == 0) {
      vTaskDelay(50 / portTICK_PERIOD_MS);
    }
  }
}

uint16_t NSPanel::_readDataToString(std::string *data, uint32_t timeout, bool find_05_return) {
  uint16_t number_of_FF_bytes = 0;
  unsigned long start_read = millis();
  bool recevied_ff_flag = false;
  bool recevied_05_flag = false;
  while (millis() - start_read <= timeout) {
    while (millis() - start_read <= timeout && Serial2.available() <= 0) {
      vTaskDelay(100 / portTICK_PERIOD_MS);
    }

    if (Serial2.available() > 0) {
      uint8_t received_byte = Serial2.read();
      data->push_back(received_byte);
      if (received_byte == 0xFF) {
        number_of_FF_bytes++;

        if (number_of_FF_bytes >= 3) {
          recevied_ff_flag = true;
        }
      } else {
        number_of_FF_bytes = 0; // Reset counter as new data is provided, any previous 0xFF byte was part of payload
        recevied_ff_flag = false;
      }

      if (find_05_return && data->find(0x05) != std::string::npos) {
        recevied_05_flag = true;
      }

      if (recevied_05_flag || recevied_ff_flag) {
        break;
      }

      if (Serial2.available() == 0) {
        vTaskDelay(20 / portTICK_PERIOD_MS);
      }
    }
  }

  if (recevied_ff_flag) {
    // Remove last three 0xFF off of the end to only return payload
    *data = data->substr(0, data->length() - 3);
  }

  return data->length();
}

void NSPanel::_taskUpdateTFTConfigOTA(void *param) {
  LOG_INFO("Starting TFT update...");

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexReadSerialData, 1000 / portTICK_PERIOD_MS)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial read mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  while (true) {
    if (xSemaphoreTake(NSPanel::instance->_mutexWriteSerialData, portTICK_PERIOD_MS)) {
      break;
    } else {
      LOG_ERROR("Failed to take serial write mutex, trying again in 3 seconds.");
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }

  for (;;) {
    bool updateResult = NSPanel::_updateTFTOTA();
    if (updateResult) {
      LOG_INFO("Update of TFT successful, will reboot.");
      ESP.restart();
    } else {
      LOG_ERROR("Failed to update TFT. Will try again in 5 seconds.");
      vTaskDelay(5000 / portTICK_PERIOD_MS);
    }
  }

  vTaskDelete(NULL);
}

bool NSPanel::getUpdateState() {
  return this->_isUpdating;
}

uint8_t NSPanel::getUpdateProgress() {
  return this->_update_progress;
}

std::string NSPanel::getWarnings() {
  std::string return_string = "";
  if (!NSPanel::instance->_display_ready) {
    return_string.append("No response from the display. Check the display serial connection and power.\n");
  }
  return return_string;
}

bool NSPanel::ready() {
  return this->_display_ready;
}

bool NSPanel::_initTFTUpdate(int communication_baud_rate) {
  static int _tft_init_depth = 0;
  if (_tft_init_depth >= 7) {
    LOG_ERROR("TFT init failed after 7 attempts (two full baud cycles), giving up (no stack recursion).");
    _tft_init_depth = 0;
    return false;
  }
  _tft_init_depth++;
  LOG_INFO("Trying to initialize TFT update at baud ", communication_baud_rate);
  Serial2.updateBaudRate(communication_baud_rate);

  NSPanel::instance->_writeCommandsToSerial = false;
  NSPanel::instance->_update_progress = 0;
  NSPanel::instance->_isUpdating = true;

  // Stop all other tasks using the panel
  if (NSPanel::instance->_taskHandleSendCommandQueue != NULL) {
    vTaskDelete(NSPanel::instance->_taskHandleSendCommandQueue);
    NSPanel::instance->_taskHandleSendCommandQueue = NULL;
  }
  NSPanel::instance->_stopListeningToPanel();

  // Clear current read buffer
  Serial2.flush();

  LOG_INFO("Force restarting screen via power switch.");
  digitalWrite(4, HIGH); // Turn off power to the display
  vTaskDelay(1000 / portTICK_PERIOD_MS);
  digitalWrite(4, LOW); // Turn on power to the display
  vTaskDelay(3000 / portTICK_PERIOD_MS);

  // Send "connect" string to get data
  Serial2.print("DRAKJHSUYDGBNCJHGJKSHBDN");
  NSPanel::instance->_sendCommandEndSequence();
  vTaskDelay(10 / portTICK_PERIOD_MS); // Was a unit-bug mix of microseconds and ticks; 10ms is ample for the panel to process a baud change.
  // Clear Serial2 read buffer
  NSPanel::_clearSerialBuffer();
  vTaskDelay(50 / portTICK_PERIOD_MS);

  LOG_DEBUG("Sending connect to panel");
  Serial2.print("connect");
  NSPanel::instance->_sendCommandEndSequence();

  std::string comok_string = "";
  NSPanel::instance->_readDataToString(&comok_string, 10000, false);
  NSPanel::instance->_clearSerialBuffer();
  // Baud rotation: 115200 (normal) -> configured upload baud -> 9600.
  // 9600 matters: a corrupt system-data flash resets the display's stored
  // baud to the Nextion default, so the bootloader only hears 9600.
  auto _next_baud = [](int current) -> int {
    uint32_t up = NSPMConfig::instance->tft_upload_baud;
    if (current == 9600) return 115200;
    if ((uint32_t)current == up && up != 9600) return 9600;
    if (current == 115200) return (up != 115200 && up != 9600) ? (int)up : 9600;
    return 115200;
  };
  if (comok_string.length() > 3) {
    comok_string.erase(comok_string.length() - 3);
    LOG_DEBUG("Got comok: ", comok_string.c_str());
  } else if (_tft_init_depth < 6) {
    // We didn't receive a comok string back. Rotate through 115200 ->
    // upload baud -> 9600 (a corrupt flash resets the stored baud to the
    // Nextion default 9600). Budget allows two full cycles.
    int next = _next_baud(communication_baud_rate);
    LOG_ERROR("Didn't receive expected comok, got: '", comok_string.c_str(), "'. Will retry at ", next, ".");
    return NSPanel::_initTFTUpdate(next);
  } else {
    // No comok after repeated tries: the display is most likely stuck at
    // "System Data ERROR!" (corrupt TFT flash — the application that would
    // answer comok never runs). The ROM bootloader still accepts the upload
    // command right after a power cycle, so proceed to whmi-wris WITHOUT
    // comok as a last resort instead of failing forever at progress 0.
    // A failed 0x05 wait below still aborts the attempt.
    LOG_ERROR("No comok after retries — display may be bricked; attempting upload without handshake.");
  }

  // URL to download TFT file from
  std::string downloadUrl = "http://";
  downloadUrl.append(NSPMConfig::instance->manager_address);
  downloadUrl.append(":");
  downloadUrl.append(std::to_string(NSPMConfig::instance->manager_port));
  if (!NSPMConfig::instance->is_us_panel) {
    downloadUrl.append("/download_tft_eu");
  } else {
    downloadUrl.append("/download_tft_us");
  }

  LOG_INFO("Will download TFT file from: ", downloadUrl.c_str());
  unsigned long file_size = 0;
  while (file_size == 0) {
    file_size = HttpLib::GetFileSize(downloadUrl.c_str());
    if (file_size == 0) {
      LOG_ERROR("Failed to get file size for TFT flashing. Will try again.");
      vTaskDelay(500 / portTICK_PERIOD_MS);
    }
  }

  LOG_DEBUG("Will start TFT upload, TFT file size: ", file_size);
  // TODO: Detect if new protocol is not supported, in that case set flag in flash and restart and then continue flash with legacy mode.
  // Send whmi-wri command to initiate upload
  std::string commandString;
  if (NSPMConfig::instance->use_new_upload_protocol) {
    LOG_INFO("Starting upload using v1.2 protocol.");
    commandString = "whmi-wris ";
    commandString.append(std::to_string(file_size));
    commandString.append(",");
    commandString.append(std::to_string(NSPMConfig::instance->tft_upload_baud));
    commandString.append(",1");
  } else {
    LOG_INFO("Starting upload using v1.0 protocol.");
    commandString = "whmi-wri ";
    commandString.append(std::to_string(file_size));
    commandString.append(",");
    commandString.append(std::to_string(NSPMConfig::instance->tft_upload_baud));
    commandString.append(",1");
  }
  NSPanel::_clearSerialBuffer();
  vTaskDelay(500 / portTICK_PERIOD_MS);

  Serial2.print(commandString.c_str());
  NSPanel::instance->_sendCommandEndSequence();
  LOG_DEBUG("Sent TFT upload command: ", commandString.c_str());

  // Switch to desiered upload buad rate.
  vTaskDelay(50 / portTICK_PERIOD_MS);
  int32_t baud_diff = NSPMConfig::instance->tft_upload_baud - Serial2.baudRate();
  if (baud_diff < 0) {
    baud_diff = baud_diff / -1;
  }
  if (baud_diff >= 10) {
    LOG_INFO("Switching flash baud rate on Serial2 from ", Serial2.baudRate(), " to ", NSPMConfig::instance->tft_upload_baud);
    Serial2.updateBaudRate(NSPMConfig::instance->tft_upload_baud);
  }

  // Wait until Nextion returns okay to transmit tft
  LOG_DEBUG("Waiting for panel reponse (max 10 seconds).");
  unsigned long start_panel_response_wait = millis();
  while (Serial2.available() == 0 && start_panel_response_wait + 10000 > millis()) {
    vTaskDelay(250 / portTICK_PERIOD_MS);
  }

  uint8_t returnData = Serial2.read();
  if (returnData == 0x05) {
    LOG_INFO("Starting to write to TFT.");
    _tft_init_depth = 0;
  } else {
    LOG_ERROR("Failed to init upload to TFT. Got return code: ", String(returnData, HEX).c_str());
    while (Serial2.available() > 0) {
      LOG_INFO(String(Serial2.read(), HEX).c_str());
      vTaskDelay(5 / portTICK_PERIOD_MS);
    }
    LOG_ERROR("Will retry TFT upload init.");
    bool retry_ok = NSPanel::_initTFTUpdate(communication_baud_rate);
    if (!retry_ok) {
      _tft_init_depth = 0;
    }
    return retry_ok;
  }

  _tft_init_depth = 0;
  return true;
}

static void _powerCycleDisplay() {
  // Hard power-cycle the display so its bootloader is listening from a
  // clean reset. GPIO4 switches the screen supply on NSPanel hardware.
  // OFF time is deliberately long (3s): the display's capacitors hold
  // charge and a short cut only browns it out without a clean reset.
  digitalWrite(4, HIGH); // Turn off power to the display
  vTaskDelay(3000 / portTICK_PERIOD_MS);
  digitalWrite(4, LOW); // Turn on power to the display
  vTaskDelay(1200 / portTICK_PERIOD_MS);
}

static void _sendWhmiWrisAt(unsigned long file_size, uint32_t baud_param) {
  std::string cmd = "whmi-wris ";
  cmd.append(std::to_string(file_size));
  cmd.append(",");
  cmd.append(std::to_string(baud_param));
  cmd.append(",1");
  while (Serial2.available() > 0) { Serial2.read(); }
  Serial2.print(cmd.c_str());
  { static const uint8_t _term[3] = {0xFF, 0xFF, 0xFF}; Serial2.write(_term, 3); }
  LOG_DEBUG("Sent TFT upload command: ", cmd.c_str());
}

static void _sendWhmiWris(unsigned long file_size) {
  _sendWhmiWrisAt(file_size, NSPMConfig::instance->tft_upload_baud);
}

// Recovery probe: a bricked bootloader never answers "connect"/comok — it
// only reacts to the upload command itself. Power-cycle, send BOTH upload
// command variants (v1.2 `whmi-wris` first, then legacy v1.0 `whmi-wri`
// for bootloaders that predate v1.2), watching 4s each for ANY reply.
// Logs everything heard. Returns 2 on clean accept (0x05/0x08), 1 on any
// traffic (garbled reply = wrong baud but a LIVE display), 0 on silence.
// Sets *used_v1 when the legacy command was the one accepted, *traffic to
// the number of reply bytes heard.
static int _probeUploadAtBaud(int baud, unsigned long file_size, bool *used_v1, int *traffic) {
  *used_v1 = false;
  *traffic = 0;
  Serial2.updateBaudRate(baud);
  _powerCycleDisplay();
  _sendWhmiWris(file_size);
  unsigned long start = millis();
  int result = 0;
  while (millis() - start < 4000) {
    while (Serial2.available() > 0) {
      uint8_t c = Serial2.read();
      (*traffic)++;
      LOG_ERROR("Heard display at baud ", baud, " (v1.2): 0x", String(c, HEX).c_str());
      if (c == 0x05 || c == 0x08) {
        result = 2;
      } else if (result == 0) {
        result = 1;
      }
    }
    if (result == 2) {
      break;
    }
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }
  if (result == 2) {
    return 2;
  }
  // No clean accept to v1.2: try the legacy v1.0 command on the same
  // (already power-cycled) display.
  {
    std::string cmd = "whmi-wri ";
    cmd.append(std::to_string(file_size));
    cmd.append(",");
    cmd.append(std::to_string(NSPMConfig::instance->tft_upload_baud));
    cmd.append(",0");
    while (Serial2.available() > 0) { Serial2.read(); }
    Serial2.print(cmd.c_str());
    { static const uint8_t _term[3] = {0xFF, 0xFF, 0xFF}; Serial2.write(_term, 3); }
    LOG_DEBUG("Sent legacy TFT upload command: ", cmd.c_str());
  }
  start = millis();
  while (millis() - start < 4000) {
    while (Serial2.available() > 0) {
      uint8_t c = Serial2.read();
      (*traffic)++;
      LOG_ERROR("Heard display at baud ", baud, " (v1.0): 0x", String(c, HEX).c_str());
      if (c == 0x05 || c == 0x08) {
        *used_v1 = true;
        result = 2;
      } else if (result == 0) {
        result = 1;
      }
    }
    if (result == 2) {
      break;
    }
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }
  return result;
}

// Standard baud rates to try as neighbors of a baud that showed traffic
// (a garbled reply usually means we are 2x off in either direction).
static int _neighborBaud(int baud, bool up) {
  const int std[] = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600};
  const unsigned n = sizeof(std) / sizeof(std[0]);
  for (unsigned i = 0; i < n; i++) {
    if (std[i] != baud) {
      continue;
    }
    if (!up && i > 0) {
      return std[i - 1];
    }
    if (up && i + 1 < n) {
      return std[i + 1];
    }
    return 0;
  }
  return 0;
}

bool NSPanel::_updateTFTOTA() {
  LOG_INFO("_updateTFTOTA Started.");
  bool init_ok = NSPanel::_initTFTUpdate(115200);
  // File size is needed by the recovery probes below; fetch it once here
  // (the stream loop below reuses it).
  std::string downloadUrl = "http://";
  downloadUrl.append(NSPMConfig::instance->manager_address);
  downloadUrl.append(":");
  downloadUrl.append(std::to_string(NSPMConfig::instance->manager_port));
  if (!NSPMConfig::instance->is_us_panel) {
    downloadUrl.append("/download_tft_eu");
  } else {
    downloadUrl.append("/download_tft_us");
  }

  unsigned long file_size = 0;
  for (int _fss = 0; _fss < 60 && file_size == 0; _fss++) {
    file_size = HttpLib::GetFileSize(downloadUrl.c_str());
    if (file_size == 0) {
      LOG_ERROR("Failed to get file size for TFT flashing. Will try again.");
      vTaskDelay(2000 / portTICK_PERIOD_MS);
    } else {
      LOG_INFO("Will flash TFT, size: ", file_size);
    }
  }
  if (file_size == 0) {
    LOG_ERROR("TFT flash aborted: could not get file size.");
    return false;
  }
  if (!init_ok) {
    // No handshake on any rotated baud. A bricked bootloader never answers
    // "connect" — probe the upload command itself at each baud (power-cycle,
    // send v1.2 then legacy v1.0 immediately, watch for 0x05/0x08).
    // Pass 1: clean accept wins immediately. Pass 2: any baud with garbled
    // traffic gets its neighbors probed (wrong-baud replies decode as
    // garbage — the display is alive, we are just off frequency).
    // Last resort below streams anyway: silence-tolerant, worst case the
    // bytes go nowhere.
    const int bauds[] = {115200, 9600, 57600, 38400, 19200, 230400, 460800, 921600};
    const unsigned nbauds = sizeof(bauds) / sizeof(bauds[0]);
    int traffic_bauds[8];
    unsigned ntraffic = 0;
    for (unsigned i = 0; i < nbauds; i++) {
      bool used_v1 = false;
      int heard = 0;
      int res = _probeUploadAtBaud(bauds[i], file_size, &used_v1, &heard);
      if (res == 2) {
        LOG_ERROR("Display accepted upload at baud ", bauds[i], used_v1 ? " (v1.0)" : " (v1.2)", " — streaming.");
        Serial2.updateBaudRate(NSPMConfig::instance->tft_upload_baud);
        vTaskDelay(50 / portTICK_PERIOD_MS);
        init_ok = true;
        break;
      }
      if (res == 1 && ntraffic < 8) {
        traffic_bauds[ntraffic++] = bauds[i];
      }
    }
    if (!init_ok && ntraffic > 0) {
      LOG_ERROR("Display talks (garbled) — hunting neighbors.");
      for (unsigned i = 0; i < ntraffic && !init_ok; i++) {
        int neighbors[2] = {_neighborBaud(traffic_bauds[i], false), _neighborBaud(traffic_bauds[i], true)};
        for (unsigned j = 0; j < 2 && !init_ok; j++) {
          if (neighbors[j] == 0) {
            continue;
          }
          bool used_v1 = false;
          int heard = 0;
          int res = _probeUploadAtBaud(neighbors[j], file_size, &used_v1, &heard);
          if (res == 2) {
            LOG_ERROR("Display accepted upload at baud ", neighbors[j], used_v1 ? " (v1.0)" : " (v1.2)", " — streaming.");
            Serial2.updateBaudRate(NSPMConfig::instance->tft_upload_baud);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            init_ok = true;
          } else if (res == 1) {
            LOG_ERROR("Display still garbled at neighbor baud ", neighbors[j], " — will stream here anyway.");
            Serial2.updateBaudRate((uint32_t)neighbors[j]);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            _sendWhmiWrisAt(file_size, (uint32_t)neighbors[j]);
            init_ok = true;
          }
        }
      }
    }
    if (!init_ok) {
      LOG_ERROR("Proceeding with blind tolerant upload at 115200 (no handshake).");
      Serial2.updateBaudRate(115200);
      _powerCycleDisplay();
      _sendWhmiWris(file_size);
    }
  }
  unsigned long startWaitingForOKForNextChunk = 0;
  unsigned long nextStartWriteOffset = 0;
  unsigned long lastReadByte = 0;

  if (esp_get_free_heap_size() < 4096) {
    LOG_ERROR("Not enough free memory to flash device! Will reboot.");
    vTaskDelay(5000 / portTICK_PERIOD_MS);
    ESP.restart();
  }

  static uint8_t dataBuffer[4096];

  // Loop until break when all firmware has finished uploading (data available in stream == 0)
  while (true) {
    // Calculate next chunk size
    int next_write_size;
    if (file_size - lastReadByte > 4096) {
      next_write_size = 4096;
    } else {
      next_write_size = file_size - lastReadByte;
    }
    size_t bytesReceived = 0;
    int _dl_tries = 0;
    while (bytesReceived != next_write_size) {
      bytesReceived = HttpLib::DownloadChunk(dataBuffer, downloadUrl.c_str(), nextStartWriteOffset, next_write_size);
      if (bytesReceived != next_write_size) {
        LOG_ERROR("Bytes received: ", bytesReceived, " requested ", next_write_size, ". Will retry.");
        vTaskDelay(250 / portTICK_PERIOD_MS);
        if (++_dl_tries > 20) {
          LOG_ERROR("TFT chunk download failed 20 times, aborting OTA attempt.");
          return false;
        }
      } else {
        _dl_tries = 0;
      }
    }

    // v1.2 upload protocol (see Nextion docs): after each 4KB block the
    // device usually stays SILENT (continue streaming); it speaks only to
    // request a retransmit (0x08 + LE32 offset, typically after the first
    // block) or with a legacy 0x05. Silence/garbage therefore means
    // CONTINUE — never rewind/abort on it (that kills healthy uploads and
    // can never recover a display whose TX line is dead). 0x08 offsets are
    // validated; a short drain timeout keeps throughput up.
    Serial2.write(dataBuffer, bytesReceived);
    unsigned long _sent_up_to = nextStartWriteOffset + bytesReceived;
    NSPanel::instance->_update_progress = ((float)_sent_up_to / (float)file_size) * 100;

    std::string return_string;
    uint16_t recevied_bytes = NSPanel::instance->_readDataToString(&return_string, 500, true);
    if (!return_string.empty() && return_string[0] == 0x08) {
      // 0x08 frames carry a BINARY 4-byte LE offset — generic text heuristics
      // (FF terminator, 0x05 sniff) corrupt it (e.g. offset bytes containing
      // FF/05 produce fabricated offsets and silent write divergence).
      // Read exactly 4 more bytes, bounded, then decode.
      unsigned long _f8_start = millis();
      while (return_string.length() < 5) {
        if (Serial2.available() <= 0) {
          if (millis() - _f8_start > 5000) {
            LOG_ERROR("Incomplete 0x08 offset frame (got ", return_string.length(),
                      " of 5 bytes in 5 s) — aborting attempt, will re-init.");
            return false;
          }
          vTaskDelay(20 / portTICK_PERIOD_MS);
          continue;
        }
        return_string.push_back(Serial2.read());
      }
      uint32_t readNextOffset = return_string[1];
      readNextOffset |= return_string[2] << 8;
      readNextOffset |= return_string[3] << 16;
      readNextOffset |= return_string[4] << 24;
      if (readNextOffset > file_size) {
        LOG_ERROR("Panel requested offset ", readNextOffset, " beyond file size ", file_size,
                  " — aborting attempt.");
        return false;
      }
      // Offset 0 is a legitimate "start over" request in the v1.2 protocol.
      // Aborting here converted a recoverable hiccup into a half-written
      // display (the classic System Data ERROR brick).
      LOG_ERROR("Panel requested retransmit from offset ", readNextOffset, ".");
      nextStartWriteOffset = readNextOffset;
      lastReadByte = readNextOffset;
      continue;
    }
    // 0x05, empty (silence) or anything else: chunk accepted, move on.
    nextStartWriteOffset = _sent_up_to;
    lastReadByte = _sent_up_to;
    if (lastReadByte >= file_size) {
      NSPanel::instance->_update_progress = 100;
      LOG_INFO("TFT Upload complete, processed ", lastReadByte, " bytes.");
      break;
    }
    if (!return_string.empty() && return_string[0] != 0x05) {
      LOG_TRACE("Ignoring ", recevied_bytes, " bytes of non-ACK chatter from panel.");
    }
    vTaskDelay(20 / portTICK_PERIOD_MS); // pacing: don't overrun the display UART buffer
  }

  LOG_INFO("Getting TFT MD5 checksum to store in flash.");
  char checksum_holder[33];
  while (true) {
    std::string checksumUrl = "http://";
    checksumUrl.append(NSPMConfig::instance->manager_address);
    checksumUrl.append(":");
    checksumUrl.append(std::to_string(NSPMConfig::instance->manager_port));
    if (!NSPMConfig::instance->is_us_panel) {
      checksumUrl.append("/checksum_tft_file_eu");
    } else {
      checksumUrl.append("/checksum_tft_file_us");
    }
    if (HttpLib::GetMD5sum(checksumUrl.c_str(), checksum_holder)) {
      break;
    }
    vTaskDelay(1000 / portTICK_PERIOD_MS);
  }
  NSPMConfig::instance->md5_tft_file = checksum_holder;
  NSPMConfig::instance->saveToLittleFS(false);

  LOG_INFO("Will restart in 5 seconds.");
  vTaskDelay(5000 / portTICK_PERIOD_MS);
  ESP.restart();

  vTaskDelay(portMAX_DELAY);
  vTaskDelete(NULL);
  return false;
}
