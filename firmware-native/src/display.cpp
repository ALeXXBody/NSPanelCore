/* NSPanel Core — display (Nextion-style UART, gentle-first boot).
 *
 * P122/P130 lessons baked in:
 * - Boot NEVER power-cycles the display (GPIO4 hard off→on browns out weak
 *   power and boot-looped the panel with no AP). The display is talked to
 *   directly; power-cycling is manual only ("display_restart" command).
 * - A dead display must never block WiFi/MQTT — the panel continues without
 *   it and reports the warning in every status report.
 * - Single baud: 115200 for all normal traffic and the handshake; the
 *   configurable upload baud applies ONLY to the bulk TFT stream.
 */

#include "driver/uart.h"
#include "touch_decode.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"  // P364b: the hold through resets
#include <cstring>
#include <cstdio>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"  // P334: the write mutex
#include "protocol.h"
#include "config.h"
#include "dash_cmd.h"
#include "screensaver_parse.h"

#define DISPLAY_UART UART_NUM_1
/* P178 fix: match the proven v1 mapping — Serial2.begin(115200, SERIAL_8N1, 17, 16)
 * is Arduino (rxPin=17, txPin=16). The swapped defines made the native firmware
 * transmit into the display's TX line: handshake could never succeed. */
#define DISPLAY_TX_PIN 16
#define DISPLAY_RX_PIN 17
#define DISPLAY_POWER_PIN GPIO_NUM_4
#define DISPLAY_BAUD 115200
#define END_SEQ "\xFF\xFF\xFF"

static volatile bool s_display_ready = false;
static volatile bool s_display_raw_mode = false;  // P208#5: touch/UART ownership
static char s_warnings[64] = "";
void nsp_display_set_raw_mode(bool on);  // P208#5: defined below
int nsp_display_read(uint8_t *buf, int len, int timeout_ms);  // P362: defined below
extern void nsp_mqtt_publish_log(const char *line);  // P160: file scope only
void nsp_display_show_screensaver(void);  // P211: defined below (file scope, P160 rule)
void nsp_display_relay(int relay, bool state);  // P211
extern "C" void nsp_relay_toggle_pub(int relay);  // P210
void nsp_display_set_raw_mode(bool on);  // P208#5

bool nsp_display_ready(void) { return s_display_ready; }
/* P269: the swipe gesture state (the dash pages, the 0x67 coordinates) */
static int s_swipe_page = -1;        // the dash page id the gesture is on
static int s_swipe_x1 = -1, s_swipe_y1 = -1;
static bool s_swipe_navigated = false;  // the release was a swipe -> suppress
const char *nsp_display_warning(void) {
    return s_display_ready ? "" : "No response from the display.";
}

/* P316: display diagnostics — the RX byte counter counts EVERY byte that
 * arrives from the display UART (silence = electrical fault; garbage =
 * wrong baud; a valid reply = alive). Exposed on the panel web status. */
static volatile uint32_t s_display_rx_bytes = 0;
uint32_t nsp_display_rx_bytes(void) { return s_display_rx_bytes; }
static void nsp_rx_count(int n) { if (n > 0) s_display_rx_bytes += (uint32_t)n; }
void nsp_display_baud_scan(void);  // P316: defined below

/* P279 MEDIUM fix (F11): the display writes are UNSYNCHRONIZED between the
 * MQTT task and the touch task (the swipe's dp=, the page nav, the clock) —
 * interleaved mid-command bytes garbled the wire. One mutex serializes
 * every command write; the TFT streamer bypasses it (it owns the UART in
 * raw mode). */

/* P347: the TFT transfer baud switch — the display and the ESP's UART
 * must match. The normal baud is 115200; the TFT transfer uses 57600 for
 * reliability (the display drops bytes at 115200 during long transfers). */
void nsp_display_set_tft_baud(int baud) {
    uart_set_baudrate(DISPLAY_UART, baud);
}

void nsp_display_send(const char *data, size_t len) {  // P210: shared with the TFT streamer
    uart_write_bytes(DISPLAY_UART, data, len);
}

/* P316: the UNGATED send — used by the handshake only. Readiness is the
 * handshake's OUTPUT; gating its own send on the state it establishes
 * (raw mode at init, not-ready afterwards) made the panel transmit
 * NOTHING since P279 batch 3 — the "dead" display was never dead. */

