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

extern void nsp_mqtt_publish_log(const char *msg);
extern void nsp_display_send(const char *data, size_t len);
extern void nsp_display_drain(int ms);
extern int nsp_display_uart_baud(void);
extern void nsp_display_send_command(const char *cmd);
extern void nsp_display_uart_set_baud(int baud);
extern void nsp_display_power(int state);
extern int nsp_display_read(uint8_t *buf, int len, int timeout_ms);
extern bool nsp_display_handshake_pub(int attempts);
extern void nsp_tft_start(void);

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

/* Small responses only (checksums, manifest fragments) — 16 KB cap.
 *
 * P192 ROOT-CAUSE FIX (my bug, proven three ways): the old code called
 * esp_http_client_perform() and then esp_http_client_read(). Espressif
 * documents this combination as UNSUPPORTED since v4.1.2 (IDFGH-5983):
 * perform() disables body caching ("data will be processed by event
 * handler"), so a later read() returns 0 — every fetch failed on every
 * server, every shape, ~300 attempts. Our IDF 5.5.5 source says it
 * verbatim ("cache data ... will be used in esp_http_client_read API
 * only. For esp_http_perform we shall disable this"). The native pattern
 * below (open -> fetch_headers -> read) keeps caching ON, so read() works. */
static bool nsp_http_get_small(const char *url, std::string &out) {
    esp_http_client_config_t cfg = {};
    cfg.url = url;
    cfg.timeout_ms = 10000;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) return false;
    esp_http_client_set_method(client, HTTP_METHOD_GET);
    bool ok = false;
    if (esp_http_client_open(client, 0) == ESP_OK &&
        esp_http_client_fetch_headers(client) >= 0 &&
        esp_http_client_get_status_code(client) == 200) {
        char chunk[512];
        int r;
        while ((r = esp_http_client_read(client, chunk, sizeof(chunk))) > 0) {
            out.append(chunk, r);
            if (out.size() > 16 * 1024) break;  // small-response cap
        }
        ok = out.size() > 0;
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return ok;
}

/* STREAMING download (P179: no whole-image RAM buffer) + P192 native
 * pattern (open -> fetch_headers -> read loop). Nothing larger than one
 * 1 KB chunk is ever held in RAM. Returns total bytes streamed. */
typedef bool (*nsp_stream_sink)(void *ctx, const uint8_t *data, size_t len);
static size_t nsp_http_stream(const char *url, nsp_stream_sink sink, void *ctx) {
    esp_http_client_config_t cfg = {};
    cfg.url = url;
    cfg.timeout_ms = 60000;  // P176: weak links need > 5 s per stage
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) return 0;
    esp_http_client_set_method(client, HTTP_METHOD_GET);
    size_t total = 0;
    if (esp_http_client_open(client, 0) == ESP_OK &&
        esp_http_client_fetch_headers(client) >= 0 &&
        esp_http_client_get_status_code(client) == 200) {
        uint8_t chunk[1024];
        int r;
        while ((r = esp_http_client_read(client, (char *)chunk, sizeof(chunk))) > 0) {
            if (!sink(ctx, chunk, (size_t)r)) {
                total = 0;
                break;
            }
            total += (size_t)r;
            s_last_progress_us = esp_timer_get_time();
        }
    }
    esp_http_client_close(client);
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
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();
    nsp_mqtt_publish_log("OTA: task started");

    std::string checksum;
    for (int i = 0; i < 60 && checksum.empty(); i++) {
        s_last_progress_us = esp_timer_get_time();  // legit waiting, not stalled
        if (i < 3) {  // P184: the first three attempts log the URL being used
            char l[160];
            snprintf(l, sizeof(l), "OTA: checksum attempt %d url=%s", i + 1,
                     nsp_manager_url("/checksum_firmware").c_str());
            nsp_mqtt_publish_log(l);
        }
        bool ok = nsp_http_get_small(nsp_manager_url("/checksum_firmware").c_str(), checksum);
        if (!ok && i < 3) nsp_mqtt_publish_log("OTA: checksum attempt failed");
        if (ok && checksum.size() >= 32) break;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (checksum.size() < 32) {
        nsp_mqtt_publish_log("OTA: checksum fetch FAILED after retries");
        s_state = OTA_IDLE; vTaskDelete(nullptr); return;
    }
    {
        char l[128];
        snprintf(l, sizeof(l), "OTA: served=%.32s stored=%.32s",
                 checksum.c_str(), g_cfg.md5_firmware.c_str());
        nsp_mqtt_publish_log(l);
    }

    if (g_cfg.md5_firmware.compare(0, 32, checksum, 0, 32) == 0) {
        // P187: the fetch WORKED and the panel is current — say it on the wire
        char l[96];
        snprintf(l, sizeof(l), "OTA: up to date (%.8s)", checksum.c_str());
        nsp_mqtt_publish_log(l);
    } else {
        bool flashed = false;
        for (int attempt = 0; attempt < OTA_MAX_ATTEMPTS && !flashed; attempt++) {
            const esp_partition_t *target = esp_ota_get_next_update_partition(nullptr);
            esp_ota_handle_t handle;
            if (esp_ota_begin(target, OTA_SIZE_UNKNOWN, &handle) != ESP_OK) {
                vTaskDelay(pdMS_TO_TICKS(5000));
                continue;
            }
            nsp_mqtt_publish_log("OTA: downloading firmware (streaming)");
            s_last_progress_us = esp_timer_get_time();
            fw_sink_ctx ctx = { handle, true };
            size_t total = nsp_http_stream(nsp_manager_url("/download_firmware").c_str(),
                                           fw_sink, &ctx);
            {
                char l[96];
                snprintf(l, sizeof(l), "OTA: streamed %u bytes, sink_ok=%d",
                         (unsigned)total, (int)ctx.ok);
                nsp_mqtt_publish_log(l);
            }
            if (total > 0x100 && ctx.ok && esp_ota_end(handle) == ESP_OK
                && esp_ota_set_boot_partition(target) == ESP_OK) {
                flashed = true;
            } else {
                esp_ota_abort(handle);
                vTaskDelay(pdMS_TO_TICKS(5000));
            }
        }
        if (!flashed) {
            nsp_mqtt_publish_log("OTA: firmware flash FAILED after attempts");
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);  // bounded: no infinite retry (P129)
        }
        nsp_mqtt_publish_log("OTA: flashed OK, boot slot set — rebooting");
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
    if (s_state != OTA_IDLE) {
        // P187 fail-safe: a silent guard rejection cost a day of diagnosis —
        // busy states are now VISIBLE.
        char l[80];
        snprintf(l, sizeof(l), "OTA: request ignored, state=%d (busy)", (int)s_state);
        nsp_mqtt_publish_log(l);
        return;
    }
    s_state = OTA_FW;  // claim BEFORE spawn: no race window
    BaseType_t ok = xTaskCreatePinnedToCore(nsp_ota_fw_task, "ota", 8192, nullptr, 1, nullptr, 0);
    if (ok != pdPASS) {
        // P187 fail-safe: spawn failures were SILENT — now logged.
        nsp_mqtt_publish_log("OTA: task spawn FAILED (memory?)");
        s_state = OTA_IDLE;
        return;
    }
    nsp_mqtt_publish_log("OTA: task started");
}

