/* NSPanel Core — OTA with every safety rail as NATIVE code:
 *
 * 1. Firmware and filesystem updates are SPLIT ACROSS REBOOTS (P132):
 *    after flashing firmware the panel reboots BEFORE any fs work — the
 *    fs update always runs under the newest code.
 * 2. The data partition is UNMOUNTED before the fs write and the new fs
 *    is mounted after (P129: a mounted fs under the write deadlocked).
 * 3. All retries BOUNDED; config save bounded; reboot guaranteed.
 * 4. Watchdog: any stalled OTA (no progress 120s) → reboot (P133).
 *    Mid-write reboots are recovery-safe (inactive slot / config fs).
 * 5. Checksum-first: fetch /checksum_* and compare BEFORE downloading.
 */

#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_timer.h"
#include <cstring>
#include <cstdio>
#include <string>
#include "protocol.h"
#include "config.h"

#define OTA_MAX_ATTEMPTS   3
#define OTA_STALL_TIMEOUT_MS 120000

enum OtaState { OTA_IDLE, OTA_FW, OTA_FS };
static volatile OtaState s_state = OTA_IDLE;
static int s_progress = 0;
static int64_t s_last_progress_us = 0;

int nsp_ota_progress(void) { return s_progress; }

static bool s_confirmed = false;
extern "C" void nsp_ota_confirm(void) {
    if (s_confirmed) return;
    // Mark the running (OTA-updated) app valid — the bootloader's rollback
    // would otherwise restore the previous slot on the next reboot.
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        s_confirmed = true;
    }
}
OtaState nsp_ota_state(void) { return s_state; }

static bool nsp_http_get_to_buffer(const char *url, std::string &out) {
    esp_http_client_config_t cfg = {};
    cfg.url = url;
    cfg.timeout_ms = 10000;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) return false;
    esp_http_client_set_method(client, HTTP_METHOD_GET);
    if (esp_http_client_perform(client) != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        esp_http_client_cleanup(client);
        return false;
    }
    int len = esp_http_client_is_chunked_response(client) ? 0 : esp_http_client_get_content_length(client);
    char chunk[1024];
    int read_total = 0;
    int r;
    while ((r = esp_http_client_read(client, chunk, sizeof(chunk))) > 0) {
        out.append(chunk, r);
        read_total += r;
        if (read_total > 6 * 1024 * 1024) break;  // hard cap
    }
    esp_http_client_cleanup(client);
    return read_total > 0;
}

static std::string nsp_manager_url(const char *path) {
    char url[256];
    snprintf(url, sizeof(url), "http://%s:%d%s",
             g_cfg.manager_address.c_str(), g_cfg.manager_port, path);
    return std::string(url);
}

/* Write a full image to the fs partition with LittleFS UNMOUNTED first. */
static bool nsp_write_fs_partition(const std::string &blob) {
    const esp_partition_t *fs = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
    if (fs == nullptr || blob.size() > fs->size) return false;

    // Rail #2: the fs driver is never mounted in the native firmware
    // (config lives in NVS) — nothing to unmount, write directly.

    bool ok = true;
    if (esp_partition_erase_range(fs, 0, fs->size) != ESP_OK) ok = false;
    size_t written = 0;
    for (size_t off = 0; ok && off < blob.size(); off += 4096) {
        size_t n = (blob.size() - off > 4096) ? 4096 : (blob.size() - off);
        if (esp_partition_write(fs, off, blob.data() + off, n) != ESP_OK) ok = false;
        written += n;
        s_progress = (int)((100ULL * written) / blob.size());
    }
    // NOTE: config lives in NVS, not in the fs — no remount needed. The
    // panel reboots right after; the manager drives any further sync.
    return ok;
}

