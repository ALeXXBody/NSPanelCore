#include "esp32-hal.h"
#include <ArduinoJson.h>
#include <ButtonManager.hpp>
#include <HttpLib.hpp>
#include <InterfaceConfig.hpp>
#include <Light.hpp>
#include <LightManager.hpp>
#include <MqttLog.hpp>
#include <MqttManager.hpp>
#include <NSPMConfig.h>
#include <Room.hpp>
#include <RoomManager.hpp>
#include <Scene.hpp>
#include <WiFi.h>
#include <map>
#include <string>

void RoomManager::init() {
  RoomManager::currentRoom = RoomManager::rooms.end();
  RoomManager::_lastReloadCommand = millis();
}

void RoomManager::performConfigReload() {
  if (RoomManager::_lastReloadCommand + 5000 >= millis()) {
    LOG_ERROR("Received reload command within 5 seconds of a reload. Ignoring command.");
    return;
  }

  LOG_DEBUG("Got reload command, reloading rooms.");
  RoomManager::loadAllRooms(true);
  RoomManager::_lastReloadCommand = millis();
}

void RoomManager::loadAllRooms(bool is_update) {
  bool save_new_config_to_littlefs_at_end = false;
  bool reboot_after_config_saved = false;
  // Stack-allocated (was `new JsonDocument` without delete — leaked the whole
  // config document on every config reload).
  JsonDocument roomDataStorage;
  JsonDocument *roomData = &roomDataStorage;
  uint8_t tries = 0;
  bool successDownloadingConfig = false;
  do {
    // Sometimes when running WiFi.macAddress garbage is returned.
    // Keep creation of download URL in the loop.
    std::string roomDataJsonUrl = "http://";
    roomDataJsonUrl.append(NSPMConfig::instance->manager_address);
    roomDataJsonUrl.append(":");
    roomDataJsonUrl.append(std::to_string(NSPMConfig::instance->manager_port));
    roomDataJsonUrl.append("/api/get_nspanel_config?mac=");
    roomDataJsonUrl.append(WiFi.macAddress().c_str());
    LOG_INFO("Trying to download config from: ", roomDataJsonUrl.c_str());
    successDownloadingConfig = HttpLib::DownloadJSON(roomDataJsonUrl.c_str(), roomData);

    if (roomData->size() == 0) {
      successDownloadingConfig = false; // The HTTP call succeeded but we got no data, do not count it as a success
    }

    if (!successDownloadingConfig) {
      tries++;
      LOG_ERROR("Failed to download config, will try again in 5 seconds.");
      vTaskDelay(5000 / portTICK_PERIOD_MS);

      // 30 failed tries to download config, restart and try again.
      if (tries == 30) {
        LOG_ERROR("Failed to download config, will restart and try again.");
        // NspanelManagerPage::setText("Restarting...");
        vTaskDelay(5000 / portTICK_PERIOD_MS);
        ESP.restart();
      }
    }
  } while (!successDownloadingConfig);
  // Config downloaded, process the raw data
  // The config also contains other config values for the interface. Populate InterfaceConfig
  // Guard every key: a missing key must NOT zero out a live value (that
  // blanked the backlight / crashed color-temp math on partial configs).
  InterfaceConfig::homeScreen = (*roomData).containsKey("home") ? (*roomData)["home"].as<uint16_t>() : InterfaceConfig::homeScreen;
  if ((*roomData).containsKey("default_page")) {
    InterfaceConfig::default_page = static_cast<DEFAULT_PAGE>((*roomData)["default_page"].as<uint8_t>());
  }
  {
    bool has_min = (*roomData).containsKey("color_temp_min");
    bool has_max = (*roomData).containsKey("color_temp_max");
    uint16_t cmin = has_min ? (*roomData)["color_temp_min"].as<uint16_t>() : InterfaceConfig::colorTempMin;
    uint16_t cmax = has_max ? (*roomData)["color_temp_max"].as<uint16_t>() : InterfaceConfig::colorTempMax;
    if (cmin < 1000) cmin = 1000;
    if (cmax > 10000) cmax = 10000;
    if (cmin < cmax && cmax > 0) {
      InterfaceConfig::colorTempMin = cmin;
      InterfaceConfig::colorTempMax = cmax;
    } else {
      LOG_ERROR("Ignoring invalid color_temp range from config.");
    }
  }
  if ((*roomData).containsKey("reverse_color_temp")) {
    InterfaceConfig::reverseColorTempSlider = (*roomData)["reverse_color_temp"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("raise_to_100_light_level")) {
    uint8_t _r2m = (*roomData)["raise_to_100_light_level"].as<uint8_t>();
    if (_r2m > 0) InterfaceConfig::raiseToMaxLightLevelAbove = _r2m;
    else LOG_ERROR("Ignoring out-of-range raise_to_100_light_level from config.");
  }
  if ((*roomData).containsKey("min_button_push_time")) {
    uint16_t _mbt = (*roomData)["min_button_push_time"].as<uint16_t>();
    if (_mbt > 0) InterfaceConfig::button_min_press_time = _mbt;
  }
  if ((*roomData).containsKey("button_long_press_time")) {
    uint16_t _blp = (*roomData)["button_long_press_time"].as<uint16_t>();
    if (_blp > 0) InterfaceConfig::button_long_press_time = _blp;
  }
  if ((*roomData).containsKey("special_mode_trigger_time")) {
    uint16_t _smt = (*roomData)["special_mode_trigger_time"].as<uint16_t>();
    if (_smt > 0) InterfaceConfig::special_mode_trigger_time = _smt;
  }
  if ((*roomData).containsKey("special_mode_release_time")) {
    uint16_t _smr = (*roomData)["special_mode_release_time"].as<uint16_t>();
    if (_smr > 0) InterfaceConfig::special_mode_release_time = _smr;
  }
  InterfaceConfig::mqtt_ignore_time = (*roomData).containsKey("mqtt_ignore_time") ? (*roomData)["mqtt_ignore_time"].as<uint16_t>() : InterfaceConfig::mqtt_ignore_time;
  if ((*roomData).containsKey("screen_dim_level")) {
    uint16_t _sdl = (*roomData)["screen_dim_level"].as<uint16_t>();
    if (_sdl >= 1 && _sdl <= 100) InterfaceConfig::screen_dim_level = (uint8_t)_sdl;
    else LOG_ERROR("Ignoring out-of-range screen_dim_level from config.");
  }
  if ((*roomData).containsKey("screensaver_dim_level")) {
    uint16_t _ssl = (*roomData)["screensaver_dim_level"].as<uint16_t>();
    if (_ssl <= 100) InterfaceConfig::screensaver_dim_level = (uint8_t)_ssl;
  }
  if ((*roomData).containsKey("screensaver_activation_timeout")) {
    uint16_t _sat = (*roomData)["screensaver_activation_timeout"].as<uint16_t>();
    if (_sat > 0) InterfaceConfig::screensaver_activation_timeout = _sat;
    else LOG_ERROR("Ignoring out-of-range screensaver_activation_timeout from config.");
  }
  if ((*roomData).containsKey("screensaver_mode")) {
    String _sm = (*roomData)["screensaver_mode"].as<String>();
    if (_sm.length() > 0) InterfaceConfig::screensaver_mode = _sm.c_str();
    else LOG_ERROR("Ignoring empty screensaver_mode from config.");
  }
  if ((*roomData).containsKey("clock_us_style")) {
    InterfaceConfig::clock_us_style = (*roomData)["clock_us_style"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("lock_to_default_room")) {
    InterfaceConfig::lock_to_default_room = (*roomData)["lock_to_default_room"].as<String>().equalsIgnoreCase("true");
  }
  NSPMConfig::instance->is_us_panel = (*roomData).containsKey("is_us_panel") ? (*roomData)["is_us_panel"].as<String>().equalsIgnoreCase("true") : NSPMConfig::instance->is_us_panel;
  if ((*roomData).containsKey("button1_mode")) {
    uint8_t _b1 = (*roomData)["button1_mode"].as<uint8_t>();
    if (_b1 <= 3) NSPMConfig::instance->button1_mode = static_cast<BUTTON_MODE>(_b1);
    else LOG_ERROR("Ignoring invalid button1_mode from config.");
  }
  if ((*roomData).containsKey("button2_mode")) {
    uint8_t _b2 = (*roomData)["button2_mode"].as<uint8_t>();
    if (_b2 <= 3) NSPMConfig::instance->button2_mode = static_cast<BUTTON_MODE>(_b2);
    else LOG_ERROR("Ignoring invalid button2_mode from config.");
  }
  if ((*roomData).containsKey("use_fahrenheit")) {
    NSPMConfig::instance->use_fahrenheit = (*roomData)["use_fahrenheit"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("temperature_calibration")) {
    NSPMConfig::instance->temperature_calibration = (*roomData)["temperature_calibration"].as<float>();
  }
  if ((*roomData).containsKey("reverse_relays")) {
    NSPMConfig::instance->reverse_relays = (*roomData)["reverse_relays"].as<String>().equalsIgnoreCase("true");
  }
  // Home widget flags default to visible when the manager predates them.
  if ((*roomData).containsKey("show_home_scenes")) {
    InterfaceConfig::show_home_scenes = (*roomData)["show_home_scenes"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("show_home_ceiling")) {
    InterfaceConfig::show_home_ceiling = (*roomData)["show_home_ceiling"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("show_home_table")) {
    InterfaceConfig::show_home_table = (*roomData)["show_home_table"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("show_home_kelvin")) {
    InterfaceConfig::show_home_kelvin = (*roomData)["show_home_kelvin"].as<String>().equalsIgnoreCase("true");
  }
  if ((*roomData).containsKey("button1_mqtt_topic")) {
    NSPMConfig::instance->button1_mqtt_topic = (*roomData)["button1_mqtt_topic"].as<String>().c_str();
  }
  if ((*roomData).containsKey("button1_mqtt_payload")) {
    NSPMConfig::instance->button1_mqtt_payload = (*roomData)["button1_mqtt_payload"].as<String>().c_str();
  }
  if ((*roomData).containsKey("button2_mqtt_topic")) {
    NSPMConfig::instance->button2_mqtt_topic = (*roomData)["button2_mqtt_topic"].as<String>().c_str();
  }
  if ((*roomData).containsKey("button2_mqtt_payload")) {
    NSPMConfig::instance->button2_mqtt_payload = (*roomData)["button2_mqtt_payload"].as<String>().c_str();
  }

  if ((*roomData).containsKey("relay1_default_mode")) {
    bool relay1_default_mode = (*roomData)["relay1_default_mode"].as<String>().equalsIgnoreCase("true");
    if (NSPMConfig::instance->relay1_default_mode != relay1_default_mode) {
      LOG_INFO("Saving new relay 1 default mode: ", relay1_default_mode ? "ON" : "OFF");
      NSPMConfig::instance->relay1_default_mode = relay1_default_mode;
      save_new_config_to_littlefs_at_end = true;
    }
  }

  if ((*roomData).containsKey("relay2_default_mode")) {
    bool relay2_default_mode = (*roomData)["relay2_default_mode"].as<String>().equalsIgnoreCase("true");
    if (NSPMConfig::instance->relay2_default_mode != relay2_default_mode) {
      LOG_INFO("Saving new relay 2 default mode: ", relay2_default_mode ? "ON" : "OFF");
      NSPMConfig::instance->relay2_default_mode = relay2_default_mode;
      save_new_config_to_littlefs_at_end = true;
    }
  }

  if ((*roomData).containsKey("name") && (*roomData)["name"].as<String>().length() > 0) {
    if (NSPMConfig::instance->wifi_hostname.compare((*roomData)["name"].as<String>().c_str()) != 0) {
      save_new_config_to_littlefs_at_end = true;
      reboot_after_config_saved = true;
      NSPMConfig::instance->wifi_hostname = (*roomData)["name"].as<String>().c_str();
      LOG_DEBUG("Name has changed. Restarting.");
    }
  } else if (!(*roomData).containsKey("name")) {
    LOG_ERROR("Config has no name; keeping current hostname.");
  } else {
    LOG_ERROR("Ignoring empty name from config; keeping current hostname.");
  }

  if (save_new_config_to_littlefs_at_end) {
    while (!NSPMConfig::instance->saveToLittleFS(false)) {
      vTaskDelay(1000 / portTICK_PERIOD_MS);
    }

    if (reboot_after_config_saved) {
      ESP.restart();
      vTaskDelay(portMAX_DELAY);
      vTaskDelete(NULL);
    }
  }

  // Load global scenes
  JsonVariant json_scenes = (*roomData)["scenes"];
  for (JsonPair scenePair : json_scenes.as<JsonObject>()) {
    bool existing_scene;
    Scene *newScene = InterfaceConfig::getSceneById(atoi(scenePair.key().c_str()));
    if (newScene == nullptr) {
      existing_scene = false;
      newScene = new Scene();
    } else {
      existing_scene = true;
    }
    newScene->room = nullptr;
    newScene->id = atoi(scenePair.key().c_str());
    newScene->name = scenePair.value()["name"] | "ERR-S";
    newScene->canSave = scenePair.value()["can_save"].as<String>().equalsIgnoreCase("true");
    newScene->callUpdateCallbacks();
    if (!existing_scene) {
      InterfaceConfig::global_scenes.push_back(newScene);
      LOG_TRACE("Loaded scene ", newScene->id, "::", newScene->name.c_str());
    }
  }

  for (auto it = InterfaceConfig::global_scenes.cbegin(); it != InterfaceConfig::global_scenes.cend();) {
    // Check if this light ID exist in JSON config
    bool scene_found = false;
    for (JsonPair jsonLightPair : json_scenes.as<JsonObject>()) {
      if (atoi(jsonLightPair.key().c_str()) == (*it)->getId()) {
        scene_found = true;
        break;
      }
    }

    if (!scene_found) {
      Scene *scene_to_remove = (*it);
      LOG_DEBUG("Removing global scene: ", scene_to_remove->getName().c_str(), ". ID: ", scene_to_remove->getId());
      it = InterfaceConfig::global_scenes.erase(it);
      scene_to_remove->callDeconstructCallbacks();
      delete scene_to_remove;
    } else {
      it++;
    }
  }

  // Init rooms
  for (uint16_t roomId : (*roomData)["rooms"].as<JsonArray>()) {
    if (InterfaceConfig::lock_to_default_room && roomId != InterfaceConfig::homeScreen) {
      continue;
    }
    LOG_INFO("Getting config for room ", roomId);
    Room *room = RoomManager::loadRoom(roomId, is_update);
    if (RoomManager::getRoomById(roomId) == nullptr) {
      // If a nullptr is returned, a room by that id was not found
      RoomManager::rooms.push_back(room);
    }
  }

  if (!is_update) {
    // Set currentRoom to the default room for this panel
    if (!RoomManager::goToRoomId(InterfaceConfig::homeScreen)) {
      LOG_ERROR("Failed to go to default room.");
      if (RoomManager::rooms.size() > 0) {
        LOG_WARNING("Navigating to first room instead of default room as that failed.");
        RoomManager::currentRoom = RoomManager::rooms.begin();
      } else {
        LOG_ERROR("No rooms loaded!");
      }
    }
  } else {
    // TODO: Implement function that remove any rooms currecntly loaded but not configured (ie. removed through manager)
    LOG_DEBUG("Calling roomChangedCallback");
    RoomManager::_callRoomChangeCallbacks(); // Call room change update to force an update for other components
  }

  // All rooms and lights has loaded, prep buttonmanager
  if (NSPMConfig::instance->button1_mode == BUTTON_MODE::DETACHED) {
    ButtonManager::button1_detached_mode_light = LightManager::getLightById((*roomData)["button1_detached_light"].as<uint16_t>());
    if (ButtonManager::button1_detached_mode_light != nullptr) {
      LOG_DEBUG("Button 1 detached mode light: ", ButtonManager::button1_detached_mode_light->getName().c_str());
    } else {
      LOG_ERROR("Coudln't find Button 1 detached mode light with ID: ", (*roomData)["button1_detached_light"].as<uint16_t>());
    }
  } else {
    ButtonManager::button1_detached_mode_light = nullptr;
  }
  if (NSPMConfig::instance->button2_mode == BUTTON_MODE::DETACHED) {
    ButtonManager::button2_detached_mode_light = LightManager::getLightById((*roomData)["button2_detached_light"].as<uint16_t>());
    if (ButtonManager::button2_detached_mode_light != nullptr) {
      LOG_DEBUG("Button 2 detached mode light: ", ButtonManager::button2_detached_mode_light->getName().c_str());
    } else {
      LOG_ERROR("Coudln't find Button 2 detached mode light with ID: ", (*roomData)["button2_detached_light"].as<uint16_t>());
    }
  } else {
    ButtonManager::button2_detached_mode_light = nullptr;
  }

  NSPMConfig::instance->successful_config_load = true;
}

Room *RoomManager::loadRoom(uint16_t roomId, bool is_update) {
  JsonDocument *roomData = new JsonDocument;
  uint8_t tries = 0;
  bool successDownloadingConfig = false;

  do {
    std::string roomDataJsonUrl = "http://";
    roomDataJsonUrl.append(NSPMConfig::instance->manager_address);
    roomDataJsonUrl.append(":");
    roomDataJsonUrl.append(std::to_string(NSPMConfig::instance->manager_port));
    roomDataJsonUrl.append("/api/get_nspanel_config/room/");
    roomDataJsonUrl.append(std::to_string(roomId));
    LOG_INFO("Downloading room config from: ", roomDataJsonUrl.c_str());

    successDownloadingConfig = HttpLib::DownloadJSON(roomDataJsonUrl.c_str(), roomData);

    if (!successDownloadingConfig) {
      tries++;
      LOG_ERROR("Failed to download config for room ", roomId, " will try again in 5 seconds.");
      vTaskDelay(5000 / portTICK_PERIOD_MS);

      // 30 failed tries to download config, restart and try again.
      if (tries == 30) {
        LOG_ERROR("Failed to download config for room ", roomId, ", will restart and try again.");
        // NspanelManagerPage::setText("Restarting...");
        vTaskDelay(5000 / portTICK_PERIOD_MS);
        ESP.restart();
      }
    }
  } while (!successDownloadingConfig);
  // Successfully downloaded config, proceed to process it
  // Load already existing room or if a nullptr was returned, create a new room.
  Room *newRoom = RoomManager::getRoomById(roomId);
  if (newRoom == nullptr) {
    newRoom = new Room();
  }
  newRoom->id = roomId;
  newRoom->name = (*roomData)["name"] | "ERR";

  // Load and init all lights for the room
  JsonVariant json_lights = (*roomData)["lights"];
  for (JsonPair lightPair : json_lights.as<JsonObject>()) {
    bool existing_light;
    Light *newLight = newRoom->getLightById(atoi(lightPair.key().c_str()));
    if (newLight == nullptr) {
      existing_light = false;
      newLight = new Light();
    } else {
      existing_light = true;
    }
    std::map<std::string, std::string> data;
    data["id"] = lightPair.key().c_str();
    for (JsonPair lightSettingsPair : lightPair.value().as<JsonObject>()) {
      data[lightSettingsPair.key().c_str()] = lightSettingsPair.value().as<String>().c_str();
    }
    newLight->initFromMap(data);

    //  If the light is new (ie. not updated from existing) push it into the correct list.
    if (!existing_light) {
      if (lightPair.value()["ceiling"] == true) {
        newRoom->ceilingLights.insert(std::make_pair(newLight->getId(), newLight));
      } else {
        newRoom->tableLights.insert(std::make_pair(newLight->getId(), newLight));
      }
    }
  }

  if (is_update) {
    for (auto it = newRoom->ceilingLights.cbegin(); it != newRoom->ceilingLights.cend();) {
      // Check if this light ID exist in JSON config
      bool light_id_found = false;
      for (JsonPair jsonLightPair : json_lights.as<JsonObject>()) {
        if (atoi(jsonLightPair.key().c_str()) == (*it).first) {
          light_id_found = true;
          break;
        }
      }

      if (!light_id_found) {
        Light *light_to_remove = (*it).second;
        LOG_DEBUG("Removing light: ", light_to_remove->getName().c_str(), ". ID: ", light_to_remove->getId());
        it = newRoom->ceilingLights.erase(it);
        light_to_remove->callDeconstructCallbacks();
        delete light_to_remove;
      } else {
        it++;
      }
    }

    for (auto it = newRoom->tableLights.cbegin(); it != newRoom->tableLights.cend();) {
      // Check if this light ID exist in JSON config
      bool light_id_found = false;
      for (JsonPair jsonLightPair : json_lights.as<JsonObject>()) {
        if (atoi(jsonLightPair.key().c_str()) == (*it).first) {
          light_id_found = true;
          break;
        }
      }

      if (!light_id_found) {
        Light *light_to_remove = (*it).second;
        LOG_DEBUG("Removing light: ", light_to_remove->getName().c_str(), ". ID: ", light_to_remove->getId());
        it = newRoom->tableLights.erase(it);
        light_to_remove->callDeconstructCallbacks();
        delete light_to_remove;
      } else {
        it++;
      }
    }

    for (auto it = newRoom->scenes.cbegin(); it != newRoom->scenes.cend();) {
      // Check if this scene ID still exists in JSON config (was json_lights — wrong map)
      bool scene_id_found = false;
      JsonVariant _scenesVar = (*roomData)["scenes"];
      for (JsonPair jsonScenePair : _scenesVar.as<JsonObject>()) {
        if (atoi(jsonScenePair.key().c_str()) == (*it)->getId()) {
          scene_id_found = true;
          break;
        }
      }

      if (!scene_id_found) {
        Scene *scene_to_remove = (*it);
        LOG_DEBUG("Removing scene: ", scene_to_remove->getName().c_str(), ". ID: ", scene_to_remove->getId());
        it = newRoom->scenes.erase(it);
        scene_to_remove->callDeconstructCallbacks();
        delete scene_to_remove;
      } else {
        it++;
      }
    }
  }

  // Load and init all the scenes for the room
  JsonVariant json_scenes = (*roomData)["scenes"];
  for (JsonPair scenePair : json_scenes.as<JsonObject>()) {
    bool existing_scene;
    Scene *newScene = newRoom->getSceneById(atoi(scenePair.key().c_str()));
    if (newScene == nullptr) {
      existing_scene = false;
      newScene = new Scene();
    } else {
      existing_scene = true;
    }
    newScene->room = newRoom;
    newScene->id = atoi(scenePair.key().c_str());
    newScene->name = scenePair.value()["name"] | "ERR-S";
    newScene->canSave = scenePair.value()["can_save"].as<String>().equalsIgnoreCase("true");
    newScene->callUpdateCallbacks();
    if (!existing_scene) {
      newRoom->scenes.push_back(newScene);
      LOG_TRACE("Loaded scene ", newScene->id, "::", newScene->name.c_str());
    }
  }

  delete roomData;
  return newRoom;
}

void RoomManager::goToNextRoom() {
  RoomManager::currentRoom++;
  if (RoomManager::currentRoom == RoomManager::rooms.end()) {
    RoomManager::currentRoom = RoomManager::rooms.begin();
  }
  RoomManager::_callRoomChangeCallbacks();
}

void RoomManager::goToPreviousRoom() {
  if (RoomManager::currentRoom == RoomManager::rooms.begin()) {
    RoomManager::currentRoom = RoomManager::rooms.end();
    RoomManager::currentRoom--;
  } else {
    RoomManager::currentRoom--;
  }
  RoomManager::_callRoomChangeCallbacks();
}

bool RoomManager::goToRoomId(uint16_t roomId) {
  bool foundRoom = false;
  for (std::list<Room *>::iterator it = RoomManager::rooms.begin(); it != RoomManager::rooms.end(); it++) {
    if ((*it)->id == roomId) {
      RoomManager::currentRoom = it;
      RoomManager::_callRoomChangeCallbacks();
      return true;
    }
  }

  LOG_ERROR("Did not find requested room. Will cancel operation.");
  return false;
}

Room *RoomManager::getRoomById(uint16_t roomId) {
  bool foundRoom = false;
  for (std::list<Room *>::iterator it = RoomManager::rooms.begin(); it != RoomManager::rooms.end(); it++) {
    if ((*it)->id == roomId) {
      return (*it);
    }
  }

  return nullptr;
}

void RoomManager::attachRoomChangeCallback(RoomManagerObserver *observer) {
  RoomManager::_roomChangeObservers.push_back(observer);
}

void RoomManager::detachRoomChangeCallback(RoomManagerObserver *observer) {
  RoomManager::_roomChangeObservers.remove(observer);
}

void RoomManager::_callRoomChangeCallbacks() {
  if (RoomManager::currentRoom != RoomManager::rooms.end()) {
    for (RoomManagerObserver *observer : RoomManager::_roomChangeObservers) {
      observer->roomChangedCallback();
    }
  }
}

bool RoomManager::hasValidCurrentRoom() {
  if (RoomManager::currentRoom == RoomManager::rooms.end()) {
    LOG_ERROR("Current room is invalid iterator!");
    return false;
  }
  return true;
}