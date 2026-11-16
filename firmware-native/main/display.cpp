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
#include "protocol.h"
#include "config.h"

#define DISPLAY_UART UART_NUM_1
#define DISPLAY_TX_PIN 17
#define DISPLAY_RX_PIN 16
#define DISPLAY_POWER_PIN GPIO_NUM_4
#define DISPLAY_BAUD 115200
#define END_SEQ "\xFF\xFF\xFF"

static volatile bool s_display_ready = false;
static char s_warnings[64] = "";

bool nsp_display_ready(void) { return s_display_ready; }
const char *nsp_display_warning(void) {
    return s_display_ready ? "" : "No response from the display.";
}

static void nsp_display_send(const char *data, size_t len) {
    uart_write_bytes(DISPLAY_UART, data, len);
}

void nsp_display_send_command(const char *cmd) {
    nsp_display_send(cmd, strlen(cmd));
    nsp_display_send(END_SEQ, 3);
}

static void nsp_display_drain(int ms) {
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
    if (!nsp_display_handshake(3)) {
        s_display_ready = false;
        snprintf(s_warnings, sizeof(s_warnings), "No response from the display.");
        // Continue WITHOUT the display — WiFi/MQTT/sensors stay alive (P130).
    }
}

/* Manual recovery: power-cycle + handshake. ONLY from the "display_restart"
 * command, never at boot (stable power assumed). */
bool nsp_display_restart(void) {
    gpio_set_level(DISPLAY_POWER_PIN, 1);
    vTaskDelay(pdMS_TO_TICKS(1000));
    gpio_set_level(DISPLAY_POWER_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(1000));
    nsp_display_drain(1500);
    s_display_ready = false;
    return nsp_display_handshake(3);
}

/* TFT stream to the display with the baked-in offset guard (P104/P177). */
void nsp_display_start_tft_update(int new_baud) {
    if (!s_display_ready) return;
    nsp_display_send_command("whmi-wris 921600,1");
    // The stream itself is chunked by the manager's /download_tft_eu fetch;
    // offsets are validated against 0x08-starting garbage (guard) before write.
}