/* P334: the old write held a portMUX critical section (interrupts
 * disabled) across uart_write_bytes — which BLOCKS when the TX ring fills.
 * The retained-message burst at every MQTT connect (the screensaver's 18
 * style commands + the clock + the weather) filled the ring and the write
 * waited with interrupts disabled: the interrupt watchdog (300 ms) aborted
 * the chip — the MQTT-connect crash. The critical section is GONE: the
 * serialization is a FreeRTOS mutex (blocking-safe, priority-inheriting),
 * and uart_write_bytes serializes internally for our lengths. */
static SemaphoreHandle_t s_display_write_mutex = nullptr;

static void nsp_display_write_init(void) {
    if (s_display_write_mutex == nullptr) {
        s_display_write_mutex = xSemaphoreCreateMutex();
    }
}

/* P339: the handshake's commands MUST reach the display — uart_tx_chars
 * DROPS them when the TX ring is full, and the handshake fails because the
 * "connect" never left the chip. send_now uses the BLOCKING write: the
 * handshake is one short command, it can't flood. The regular display
 * writes (the clock, the style, the dim) use the non-blocking path. */
void nsp_display_send_now(const char *cmd) {
    size_t len = strlen(cmd);
    if (s_display_write_mutex) {
        xSemaphoreTake(s_display_write_mutex, portMAX_DELAY);
        uart_write_bytes(DISPLAY_UART, cmd, len);  // P339: blocking — must arrive
        uart_write_bytes(DISPLAY_UART, END_SEQ, 3);
        xSemaphoreGive(s_display_write_mutex);
    } else {
        uart_write_bytes(DISPLAY_UART, cmd, len);
        uart_write_bytes(DISPLAY_UART, END_SEQ, 3);
    }
}

void nsp_display_send_command(const char *cmd) {
    if (s_display_raw_mode) return;  // P279 HIGH fix: the TFT upload owns the wire
    /* P312: display-dead suspension — commands are dropped until the
     * display answers again; the handshake/revival path uses send_now. */
    if (!s_display_ready) return;
    nsp_display_send_now(cmd);
}

void nsp_display_drain(int ms) {  // P210: shared
    uint8_t buf[64];
    int64_t start = esp_timer_get_time();
    while (esp_timer_get_time() - start < (int64_t)ms * 1000) {
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(25));
        nsp_rx_count(n);
        (void)n;
    }
}

/* Handshake: send "connect", expect a reply (typically "comok..."). */
static bool nsp_display_handshake(int attempts) {
    for (int i = 0; i < attempts; i++) {
        uart_flush_input(DISPLAY_UART);
        /* P336: WAKE the display before the handshake — the HMI's sleep
         * (its own timer or a stray sleep command) silences its serial and
         * every handshake failed "no comok" while a power-cycle answered.
         * The wake command exits sleep; the sleep timer is then disabled
         * (thsp=0) so the display never silences itself again. */
        nsp_display_send_now("wake");
        vTaskDelay(pdMS_TO_TICKS(150));
        nsp_display_send_now("thsp=0");
        vTaskDelay(pdMS_TO_TICKS(150));
        nsp_display_send_now("connect");  // P316: the ungated path
        vTaskDelay(pdMS_TO_TICKS(1000));
        uint8_t buf[128];
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(1000));
        nsp_rx_count(n);
        if (n > 3) {  // any non-trivial reply proves the link
            s_display_ready = true;
            s_warnings[0] = '\0';
            return true;
        }
    }
    /* P358: a FAILED handshake must clear the ready flag. The post-TFT-
     * delivery handshake failed while the flag stayed true from the pre-
     * delivery one — the revival paths (the reprobe, the P312 housekeeping)
     * all gate on !s_display_ready and were SKIPPED FOREVER: the freshly
     * rebooted display sat on the splash (the authored logo) with nobody
     * to navigate it (the user's report after the re-delivery). */
    s_display_ready = false;
    snprintf(s_warnings, sizeof(s_warnings), "No response from the display.");
    return false;
}

static bool nsp_display_handshake(int attempts);
static void nsp_display_after_handshake(void);  // P310: forward decl (defined below)