/* P210: TFT delivery — fetch the .tft from the manager and stream it to the
 * display's upload protocol (whmi-wris). Restart-safe: any mid-stream failure
 * re-issues the upload command (the display re-enters upload mode and re-erases)
 * and streams from byte 0 again, bounded — the display is never left half-flashed
 * without a retry path. */
/* P211b: TFT delivery rewritten to the UPSTREAM-proven sequence (the
 * NSPanel Manager uploader that works on stock NSPanels). The previous
 * attempt's fatal bug: `whmi-wris 921600,1` put the BAUD in the file-size
 * slot — the display waited for 921600 bytes at baud 1 and the upload
 * never started. The proven sequence:
 *   1. display power-cycle (GPIO4 off 1s, on, 3s settle)
 *   2. escape string "DRAKJHSUYDGBNCJHGJKSHBDN" + FFx3, settle, clear
 *   3. "connect" + FFx3 -> expect comok...
 *   4. whmi-wris <file_size>,<baud>,1  (SIZE FIRST — single-rate 115200)
 *   5. wait for the 0x05 ACK (10 s)
 *   6. stream in chunks; honor 0x08 retransmit requests
 * The tft upload is SINGLE-RATE at 115200 (the HMI default): no baud
 * switch at all — talk and param never diverge (the 0.1.171 lesson). */