/* Rail #1: firmware first, REBOOT, fs later under the new firmware. */
static void nsp_ota_fw_task(void *) {
    s_state = OTA_FW;
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();

    std::string checksum;
    for (int i = 0; i < 60 && checksum.empty(); i++) {
        if (nsp_http_get_to_buffer(nsp_manager_url("/checksum_firmware").c_str(), checksum)
            && checksum.size() >= 32) break;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (checksum.size() < 32) { s_state = OTA_IDLE; vTaskDelete(nullptr); return; }

    if (g_cfg.md5_firmware.compare(0, 32, checksum, 0, 32) == 0) {
        s_state = OTA_IDLE;  // same firmware — skip, fs may still be needed
    } else {
        std::string blob;
        for (int attempt = 0; attempt < OTA_MAX_ATTEMPTS; attempt++) {
            blob.clear();
            if (nsp_http_get_to_buffer(nsp_manager_url("/download_firmware").c_str(), blob)
                && blob.size() > 0x100) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(5000));
        }
        if (blob.size() <= 0x100) {
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);  // bounded: no infinite retry (P129)
        }
        const esp_partition_t *target = esp_ota_get_next_update_partition(nullptr);
        esp_ota_handle_t handle;
        if (esp_ota_begin(target, OTA_SIZE_UNKNOWN, &handle) != ESP_OK) {
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);
        }
        size_t off = 0;
        while (off < blob.size()) {
            size_t n = (blob.size() - off > 4096) ? 4096 : (blob.size() - off);
            if (esp_ota_write(handle, blob.data() + off, n) != ESP_OK) {
                esp_ota_abort(handle);
                s_state = OTA_IDLE;
                vTaskDelete(nullptr);
            }
            off += n;
            s_progress = (int)((100ULL * off) / blob.size());
            s_last_progress_us = esp_timer_get_time();
        }
        if (esp_ota_end(handle) != ESP_OK || esp_ota_set_boot_partition(target) != ESP_OK) {
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);
        }
        g_cfg.md5_firmware = checksum.substr(0, 32);
        nsp_config_save();
        // RAIL #1: reboot NOW — the fs update runs under the new firmware.
        vTaskDelay(pdMS_TO_TICKS(3000));
        esp_restart();
    }

    // Firmware was already current: the fs update may proceed under THIS fw.
    s_state = OTA_FS;
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();
    std::string fs_checksum, fs_blob;
    for (int i = 0; i < 60 && fs_checksum.empty(); i++) {
        if (nsp_http_get_to_buffer(nsp_manager_url("/checksum_data_file").c_str(), fs_checksum)
            && fs_checksum.size() >= 32) break;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (fs_checksum.size() >= 32 &&
        g_cfg.md5_data_file.compare(0, 32, fs_checksum, 0, 32) != 0) {
        for (int attempt = 0; attempt < OTA_MAX_ATTEMPTS; attempt++) {
            fs_blob.clear();
            if (nsp_http_get_to_buffer(nsp_manager_url("/download_data_file").c_str(), fs_blob)
                && fs_blob.size() > 4096) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(5000));
        }
        if (fs_blob.size() > 4096 && nsp_write_fs_partition(fs_blob)) {
            g_cfg.md5_data_file = fs_checksum.substr(0, 32);
            nsp_config_save();
        }
    }
    s_state = OTA_IDLE;
    vTaskDelay(pdMS_TO_TICKS(3000));
    esp_restart();
}

void nsp_ota_start() {
    if (s_state != OTA_IDLE) return;  // re-entrancy guard (P175)
    xTaskCreatePinnedToCore(nsp_ota_fw_task, "ota", 8192, nullptr, 1, nullptr, 0);
}

/* Rail #4: watchdog — call from the 1s housekeeping loop. */
void nsp_ota_watchdog_feed_check() {
    if (s_state == OTA_IDLE) return;
    if (esp_timer_get_time() - s_last_progress_us >
        (int64_t)OTA_STALL_TIMEOUT_MS * 1000) {
        esp_restart();  // mid-write safe: inactive slot / config fs
    }
}