void nsp_display_init(void) {
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << DISPLAY_POWER_PIN;
    io.mode = GPIO_MODE_OUTPUT;
    gpio_config(&io);
    gpio_set_level(DISPLAY_POWER_PIN, 0);  // display POWERED — never cycle at boot (P122)
    /* P364b (the bootloop root cause): during every ESP reset/bootloader
     * phase the GPIO FLOATS — the display's supply browns out (the P122
     * lesson: power-cycling browns out weak supplies) and a brownout at
     * the wrong moment corrupts the display's config flash (the
     * recurring System-Data-ERROR, always after a panel update). The
     * RTC-domain hold keeps the level through the reset. GPIO4 is an RTC
     * pad on the ESP32: the hold survives esp_restart. */
    esp_err_t hold_err = rtc_gpio_hold_en(DISPLAY_POWER_PIN);
    if (hold_err != ESP_OK) gpio_hold_en(DISPLAY_POWER_PIN);

    uart_config_t ucfg = {};
    ucfg.baud_rate = DISPLAY_BAUD;
    ucfg.data_bits = UART_DATA_8_BITS;
    ucfg.parity = UART_PARITY_DISABLE;
    ucfg.stop_bits = UART_STOP_BITS_1;
    ucfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    uart_driver_install(DISPLAY_UART, 512, 512, 0, nullptr, 0);
    nsp_display_write_init();  // P334: the blocking-safe write mutex
    uart_param_config(DISPLAY_UART, &ucfg);
    uart_set_pin(DISPLAY_UART, DISPLAY_TX_PIN, DISPLAY_RX_PIN, -1, -1);

    vTaskDelay(pdMS_TO_TICKS(1500));  // let the display finish its own boot
    /* P208#5: the touch task must not consume the handshake replies. */
    s_display_raw_mode = true;
    bool hand = nsp_display_handshake(3);
    s_display_raw_mode = false;
    if (!hand) {
        s_display_ready = false;
        snprintf(s_warnings, sizeof(s_warnings), "No response from the display.");
        // Continue WITHOUT the display — WiFi/MQTT/sensors stay alive (P130).
    } else {
        /* P211: navigate OFF the splash into the screensaver — the authored
         * splash has no auto-page code, so without this the display sits on
         * a static image forever (the user's report after the TFT update). */
        nsp_display_after_handshake();
    }
}

/* P310: what the display needs after ANY successful handshake — the authored
 * splash never auto-advances, so a screen left at the logo after a manual
 * restart (or a recovered hang) must be navigated into the screensaver and
 * the relay buttons re-synced, exactly like the boot path. */
static void nsp_display_after_handshake(void) {
    /* P355: the P337 suppression is LIFTED — the "goes deaf" suspicion it
     * isolated was falsified by P352 (the served file switched mid-transfer;
     * the display was faithfully ACKing throughout). The navigation's own
     * writes go through nsp_display_send_command, which is INERT while the
     * TFT task holds raw mode — a handshake inside the delivery never
     * navigates mid-upload. With the suppression, every boot sat on the
     * splash forever (the user's report: the logo stuck, the switches dead —
     * the button zones live on home, which nothing ever reached). */
    nsp_display_show_screensaver();
    extern int nsp_relay_state(int relay);
    nsp_display_relay(1, nsp_relay_state(1));
    nsp_display_relay(2, nsp_relay_state(2));
}

/* Manual recovery: power-cycle + handshake. ONLY from the "display_restart"
 * command, never at boot (stable power assumed). */
/* P312: bounded display reprobe — one drain + one handshake attempt, no
 * power cycle, no raw mode. Called from the housekeeping loop while the
 * display is dead; revives the panel automatically when the hardware
 * answers again. */
bool nsp_display_reprobe(void) {
    if (s_display_ready || s_display_raw_mode) return s_display_ready;
    nsp_display_drain(300);
    s_display_ready = false;
    bool ok = nsp_display_handshake(1);
    if (ok) nsp_display_after_handshake();  // P316: revive = take over the screen
    return ok;
}

/* P316: the baud scan — interrupted TFT uploads (whmi-wris) switch the
 * Nextion's UART speed; a crash after that leaves it at a baud we never
 * probe (the handshake is fixed at 115200). Scan the realistic baud set:
 * a reply at ANY baud revives the panel; total silence at all of them is
 * the electrical verdict (ribbon / display). Runs while the touch task is
 * parked (not ready) — we own the wire. */