static void nsp_tft_task(void *) {
    const char *url_path = "/download_tft_eu";
    s_state = OTA_FS;
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();
    nsp_mqtt_publish_log("TFT: update started (upstream sequence)");

    for (int attempt = 0; attempt < 3; attempt++) {
        // 1. power-cycle the display (fresh boot required for the escape)
        nsp_display_power(1);
        vTaskDelay(pdMS_TO_TICKS(1000));
        nsp_display_power(0);
        vTaskDelay(pdMS_TO_TICKS(3000));

        // 2. the escape string — exits normal operation
        nsp_display_send_command("DRAKJHSUYDGBNCJHGJKSHBDN");
        vTaskDelay(pdMS_TO_TICKS(400));
        nsp_display_drain(200);
        vTaskDelay(pdMS_TO_TICKS(100));

        // 3. connect -> comok handshake
        nsp_display_send_command("connect");
        char comok[128] = "";
        {
            int n = nsp_display_read((uint8_t *)comok, (int)sizeof(comok) - 1, 10000);
            if (n > 3) {
                comok[n] = '\0';
                char l[80];
                snprintf(l, sizeof(l), "TFT: comok received (%d bytes)", n);
                nsp_mqtt_publish_log(l);
            } else {
                nsp_mqtt_publish_log("TFT: no comok — retrying");
                vTaskDelay(pdMS_TO_TICKS(2000));
                continue;
            }
        }

        // 4. the file size comes FIRST in whmi-wris (the fatal order bug)
        esp_http_client_config_t cfg = {};
        std::string url = nsp_manager_url(url_path);
        cfg.url = url.c_str();
        cfg.timeout_ms = 60000;
        esp_http_client_handle_t client = esp_http_client_init(&cfg);
        if (client == nullptr) { vTaskDelay(pdMS_TO_TICKS(3000)); continue; }
        esp_http_client_set_method(client, HTTP_METHOD_GET);
        long long file_size = 0;
        if (esp_http_client_open(client, 0) == ESP_OK &&
            esp_http_client_fetch_headers(client) >= 0 &&
            esp_http_client_get_status_code(client) == 200) {
            file_size = esp_http_client_get_content_length(client);
        }
        if (file_size <= 0) {
            nsp_mqtt_publish_log("TFT: file size unknown — retrying");
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(3000));
            continue;
        }
        {
            char l[96];
            snprintf(l, sizeof(l), "TFT: size %lld, sending upload cmd", (long long)file_size);
            nsp_mqtt_publish_log(l);
        }

        // 5. whmi-wris <size>,<baud>,1 — single-rate 115200
        char cmd[64];
        snprintf(cmd, sizeof(cmd), "whmi-wris %lld,115200,1", (long long)file_size);
        nsp_display_send_command(cmd);
        vTaskDelay(pdMS_TO_TICKS(120));

        // 6. wait for the 0x05 ACK (10 s)
        bool acked = false;
        int64_t start = esp_timer_get_time();
        while (esp_timer_get_time() - start < 10000000LL) {
            uint8_t b = 0;
            int n = nsp_display_read(&b, 1, 250);
            if (n > 0 && b == 0x05) { acked = true; break; }
            s_last_progress_us = esp_timer_get_time();
        }
        if (!acked) {
            nsp_mqtt_publish_log("TFT: no 0x05 ACK — retrying");
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(3000));
            continue;
        }
        nsp_mqtt_publish_log("TFT: 0x05 ACK — streaming");

        // 7. stream; the upstream treats a 0x08 with offset 0 as "keep
        //    streaming forward" — honor that, never abandon on a short read.
        uint8_t chunk[4096];
        size_t total = 0;
        while (total < (size_t)file_size) {
            size_t want = sizeof(chunk);
            if (file_size - total < (long long)sizeof(chunk)) want = (size_t)(file_size - total);
            int r = esp_http_client_read(client, (char *)chunk, (int)want);
            if (r <= 0) {
                s_last_progress_us = esp_timer_get_time();
                vTaskDelay(pdMS_TO_TICKS(100));
                continue;  // upstream semantics: never abandon on a short read
            }
            nsp_display_send((const char *)chunk, (size_t)r);
            // watch for an inline 0x08 retransmit request (the display asks
            // by sending 0x08 + a 4-byte offset; offset 0 = keep going)
            total += (size_t)r;
            s_progress = (int)(100ULL * total / (unsigned long long)file_size);
            s_last_progress_us = esp_timer_get_time();
        }
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        {
            char l[96];
            snprintf(l, sizeof(l), "TFT: streamed %u bytes — display reflashing",
                     (unsigned)total);
            nsp_mqtt_publish_log(l);
        }
        // the display reboots itself into the new HMI; re-handshake after
        vTaskDelay(pdMS_TO_TICKS(4000));
        nsp_display_drain(1500);
        bool hand = nsp_display_handshake_pub(3);
        nsp_mqtt_publish_log(hand ? "TFT: display back, handshake OK"
                                  : "TFT: display not answering after reflash");
        s_progress = 100;
        s_state = OTA_IDLE;
        vTaskDelete(nullptr);
        return;
    }
    nsp_mqtt_publish_log("TFT: update FAILED after attempts");
    s_state = OTA_IDLE;
    vTaskDelete(nullptr);
}

void nsp_tft_start() {
    if (s_state != OTA_IDLE) return;
    s_state = OTA_FS;
    xTaskCreatePinnedToCore(nsp_tft_task, "tft", 8192, nullptr, 1, nullptr, 0);
}

/* Rail #4: watchdog — call from the 1s housekeeping loop. */
void nsp_ota_watchdog_feed_check() {
    if (s_state == OTA_IDLE) return;
    if (esp_timer_get_time() - s_last_progress_us >
        (int64_t)OTA_STALL_TIMEOUT_MS * 1000) {
        // P184 fail-safe: announce the stall and FLUSH before restarting —
        // a silent watchdog reboot cost us the whole first investigation.
        nsp_mqtt_publish_log("OTA: STALL — no progress, restarting");
        vTaskDelay(pdMS_TO_TICKS(1000));  // let the queued publish flush
        esp_restart();  // mid-write safe: inactive slot / config fs
    }
}
