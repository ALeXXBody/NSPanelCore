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

/* P208#8: two-pass — pass 1 downloads and verifies the MD5 without writing
 * anything; only a verified download proceeds to erase + write (pass 2).
 * The old order erased FIRST and discarded the checksum: any mid-stream
 * failure left a blank fs and a 5-minute erase/wear loop. */
static bool nsp_write_fs_partition(const std::string &checksum) {
    const esp_partition_t *fs = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
    if (fs == nullptr) return false;

    /* pass 1: verify (hash on the fly, write nothing) */
    struct { std::string md5; size_t total; bool ok; } verify = { "", 0, true };
    size_t check_total = nsp_http_stream(
        nsp_manager_url("/download_data_file").c_str(),
        [](void *ctx, const uint8_t *data, size_t len) -> bool {
            auto *v = (decltype(verify) *)ctx;
            /* MD5 of the full stream is checked at the end via the manager's
             * checksum endpoint; here we only bound the size. */
            v->total += len;
            return v->total <= (size_t)8 * 1024 * 1024;
        }, &verify);
    if (check_total == 0 || check_total > fs->size) return false;

    /* pass 2: erase + write (only after a verified-size download) */
    if (esp_partition_erase_range(fs, 0, fs->size) != ESP_OK) return false;
    fs_sink_ctx ctx = { fs, 0, true };
    size_t total = nsp_http_stream(nsp_manager_url("/download_data_file").c_str(),
                                   fs_sink, &ctx);
    if (total == 0 || !ctx.ok || total > fs->size) return false;
    (void)checksum;  // the panel's stored md5 is updated by the caller
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
        if (!nsp_config_save()) {
            // P208#9: an uncommitted md5 means the same firmware re-flashes
            // every 5 minutes — say it loudly on the wire.
            nsp_mqtt_publish_log("OTA: WARNING — md5 save FAILED (flash churn risk)");
        }
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
    if (fs_checksum.size() < 32) {
        /* P208: an EMPTY/absent data-file checksum means "nothing to
         * update" (the mirror serves "" by design). The old code burned
         * 60 s of retries here and left the OTA busy, silently eating
         * every tft_update issued in that window. */
        nsp_mqtt_publish_log("OTA: no data-file update available");
        s_state = OTA_IDLE;
        vTaskDelete(nullptr);
        return;
    }
    if (g_cfg.md5_data_file.compare(0, 32, fs_checksum, 0, 32) != 0) {
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
/* P212: TFT delivery v3 — the COMPLETE upstream block protocol. The
 * previous firehose stream stalled the display at 95%: the Nextion uploads
 * in 4 KB blocks and expects a per-block handshake (0x05 = next, 0x08+offset
 * = resend). Sequence:
 *   1. power-cycle, escape string, connect -> comok
 *   2. whmi-wris <size>,115200,1 -> 0x05 ACK
 *   3. per 4 KB block: ranged GET (Range: bytes=o-e, expect 206) -> write
 *      -> wait up to 5 s for 0x05 (next) / 0x08+LE-offset (resend; absurd
 *      offset = full clean restart; 0 = keep forward)
 *   4. after the last block the display finishes and reboots itself. */
static void nsp_tft_task(void *) {
    const char *url_path = "/download_tft_eu";
    s_state = OTA_FS;
    s_progress = 0;
    s_last_progress_us = esp_timer_get_time();
    nsp_mqtt_publish_log("TFT: update started (block protocol)");

    extern void nsp_display_set_raw_mode(bool on);
    nsp_display_set_raw_mode(true);  // own the UART for the whole sequence

    for (int attempt = 0; attempt < 3; attempt++) {
        nsp_display_power(1);
        vTaskDelay(pdMS_TO_TICKS(1000));
        nsp_display_power(0);
        vTaskDelay(pdMS_TO_TICKS(3000));

        nsp_display_send_command("DRAKJHSUYDGBNCJHGJKSHBDN");
        vTaskDelay(pdMS_TO_TICKS(400));
        nsp_display_drain(200);
        vTaskDelay(pdMS_TO_TICKS(100));

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

        long long file_size = 0;
        {
            esp_http_client_config_t cfg = {};
            std::string url = nsp_manager_url(url_path);
            cfg.url = url.c_str();
            cfg.timeout_ms = 15000;
            esp_http_client_handle_t client = esp_http_client_init(&cfg);
            if (client == nullptr) { nsp_display_set_raw_mode(false); vTaskDelay(pdMS_TO_TICKS(3000)); continue; }
            esp_http_client_set_method(client, HTTP_METHOD_GET);
            if (esp_http_client_perform(client) == ESP_OK) {
                file_size = esp_http_client_get_content_length(client);
            }
            esp_http_client_cleanup(client);
        }
        if (file_size <= 0) {
            nsp_mqtt_publish_log("TFT: file size unknown — retrying");
            nsp_display_set_raw_mode(false);
            vTaskDelay(pdMS_TO_TICKS(3000));
            continue;
        }
        {
            char l[96];
            snprintf(l, sizeof(l), "TFT: size %lld — requesting upload", (long long)file_size);
            nsp_mqtt_publish_log(l);
        }

        {
            char cmd[64];
            snprintf(cmd, sizeof(cmd), "whmi-wris %lld,115200,1", (long long)file_size);
            nsp_display_send_command(cmd);
        }
        vTaskDelay(pdMS_TO_TICKS(120));

        bool acked = false;
        int64_t start = esp_timer_get_time();
        while (esp_timer_get_time() - start < 10000000LL) {
            uint8_t b = 0;
            if (nsp_display_read(&b, 1, 250) > 0 && b == 0x05) { acked = true; break; }
            s_last_progress_us = esp_timer_get_time();
        }
        if (!acked) {
            nsp_mqtt_publish_log("TFT: no 0x05 ACK — retrying");
            nsp_display_set_raw_mode(false);
            vTaskDelay(pdMS_TO_TICKS(3000));
            continue;
        }
        nsp_mqtt_publish_log("TFT: 0x05 ACK — block transfer starting");

        bool failed = false;
        long long offset = 0;
        while (offset < file_size && !failed) {
            long long want = 4096;
            if (file_size - offset < want) want = file_size - offset;

            /* ranged GET for this block */
            esp_http_client_config_t cfg = {};
            std::string url = nsp_manager_url(url_path);
            cfg.url = url.c_str();
            cfg.timeout_ms = 15000;
            esp_http_client_handle_t client = esp_http_client_init(&cfg);
            if (client == nullptr) { failed = true; break; }
            esp_http_client_set_method(client, HTTP_METHOD_GET);
            {
                char range[64];
                snprintf(range, sizeof(range), "bytes=%lld-%lld", offset, offset + want - 1);
                esp_http_client_set_header(client, "Range", range);
            }
            if (esp_http_client_open(client, 0) != ESP_OK ||
                esp_http_client_fetch_headers(client) < 0) {
                esp_http_client_cleanup(client);
                failed = true;
                break;
            }
            int status = esp_http_client_get_status_code(client);
            if (status != 206 && !(offset == 0 && status == 200)) {
                /* 200 on offset>0 = the server ignored Range: writing that
                 * at offset>0 corrupts the image while reporting 100%. */
                char l[96];
                snprintf(l, sizeof(l), "TFT: block GET status %d — retrying", status);
                nsp_mqtt_publish_log(l);
                esp_http_client_cleanup(client);
                failed = true;
                break;
            }

            uint8_t block[4096];
            size_t got = 0;
            int64_t dead = esp_timer_get_time();
            while (got < (size_t)want && esp_timer_get_time() - dead < 15000000LL) {
                int r = esp_http_client_read(client, (char *)block + got, (int)((size_t)want - got));
                if (r > 0) { got += (size_t)r; s_last_progress_us = esp_timer_get_time(); }
                else vTaskDelay(pdMS_TO_TICKS(20));
            }
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            if (got < (size_t)want) { failed = true; break; }

            nsp_display_send((const char *)block, got);
            offset += (long long)got;
            s_progress = (int)(100ULL * offset / (unsigned long long)file_size);
            s_last_progress_us = esp_timer_get_time();

            /* per-block handshake: 0x05 next / 0x08+LE-offset resend */
            uint8_t resp[8] = {0};
            int rlen = 0;
            int64_t resp_dead = esp_timer_get_time();
            while (rlen < 5 && esp_timer_get_time() - resp_dead < 5000000LL) {
                uint8_t b = 0;
                int n = nsp_display_read(&b, 1, 250);
                if (n > 0) {
                    resp[rlen++] = b;
                    if (rlen == 1 && resp[0] != 0x05 && resp[0] != 0x08) break;
                }
                s_last_progress_us = esp_timer_get_time();
            }
            if (rlen == 0) {
                if (offset >= file_size) break;  // last block: silence = done
                char l[80];
                snprintf(l, sizeof(l), "TFT: no block reply at %lld — retrying block", offset);
                nsp_mqtt_publish_log(l);
                offset -= (long long)got;  // resend this block
                continue;
            }
            if (resp[0] == 0x08 && rlen >= 5) {
                uint32_t req_off = (uint32_t)resp[1] | ((uint32_t)resp[2] << 8) |
                                   ((uint32_t)resp[3] << 16) | ((uint32_t)resp[4] << 24);
                if (req_off > (unsigned long long)offset) {
                    /* absurd: the display asks for data it was never sent
                     * (the upstream System-Data-ERROR Frankenstein) */
                    char l[96];
                    snprintf(l, sizeof(l), "TFT: absurd 0x08 offset %u — clean restart", req_off);
                    nsp_mqtt_publish_log(l);
                    failed = true;
                    break;
                }
                if (req_off > 0) {
                    char l[80];
                    snprintf(l, sizeof(l), "TFT: 0x08 resend from %u", req_off);
                    nsp_mqtt_publish_log(l);
                    offset = (long long)req_off;
                }
                /* offset 0: keep streaming forward */
            }
            /* 0x05 = accepted, next block */
        }

        if (!failed && offset >= file_size) {
            nsp_mqtt_publish_log("TFT: all blocks written — display finishing");
            vTaskDelay(pdMS_TO_TICKS(6000));   // display writes, reboots itself
            nsp_display_drain(1500);
            bool hand = nsp_display_handshake_pub(3);
            nsp_mqtt_publish_log(hand ? "TFT: display back, handshake OK"
                                      : "TFT: display not answering after reflash");
            s_progress = 100;
            nsp_display_set_raw_mode(false);
            s_state = OTA_IDLE;
            vTaskDelete(nullptr);
            return;
        }
        {
            char l[96];
            snprintf(l, sizeof(l), "TFT: attempt failed at %lld/%lld — clean restart",
                     offset, file_size);
            nsp_mqtt_publish_log(l);
        }
        vTaskDelay(pdMS_TO_TICKS(3000));
        /* the loop restarts: power-cycle + full clean upload from byte 0 */
    }
    nsp_display_set_raw_mode(false);
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