void nsp_display_baud_scan(void) {
    if (s_display_ready) return;
    if (s_display_raw_mode) return;  // someone else owns the wire
    static const int bauds[] = {115200, 9600, 38400, 57600, 230400, 921600};
    char l[80];
    s_display_raw_mode = true;  // the scan owns the wire end to end
    for (unsigned i = 0; i < sizeof(bauds) / sizeof(bauds[0]); i++) {
        uart_set_baudrate(DISPLAY_UART, bauds[i]);
        uart_flush_input(DISPLAY_UART);
        uart_write_bytes(DISPLAY_UART, "connect", 7);
        uart_write_bytes(DISPLAY_UART, END_SEQ, 3);
        vTaskDelay(pdMS_TO_TICKS(300));
        uint8_t buf[128];
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(400));
        nsp_rx_count(n);
        snprintf(l, sizeof(l), "diag: baud %d -> %d bytes%s", bauds[i], n,
                 n > 3 ? " REPLY!" : "");
        nsp_mqtt_publish_log(l);
        if (n > 3) {  // the display answers HERE — revive at this baud
            s_display_ready = true;
            s_warnings[0] = '\0';
            s_display_raw_mode = false;
            nsp_display_after_handshake();
            return;
        }
    }
    uart_set_baudrate(DISPLAY_UART, DISPLAY_BAUD);  // back to the default
    s_display_raw_mode = false;
    nsp_mqtt_publish_log("diag: no reply at any baud");
}

bool nsp_display_restart(void) {
    /* P208#5: raw mode during the power-cycle + re-handshake. */
    s_display_raw_mode = true;
    gpio_set_level(DISPLAY_POWER_PIN, 1);
    vTaskDelay(pdMS_TO_TICKS(1000));
    gpio_set_level(DISPLAY_POWER_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(1000));
    nsp_display_drain(1500);
    s_display_ready = false;
    bool ok = nsp_display_handshake(3);
    /* P279 HIGH fix: raw mode was left STUCK after a restart —
     * the touch task skipped every frame until the next reboot. */
    s_display_raw_mode = false;
    /* P310: a successful restart must actually TAKE OVER the screen — the
     * old code re-handshaked and left the display on the splash forever
     * (the user's "stuck at logo"). */
    if (ok) {
        s_display_ready = true;
        nsp_display_after_handshake();
        /* P362: THE DISPLAY HEALTH CHECK — the kit's HMI announces its own
         * boot (program.nx: printh 88 ff ff ff) only when the flash content
         * is valid; a display showing "System-Data-ERROR" never does. The
         * restart's power-cycle JUST booted the display: if no announcement
         * arrives, the flash content is broken and the panel can repair
         * itself by re-delivering the TFT — no human in the loop. Capped at
         * 2 auto-repairs per boot (a genuinely bad TFT file must not loop
         * forever; the user is told loudly instead). */
        {
            bool announced = false;
            int64_t dead = esp_timer_get_time() + 4000000LL;
            while (esp_timer_get_time() < dead) {
                uint8_t b[16] = {0};
                int n = nsp_display_read(b, sizeof(b), 400);
                for (int i = 0; i + 3 < n; i++) {
                    if (b[i] == 0x88 && b[i + 1] == 0xFF &&
                        b[i + 2] == 0xFF && b[i + 3] == 0xFF) {
                        announced = true;
                        break;
                    }
                }
                if (announced) break;
            }
            /* P363 (user report: the panel degraded after the restarts): the
             * auto-repair here misfires — a panel reboot does NOT reboot the
             * display (it stays powered), so after a plain restart there is
             * no announcement to find and this check would re-deliver the
             * STOCK TFT over the user's dashboard. The detection stays
             * (log-only); the auto-repair lives ONLY in the delivery's own
             * verdict path, where the display truly rebooted by itself. */
            if (!announced) {
                nsp_mqtt_publish_log("DISPLAY: no boot announcement after restart — the TFT flash may be broken (log-only; re-deliver from the studio if the glass shows the error)");
            }
        }
        return true;
    }
    /* P316: the restart failed at the default baud — scan the rest before
     * declaring the display dead (an interrupted TFT upload may have left
     * the Nextion at another speed). */
    nsp_display_baud_scan();
    return s_display_ready;
}

/* ---- Page layer (alpha): clock/date rendering + touch decode ----
 * The panel's HMI (NSPanelManager-style, same object names) exposes:
 *   screensaver.curTime / curDay / curAMPM  (+ the _minimal variants)
 * The manager publishes nspanel/status/{time,date,ampm}; we render them.
 * Touch events arrive as 0x65 <page> <component> <event> FF FF FF. */

static const char *SCREENSAVER_PAGE = "screensaver";

/* P356: the screensaver activation timeout. The screensaver appeared only
 * at boot/handshake; once the user left it nothing returned (the user's
 * report: "after entering the menu, there is no time-out for the
 * screensaver to appear again"). After <timeout> seconds without a touch
 * the panel navigates back. The timeout rides the screensaver payload
 * (default 15 s); 0 or negative disables the idle return. */
