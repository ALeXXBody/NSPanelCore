/* NSPanel Core — OTA with every safety rail as NATIVE code:
 *
 * 1. Firmware and filesystem updates are SPLIT ACROSS REBOOTS (P132):
 *    after flashing firmware the panel reboots BEFORE any fs work — the
 *    fs update always runs under the newest code.
 * 2. STREAMING WRITE (P179 fix): the image is written to flash AS IT
 *    ARRIVES from the HTTP stream. The old design buffered the whole
 *    ~1.4 MB blob in RAM first — impossible on a classic ESP32 (~300 KB
 *    heap): every attempt OOM-panicked and the panel rebooted back onto
 *    the same version forever.
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

/* Small responses only (checksums, manifest fragments) — 16 KB cap. */
static bool nsp_http_get_small(const char *url, std::string &out) {
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
    char chunk[512];
    int r;
    while ((r = esp_http_client_read(client, chunk, sizeof(chunk))) > 0) {
        out.append(chunk, r);
        if (out.size() > 16 * 1024) break;  // small-response cap
    }
    esp_http_client_cleanup(client);
    return out.size() > 0;
}

/* STREAMING download (P179): the body is handed to `sink` as it arrives;
 * nothing larger than one chunk (1 KB) is ever held in RAM.
 * Returns total bytes streamed (0 = failure). */
typedef bool (*nsp_stream_sink)(void *ctx, const uint8_t *data, size_t len);
static size_t nsp_http_stream(const char *url, nsp_stream_sink sink, void *ctx) {
    esp_http_client_config_t cfg = {};
    cfg.url = url;
    cfg.timeout_ms = 60000;  // P176: weak links need > 5 s per stage
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) return 0;
    esp_http_client_set_method(client, HTTP_METHOD_GET);
    if (esp_http_client_perform(client) != ESP_OK) {
        esp_http_client_cleanup(client);
        return 0;
    }
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        esp_http_client_cleanup(client);
        return 0;
    }
    uint8_t chunk[1024];
    size_t total = 0;
    int r;
    while ((r = esp_http_client_read(client, (char *)chunk, sizeof(chunk))) > 0) {
        if (!sink(ctx, chunk, (size_t)r)) {
            total = 0;
            break;
        }
        total += (size_t)r;
        s_last_progress_us = esp_timer_get_time();
    }
    esp_http_client_cleanup(client);
    return total;
}

static std::string nsp_manager_url(const char *path) {
    char url[256];
    snprintf(url, sizeof(url), "http://%s:%d%s",
             g_cfg.manager_address.c_str(), g_cfg.manager_port, path);
    return std::string(url);
}

/* ---- stream sinks ---- */

typedef struct { esp_ota_handle_t handle; bool ok; } fw_sink_ctx;
static bool fw_sink(void *vctx, const uint8_t *data, size_t len) {
    fw_sink_ctx *c = (fw_sink_ctx *)vctx;
    if (esp_ota_write(c->handle, data, len) != ESP_OK) { c->ok = false; return false; }
    return true;
}

typedef struct { const esp_partition_t *fs; size_t off; bool ok; } fs_sink_ctx;
static bool fs_sink(void *vctx, const uint8_t *data, size_t len) {
    fs_sink_ctx *c = (fs_sink_ctx *)vctx;
    if (esp_partition_write(c->fs, c->off, data, len) != ESP_OK) { c->ok = false; return false; }
    c->off += len;
    s_progress = (int)((100ULL * c->off) / c->fs->size);  // monotonic vs partition size
    return true;
}

/* Write a full image to the fs partition with LittleFS UNMOUNTED first. */
static bool nsp_write_fs_partition(const std::string &checksum) {
    const esp_partition_t *fs = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
    if (fs == nullptr) return false;

    // Rail #2: the fs driver is never mounted in the native firmware
    // (config lives in NVS) — nothing to unmount, write directly.
    if (esp_partition_erase_range(fs, 0, fs->size) != ESP_OK) return false;

    fs_sink_ctx ctx = { fs, 0, true };
    size_t total = nsp_http_stream(nsp_manager_url("/download_data_file").c_str(),
                                   fs_sink, &ctx);
    if (total == 0 || !ctx.ok || total > fs->size) return false;
    (void)checksum;
    return true;
}

/* Rail #1: firmware first, REBOOT, fs later under the new firmware. */
static void nsp_ota_fw_task(void *) {
    s_state = OTA_FW;
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();

    std::string checksum;
    for (int i = 0; i < 60 && checksum.empty(); i++) {
        s_last_progress_us = esp_timer_get_time();  // legit waiting, not stalled
        if (nsp_http_get_small(nsp_manager_url("/checksum_firmware").c_str(), checksum)
            && checksum.size() >= 32) break;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (checksum.size() < 32) { s_state = OTA_IDLE; vTaskDelete(nullptr); return; }

    if (g_cfg.md5_firmware.compare(0, 32, checksum, 0, 32) == 0) {
        // same firmware — skip the app flash, fs may still be needed (below)
    } else {
        bool flashed = false;
        for (int attempt = 0; attempt < OTA_MAX_ATTEMPTS && !flashed; attempt++) {
            const esp_partition_t *target = esp_ota_get_next_update_partition(nullptr);
            esp_ota_handle_t handle;
            if (esp_ota_begin(target, OTA_SIZE_UNKNOWN, &handle) != ESP_OK) {
                vTaskDelay(pdMS_TO_TICKS(5000));
                continue;
            }
            fw_sink_ctx ctx = { handle, true };
            size_t total = nsp_http_stream(nsp_manager_url("/download_firmware").c_str(),
                                           fw_sink, &ctx);
            if (total > 0x100 && ctx.ok && esp_ota_end(handle) == ESP_OK
                && esp_ota_set_boot_partition(target) == ESP_OK) {
                flashed = true;
            } else {
                esp_ota_abort(handle);
                vTaskDelay(pdMS_TO_TICKS(5000));
            }
        }
        if (!flashed) {
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);  // bounded: no infinite retry (P129)
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
    std::string fs_checksum;
    for (int i = 0; i < 60 && fs_checksum.empty(); i++) {
        s_last_progress_us = esp_timer_get_time();
        if (nsp_http_get_small(nsp_manager_url("/checksum_data_file").c_str(), fs_checksum)
            && fs_checksum.size() >= 32) break;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (fs_checksum.size() >= 32 &&
        g_cfg.md5_data_file.compare(0, 32, fs_checksum, 0, 32) != 0) {
        if (nsp_write_fs_partition(fs_checksum)) {
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
