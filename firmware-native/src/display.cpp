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
#include <cstring>
#include <cstdio>
#include "esp_timer.h"
#include "protocol.h"
#include "config.h"
#include "dash_cmd.h"

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

void nsp_display_send(const char *data, size_t len) {  // P210: shared with the TFT streamer
    uart_write_bytes(DISPLAY_UART, data, len);
}

/* P279 HIGH fix: the clock/relay/dash writes were NOT gated on raw mode —
 * the MQTT task injected their bytes into a running whmi-wris block
 * transfer, corrupting the image mid-stream while progress read 100%. */
void nsp_display_send_command(const char *cmd) {
    if (s_display_raw_mode) return;  // the TFT upload owns the wire
    nsp_display_send(cmd, strlen(cmd));
    nsp_display_send(END_SEQ, 3);
}

void nsp_display_drain(int ms) {  // P210: shared
    uint8_t buf[64];
    int64_t start = esp_timer_get_time();
    while (esp_timer_get_time() - start < (int64_t)ms * 1000) {
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(25));
        (void)n;
    }
}

/* Handshake: send "connect", expect a reply (typically "comok..."). */
static bool nsp_display_handshake(int attempts) {
    for (int i = 0; i < attempts; i++) {
        uart_flush_input(DISPLAY_UART);
        nsp_display_send_command("connect");
        vTaskDelay(pdMS_TO_TICKS(1000));
        uint8_t buf[128];
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(1000));
        if (n > 3) {  // any non-trivial reply proves the link
            s_display_ready = true;
            s_warnings[0] = '\0';
            return true;
        }
    }
    return false;
}

void nsp_display_init(void) {
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << DISPLAY_POWER_PIN;
    io.mode = GPIO_MODE_OUTPUT;
    gpio_config(&io);
    gpio_set_level(DISPLAY_POWER_PIN, 0);  // display POWERED — never cycle at boot (P122)

    uart_config_t ucfg = {};
    ucfg.baud_rate = DISPLAY_BAUD;
    ucfg.data_bits = UART_DATA_8_BITS;
    ucfg.parity = UART_PARITY_DISABLE;
    ucfg.stop_bits = UART_STOP_BITS_1;
    ucfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    uart_driver_install(DISPLAY_UART, 512, 512, 0, nullptr, 0);
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
        nsp_display_show_screensaver();
        extern int nsp_relay_state(int relay);
        nsp_display_relay(1, nsp_relay_state(1));
        nsp_display_relay(2, nsp_relay_state(2));
    }
}

/* Manual recovery: power-cycle + handshake. ONLY from the "display_restart"
 * command, never at boot (stable power assumed). */
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
    return ok;
}

/* TFT stream to the display with the baked-in offset guard (P104/P177). */
void nsp_display_start_tft_update(int new_baud) {
    if (!s_display_ready) return;
    nsp_display_send_command("whmi-wris 921600,1");
    // The stream itself is chunked by the manager's /download_tft_eu fetch;
    // offsets are validated against 0x08-starting garbage (guard) before write.
}


/* ---- Page layer (alpha): clock/date rendering + touch decode ----
 * The panel's HMI (NSPanelManager-style, same object names) exposes:
 *   screensaver.curTime / curDay / curAMPM  (+ the _minimal variants)
 * The manager publishes nspanel/status/{time,date,ampm}; we render them.
 * Touch events arrive as 0x65 <page> <component> <event> FF FF FF. */

static const char *SCREENSAVER_PAGE = "screensaver";
static const char *SCREENSAVER_MINIMAL_PAGE = "mini";

void nsp_display_show_screensaver(void) {
    if (!s_display_ready) return;
    std::string cmd = std::string("page ") + SCREENSAVER_PAGE;
    nsp_display_send_command(cmd.c_str());
}

/* P208#1: Nextion text objects take .txt= — the v1 did exactly this;
 * without it every clock/date write is silently ignored (the static
 * screen). P208#4: the value is sanitized — MQTT-supplied text could
 * otherwise terminate the command and inject display script (v1 had
 * the same guard). */
static void nsp_display_set_text(const char *object, const char *value) {
    if (!s_display_ready) return;
    char clean[24] = "";
    size_t ci = 0;
    for (const char *p = value; *p && ci + 1 < sizeof(clean); p++) {
        char c = *p;
        if ((c >= '0' && c <= '9') || c == ':' || c == ' ' || c == '/' ||
            (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '-' ||
            c == '.') {
            clean[ci++] = c;
        }
    }
    clean[ci] = '\0';
    std::string cmd = std::string(object) + ".txt=\"" + clean + "\"";
    nsp_display_send_command(cmd.c_str());
}

void nsp_display_set_clock(const std::string &time_str) {
    nsp_display_set_text("screensaver.curTime", time_str.c_str());
    nsp_display_set_text("mini.curTime", time_str.c_str());
}

void nsp_display_set_date(const std::string &date_str) {
    nsp_display_set_text("screensaver.curDay", date_str.c_str());
    nsp_display_set_text("mini.curDay", date_str.c_str());
}

void nsp_display_set_ampm(const std::string &ampm_str) {
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
    for (;;) {
        int n = uart_read_bytes(DISPLAY_UART, buf, sizeof(buf), pdMS_TO_TICKS(200));
        /* P208#6: a negative UART result cast to size_t scanned out of
         * bounds; also skip while another sequence owns the UART (P208#5). */
        if (n <= 0 || s_display_raw_mode) continue;
        auto frames = nsp_touch_decode(buf, (size_t)n);
        for (const auto &f : frames) {
            int page = f.page, component = f.component, event = f.event;
            bool pressed = (event == 1);
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
                    s_swipe_navigated = false;
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
            if (pressed && nsp_dash_is_dash_page(page)) {
                s_swipe_page = page;  // the coords are already stashed
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
                nsp_display_send_command("page home");
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
                if (page == HMI_HOME_PAGE_ID) {
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

int nsp_display_uart_baud(void) { return DISPLAY_BAUD; }

/* P211b: the TFT streamer needs the UART baud changes from ota.cpp. */
void nsp_display_uart_set_baud(int baud) {
    uart_set_baudrate(DISPLAY_UART, baud);
}

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
    return uart_read_bytes(DISPLAY_UART, buf, (size_t)len, pdMS_TO_TICKS(timeout_ms));
}
bool nsp_display_handshake_pub(int attempts) {
    return nsp_display_handshake(attempts);
}