static volatile int s_screensaver_idle_timeout = 15;
/* P361 (audit M2): a volatile int64_t is TWO 32-bit loads on Xtensa — the
 * idle poll could read a torn value and navigate mid-interaction. The
 * touch clock is a wrap-safe uint32_t tick now (49 days at 1000 Hz). */
static volatile uint32_t s_last_touch_tick = 0;
static volatile int s_last_component_page = -1;  // the last 0x65 page seen

void nsp_screensaver_set_idle_timeout(int secs) {
    /* P361 (audit M3): 0 disables the idle return — the old clamp mapped
     * "never" to 15 s. */
    int applied;
    if (secs == 0) {
        s_screensaver_idle_timeout = 0;
        applied = 0;
    } else {
        applied = (secs >= 5 && secs <= 3600) ? secs : 15;
        s_screensaver_idle_timeout = applied;
    }
    /* P363: the evidence line — the payload's value vs what was applied. */
    {
        char l[80];
        snprintf(l, sizeof(l), "screensaver: timeout requested %d -> applied %ds",
                 secs, applied);
        nsp_mqtt_publish_log(l);
    }
}

void nsp_screensaver_idle_poll(void) {
    if (!s_display_ready || s_display_raw_mode) return;
    int timeout_s = s_screensaver_idle_timeout;
    if (timeout_s <= 0) return;
    /* wrap-safe tick difference (P361 M2) */
    uint32_t now_tick = (uint32_t)xTaskGetTickCount();
    uint32_t elapsed_ticks = now_tick - s_last_touch_tick;
    if (elapsed_ticks < (uint32_t)timeout_s * configTICK_RATE_HZ) return;
    int page = s_last_component_page;
    if (page == 1 || page == 3) return;  // already on the screensaver/mini
    /* P363: the wire-level evidence — the poll's decision is INVISIBLE
     * otherwise (the user's report: the screensaver timeout is not
     * working; every static review passed). Log the navigation once per
     * timeout period. */
    {
        char l[96];
        snprintf(l, sizeof(l),
                 "screensaver: idle poll firing (timeout=%ds page=%d idle=%us)",
                 timeout_s, page, (unsigned)(elapsed_ticks / configTICK_RATE_HZ));
        nsp_mqtt_publish_log(l);
    }
    nsp_display_show_screensaver();
    s_last_component_page = 1;   // we are on the screensaver now
    s_last_touch_tick = now_tick;  // don't re-fire every housekeeping second
}

/* P364: the last-known clock/date strings — the manager publishes them
 * every minute, but the SCREENSAVER page's text objects hold their
 * compiled defaults ("00:00") until the NEXT publish lands: after the
 * idle poll navigates, the user saw 00:00 for a few seconds (their
 * report). The panel stores the last values and writes them the moment
 * the screensaver page opens. */
static std::string s_last_time;
static std::string s_last_date;
static std::string s_last_ampm;
static void nsp_display_set_text(const char *object, const char *value);  // P364: defined below

void nsp_display_show_screensaver(void) {
    if (!s_display_ready) return;
    std::string cmd = std::string("page ") + SCREENSAVER_PAGE;
    nsp_display_send_command(cmd.c_str());
    /* P364: the clock shows the REAL time immediately — the page's text
     * objects otherwise hold "00:00" until the next minute-publish. */
    if (!s_last_time.empty())
        nsp_display_set_text("screensaver.curTime", s_last_time.c_str());
    if (!s_last_date.empty())
        nsp_display_set_text("screensaver.curDay", s_last_date.c_str());
    if (!s_last_ampm.empty())
        nsp_display_set_text("screensaver.curAMPM", s_last_ampm.c_str());
}

/* P208#1: Nextion text objects take .txt= — the v1 did exactly this;
 * without it every clock/date write is silently ignored (the static
 * screen). P208#4: the value is sanitized — MQTT-supplied text could
 * otherwise terminate the command and inject display script (v1 had
 * the same guard). */
static void nsp_display_set_text(const char *object, const char *value) {
    if (!s_display_ready) return;
    /* P306: one canonical sanitiser for every .txt write. The old inline
     * whitelist is a subset of nsp_display_clean(), which also admits the
     * degree glyph and '%' (needed by weather) while still stripping
     * quotes, semicolons, 0xFF and control bytes. */
    const std::string clean = nsp_display_clean(value ? value : "", 24);
    const std::string cmd = std::string(object) + ".txt=\"" + clean + "\"";
    nsp_display_send_command(cmd.c_str());
}

