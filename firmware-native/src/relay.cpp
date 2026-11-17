/* NSPanel Core — relay + physical button layer (v1 ButtonManager parity).
 *
 * Relays:  GPIO22 = relay 1, GPIO19 = relay 2 (reverse_relays swaps them).
 * Buttons: GPIO14 = button 1, GPIO27 = button 2 (interrupt + 50 ms debounce).
 * Wire:    r{N}_cmd ("1"/"0") drives; r{N}_state ("1"/"0") published retained.
 * Modes:   DIRECT (press toggles relay), FOLLOW (relay follows), DETACHED and
 *          CUSTOM_MQTT (publish to the configured button topic).
 */

#include "relay_cmd.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "protocol.h"
#include "config.h"

#define RELAY1_PIN GPIO_NUM_22
#define RELAY2_PIN GPIO_NUM_19
#define BUTTON1_PIN GPIO_NUM_14
#define BUTTON2_PIN GPIO_NUM_27
#define BUTTON_DEBOUNCE_MS 50

static bool s_relay1 = false;
static bool s_relay2 = false;
static volatile int s_btn1_state = 0;
static volatile int s_btn2_state = 0;
static int64_t s_btn1_last_us = 0;
static int64_t s_btn2_last_us = 0;

extern void nsp_mqtt_publish_relay_state(int relay, bool state);

static int map_relay(int relay) {
    if (g_cfg.reverse_relays) {
        return relay == 1 ? 2 : 1;
    }
    return relay;
}

int nsp_relay_gpio(int relay) {
    relay = map_relay(relay);
    return relay == 1 ? (gpio_num_t)RELAY1_PIN : (gpio_num_t)RELAY2_PIN;
}

bool nsp_relay_state(int relay) {
    relay = map_relay(relay);
    return relay == 1 ? s_relay1 : s_relay2;
}

void nsp_relay_init(void) {
    for (int r = 1; r <= 2; r++) {
        gpio_config_t io = {};
        io.pin_bit_mask = 1ULL << (int)nsp_relay_gpio(r);
        io.mode = GPIO_MODE_OUTPUT;
        gpio_config(&io);
        gpio_set_level((gpio_num_t)nsp_relay_gpio(r), 0);
    }
    gpio_config_t btn = {};
    btn.pin_bit_mask = (1ULL << BUTTON1_PIN) | (1ULL << BUTTON2_PIN);
    btn.mode = GPIO_MODE_INPUT;
    btn.pull_up_en = GPIO_PULLUP_ENABLE;
    gpio_config(&btn);
}

void nsp_relay_set(int relay, bool state) {
    relay = map_relay(relay);
    gpio_set_level((gpio_num_t)nsp_relay_gpio(relay), state ? 1 : 0);
    if (relay == 1) s_relay1 = state; else s_relay2 = state;
    nsp_mqtt_publish_relay_state(map_relay(relay) == relay ? relay : relay, state);
    extern void nsp_display_relay(int relay, bool state);  // P210: buttons follow
    nsp_display_relay(relay, state);
}

/* Handle an incoming r{N}_cmd payload ("1"/"0"). */
void nsp_relay_handle_cmd(int relay, const std::string &payload) {
    /* P184: parse extracted to relay_cmd.cpp (HOST-UNIT-TESTED). Fail-safe:
     * invalid payloads are IGNORED — the old code treated any non-"1"/"on"
     * payload as OFF, so a stray "1 " (trailing space) would drop a live
     * relay instead of being rejected. */
    int v = nsp_relay_parse(payload);
    if (v < 0) return;  // ignore garbage; never drive the GPIO from it
    nsp_relay_set(relay, v == 1);
}

/* Physical button press (debounced, active-low buttons). */
static void nsp_button_pressed(int button) {
    // Alpha: DIRECT mode — press toggles the mapped relay.
    int relay = button;
    bool new_state = !nsp_relay_state(relay);
    nsp_relay_set(relay, new_state);
}

/* Called by the button scan loop (polling the GPIOs, 50 ms debounce). */
void nsp_button_scan(void) {
    int64_t now = esp_timer_get_time();
    int b1 = gpio_get_level(BUTTON1_PIN) == 0 ? 1 : 0;  // active-low
    int b2 = gpio_get_level(BUTTON2_PIN) == 0 ? 1 : 0;
    if (b1 != s_btn1_state && now - s_btn1_last_us > (int64_t)BUTTON_DEBOUNCE_MS * 1000) {
        if (b1) {  // pressed (falling edge)
            s_btn1_last_us = now;
            s_btn1_state = b1;
            nsp_button_pressed(1);
        }
        s_btn1_state = b1;
    }
    if (b2 != s_btn2_state && now - s_btn2_last_us > (int64_t)BUTTON_DEBOUNCE_MS * 1000) {
        if (b2) {
            s_btn2_last_us = now;
            s_btn2_state = b2;
            nsp_button_pressed(2);
        }
        s_btn2_state = b2;
    }
}

/* P210: the display's touch buttons toggle relays directly. */
extern "C" void nsp_relay_toggle_pub(int relay) {
    bool new_state = !nsp_relay_state(relay);
    nsp_relay_set(relay, new_state);
}