void nsp_display_set_clock(const std::string &time_str) {
    /* P364: store for the immediate write on every screensaver navigation. */
    s_last_time = time_str;
    nsp_display_set_text("screensaver.curTime", time_str.c_str());
    nsp_display_set_text("mini.curTime", time_str.c_str());
}

void nsp_display_set_date(const std::string &date_str) {
    s_last_date = date_str;
    nsp_display_set_text("screensaver.curDay", date_str.c_str());
    nsp_display_set_text("mini.curDay", date_str.c_str());
}

void nsp_display_set_ampm(const std::string &ampm_str) {
    s_last_ampm = ampm_str;
    nsp_display_set_text("screensaver.curAMPM", ampm_str.c_str());
    nsp_display_set_text("mini.curAMPM", ampm_str.c_str());
}

/* Touch listener: decode 0x65 events, wake the screen on touch. */
void nsp_display_touch_task(void *);

extern "C" void nsp_relay_toggle_pub(int relay);  // P210: file scope (P160 rule)
extern void nsp_mqtt_publish_log(const char *line);  // P256: touch-frame logging
void nsp_display_touch_task_start(void) {
    xTaskCreatePinnedToCore(nsp_display_touch_task, "touch", 4096, nullptr, 0, nullptr, 0);
}

/* HMI map — the authored NSPanel Core UI (P210, component ids verified by
 * decompiling the compiled TFT: page2=home, page4=room, page6=scenes). */
#define HMI_HOME_PAGE_ID 2
#define HMI_ROOM_PAGE_ID 4
#define HMI_SCENES_PAGE_ID 6
/* home: 1=bg, 2=rel1, 3=rel2, 4=room hotspot, 6=scenes hotspot */
#define HMI_HOME_REL1 2
#define HMI_HOME_REL2 3
#define HMI_HOME_ROOM 4
#define HMI_HOME_SCENES 6
/* room: 1=bg, 2=rel1, 3=rel2, 4=back hotspot */
#define HMI_ROOM_REL1 2
#define HMI_ROOM_REL2 3
#define HMI_ROOM_BACK 4
/* scenes: 1=bg, 2=back hotspot */
#define HMI_SCENES_BACK 2

/* P208#5: the touch task races the handshake/TFT uploader for the same
 * UART — it swallows reply bytes (comok, 0x05) and desyncs sequences.
 * The flag lives at file scope (declared above); the setter is here. */
void nsp_display_set_raw_mode(bool on) { s_display_raw_mode = on; }

void nsp_display_touch_task(void *) {
    /* P184: decode extracted to touch_decode.cpp (HOST-UNIT-TESTED). */
    uint8_t buf[64];
    /* P279 MEDIUM fix: a frame SPLIT across two reads was lost on both
     * sides (the decoder sees no terminator, then no header) — a steady
     * per-touch probability, the "quick taps lost" suspect. A residual
     * buffer carries the unconsumed tail into the next read. */
    static uint8_t resid[16];
    static size_t resid_len = 0;
    for (;;) {
        /* P312: display-dead suspension — parked while the display is not
         * answering (nothing to decode; the revival clears the flag). */
        if (!s_display_ready) {
            vTaskDelay(pdMS_TO_TICKS(3000));
            continue;
        }
        /* P361 (audit CRITICAL C2): the read happened BEFORE the raw-mode
         * check — while s_display_ready was true the touch task ACTIVELY
         * read the same UART as the TFT streamer/handshake and CONSUMED
         * the display's replies (comok, the 0x05 ACKs, the 0x08s): the
         * "no comok"/"no block reply" strike counters. Park BEFORE
         * reading; the raw-mode owner drains the wire itself. */
        if (s_display_raw_mode) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf) - resid_len, pdMS_TO_TICKS(200));
        nsp_rx_count(n);
        if (n > 0 && resid_len) {
            memmove(buf + resid_len, buf, n);
            memcpy(buf, resid, resid_len);
            n += resid_len;
            resid_len = 0;
        }
        /* P208#6: a negative UART result cast to size_t scanned out of
         * bounds. */
        if (n <= 0) continue;
        auto frames = nsp_touch_decode(buf, (size_t)n);
        /* P328: a garbage flood (the floating RX, the baud-mismatched
         * display) decodes to NOTHING — consumed 0 of every chunk (the
         * host test pins it) — and the read returns instantly while data
         * flows: the loop burned full CPU without yielding. A tick of
         * sleep on zero progress costs nothing when frames ARE flowing. */
        if (frames.empty() && n > 0) {
            vTaskDelay(pdMS_TO_TICKS(1));
        }
        if (!frames.empty()) {
            size_t used = frames.back().consumed + (frames.front().page == -1 || frames.front().consumed ? 0 : 0);
            // the consumed offsets are per-frame relative to the decode start —
            // walk them to find the total consumed bytes
            size_t total = 0;
            for (const auto &fr : frames) total += fr.consumed;
            resid_len = (size_t)n > total ? (size_t)n - total : 0;
            if (resid_len > sizeof(resid)) resid_len = sizeof(resid);
            memcpy(resid, buf + total, resid_len);
        }
        for (const auto &f : frames) {
            int page = f.page, component = f.component, event = f.event;
            bool pressed = (event == 1);
            /* P356: every frame is activity — the idle clock restarts. The
             * 0x65 frames also reveal the page (the idle poll needs to know
             * whether the panel is already on the screensaver pages). */
            s_last_touch_tick = (uint32_t)xTaskGetTickCount();
            if (f.page >= 0) s_last_component_page = f.page;
            /* P256: every touch frame the panel receives is visible in the
             * log — the relay-latency diagnosis (quick taps lost?) needs
             * the raw frames with their arrival spacing. */
            {
                char l[80];
                if (f.page == -1)  // P269: a coordinate frame
                    snprintf(l, sizeof(l), "touch: x=%d y=%d e=%d", f.x, f.y, f.event);
                else
                    snprintf(l, sizeof(l), "touch: p=%d c=%d e=%d", page, component, event);
                nsp_mqtt_publish_log(l);
            }

            /* P269: the SWIPE — the coordinate frames (0x67, sendxy=1)
             * track the gesture on the dashboard pages: a horizontal drag
             * of >= 100 px (and < 80 px vertical) navigates to the next
             * (drag left) or previous (drag right) dashboard page, and the
             * following component release is suppressed so a swipe over a
             * tile never toggles it. */
            if (f.page == -1) {  // a 0x67 coordinate frame
                if (f.event == 1) {
                    s_swipe_x1 = f.x;
                    s_swipe_y1 = f.y;
                    s_swipe_page = -2;       // the press seen; the page arrives in the 0x65
                    s_swipe_navigated = false;  // P279 LOW fix: never sticky
                } else if (f.event == 0 && s_swipe_page >= 0 &&
                           nsp_dash_is_dash_page(s_swipe_page)) {
                    int dx = f.x - s_swipe_x1;
                    int dy = f.y - s_swipe_y1;
                    int count = nsp_dash_page_count();
                    int idx = nsp_dash_page_index(s_swipe_page);
                    if (count > 1 && idx >= 0 && abs(dx) >= 100 && abs(dy) < 80) {
                        int next = (idx + (dx < 0 ? 1 : count - 1)) % count;
                        int target = nsp_dash_page_id(next);
                        char cmd[24];
                        snprintf(cmd, sizeof(cmd), "dp=%d", target);
                        nsp_display_send_command(cmd);
                        s_swipe_navigated = true;
                        char l[64];
                        snprintf(l, sizeof(l), "swipe: dx=%d -> page %d", dx, target);
                        nsp_mqtt_publish_log(l);
                    }
                    s_swipe_page = -1;
                }
                continue;  // the coordinate frames run no component chains
            }
            /* the 0x65 press reveals the page the gesture is on */
            if (pressed) {
                s_swipe_navigated = false;  // P279 LOW fix: a new press clears the suppression
                if (nsp_dash_is_dash_page(page)) {
                    s_swipe_page = page;  // the coords are already stashed
                }
            }
            /* the suppressed release: the swipe already navigated */
            if (s_swipe_navigated && !pressed && nsp_dash_is_dash_page(page)) {
                s_swipe_navigated = false;
                s_swipe_page = -1;
                continue;
            }
            /* P208#4: wake on release from the screensaver pages only —
             * the old code navigated on press from EVERY page (mid-
             * interaction jumps) and ignored screensaver releases. */
            if ((page == 1 || page == 3) && !pressed) {
                /* P356b: with a delivered design, the wake lands on the
                 * USER'S dashboard — the first dash page (the map's second
                 * entry; the contract is [menu, dash…, details], P234
                 * page_ids) — not the stock home with its placeholder
                 * buttons (the user's screenshot: kit-default "newtxt").
                 * Without an adopted map: the stock home, as before. */
                int map_count = nsp_dash_page_count();
                if (map_count >= 2) {
                    int target = nsp_dash_page_id(1);
                    if (target >= 0) {
                        char wcmd[24];
                        snprintf(wcmd, sizeof(wcmd), "dp=%d", target);
                        nsp_display_send_command(wcmd);
                        /* P361 (audit L9): the tracked "last page" must
                         * follow the navigation, or the idle poll thinks
                         * the panel is still asleep until the next 0x65. */
                        s_last_component_page = target;
                    } else {
                        nsp_display_send_command("page home");
                        s_last_component_page = 2;
                    }
                } else {
                    nsp_display_send_command("page home");
                    s_last_component_page = 2;
                }
            } else if (nsp_dash_is_dash_page(page)) {
                /* P234: dash pages publish ONLY — the manager owns every
                 * action there (it generated the layout). No local relay
                 * chains can misfire on a page the manager re-authored.
                 * P269: the SWIPE — the coordinates (0x67, sendxy=1) track
                 * the gesture; a horizontal drag >= 100 px navigates to the
                 * next/previous dashboard page (the manager's dash_map
                 * order), and the release's component event is suppressed
                 * so a swipe over a tile never toggles it. */
            } else if (event == 0) {  // releases act (P210)
                /* P357: with a DELIVERED design (the map adopted), home and
                 * the menu are GENERATED layouts — the kit-era component
                 * constants cannot know their ids (the relays may not even
                 * exist there: the integration's setting decides). Their
                 * presses PUBLISH ONLY; the manager routes every action
                 * (the rel toggles, the menu hotspots, the navigation)
                 * against the map it generated. Stock-TFT panels (no map)
                 * keep the kit chains below unchanged. */
                bool design_owned =
                    nsp_dash_page_count() > 0 &&
                    (page == HMI_HOME_PAGE_ID || page == HMI_ROOM_PAGE_ID);
                if (design_owned) {
                    /* publish-only — the touch goes out below */
                } else if (page == HMI_HOME_PAGE_ID) {
                    if (component == HMI_HOME_REL1) nsp_relay_toggle_pub(1);
                    else if (component == HMI_HOME_REL2) nsp_relay_toggle_pub(2);
                    else if (component == HMI_HOME_ROOM) nsp_display_send_command("page room");
                    else if (component == HMI_HOME_SCENES) nsp_display_send_command("page scenes");
                } else if (page == HMI_ROOM_PAGE_ID) {
                    if (component == HMI_ROOM_REL1) nsp_relay_toggle_pub(1);
                    else if (component == HMI_ROOM_REL2) nsp_relay_toggle_pub(2);
                    else if (component == HMI_ROOM_BACK) nsp_display_send_command("page home");
                } else if (page == HMI_SCENES_PAGE_ID) {
                    if (component == HMI_SCENES_BACK) nsp_display_send_command("page home");
                }
            }
            extern void nsp_mqtt_publish_touch(int page, int component, int event);
            nsp_mqtt_publish_touch(page, component, event);
        }
    }
}

/* P210: keep the display buttons in step with the relays (dual-state val). */
void nsp_display_relay(int relay, bool state) {
    if (!nsp_display_ready()) return;
    char cmd[64];
    snprintf(cmd, sizeof(cmd), "home.rel%d.val=%d", relay, state ? 1 : 0);
    nsp_display_send_command(cmd);
    snprintf(cmd, sizeof(cmd), "room.rel%d.val=%d", relay, state ? 1 : 0);
    nsp_display_send_command(cmd);
}

/* P361 (audit): nsp_display_uart_baud / nsp_display_uart_set_baud were
 * unused (the transfer uses nsp_display_set_tft_baud) — removed. */

/* P211b: display power control for the upload sequence (the proven
 * upstream flow power-cycles the display before the escape string). */
void nsp_display_power(int state) {
    // P122 lesson: HIGH = OFF on this board (power-cycling browns out weak
    // supplies at boot — but in the UPLOAD flow the display is explicitly
    // restarted, which is the upstream-proven requirement).
    gpio_set_level(DISPLAY_POWER_PIN, state ? 1 : 0);
}

/* P211b: exports for the TFT uploader (ota.cpp) — single access point. */
int nsp_display_read(uint8_t *buf, int len, int timeout_ms) {
    int n = uart_read_bytes(DISPLAY_UART, buf, (size_t)len, pdMS_TO_TICKS(timeout_ms));
    nsp_rx_count(n);
    return n;
}
bool nsp_display_handshake_pub(int attempts) {
    return nsp_display_handshake(attempts);
}

/* P358: the post-delivery navigation — the freshly rebooted display must
 * leave the splash (the authored logo) the moment the link is proven. */
void nsp_display_after_handshake_pub(void) {
    nsp_display_after_handshake();
}
