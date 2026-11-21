/* P317: the fault capture — the IDF's task-wdt diagnostic NAMES the tasks
 * that starved the watchdog, but it prints via ESP_LOG (the serial console,
 * never attached). The crash loop needs those lines where the panel's OWN
 * web UI can read them — including across the reboot that follows, because
 * the panel lives only seconds. The ring lives in .noinit (survives
 * esp_restart, not power-on), written lock-free so the WDT interrupt
 * context can call it. The captured lines surface on /status.json. */
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <string>
#include "esp_log.h"

#define FAULT_SLOTS 8
#define FAULT_LEN 96

/* .noinit: survives a soft reset (the WDT reset IS one). */
static char s_fault_ring[FAULT_SLOTS][FAULT_LEN]
    __attribute__((section(".noinit")));
static volatile int s_fault_head __attribute__((section(".noinit")));
static volatile int s_fault_wrapped __attribute__((section(".noinit")));

static void fault_append(const char *line) {
    int head = s_fault_head;
    /* bounded copy, no locks — ISR context safe */
    size_t n = strlen(line);
    if (n > FAULT_LEN - 1) n = FAULT_LEN - 1;
    char *slot = s_fault_ring[head];
    memcpy(slot, line, n);
    slot[n] = '\0';
    int next = head + 1;
    if (next >= FAULT_SLOTS) {
        next = 0;
        s_fault_wrapped = 1;
    }
    s_fault_head = next;
}

static int fault_vprintf(const char *fmt, va_list args) {
    char buf[320];
    int n = vsnprintf(buf, sizeof(buf) - 1, fmt, args);
    if (n > 0) {
        buf[n < (int)sizeof(buf) - 1 ? n : (int)sizeof(buf) - 1] = '\0';
        /* the death sentences only — the rest of the ESP_LOG flood is noise */
        if (strstr(buf, "task_wdt") || strstr(buf, "Guru Meditation") ||
            strstr(buf, "abort()") || strstr(buf, "assert failed")) {
            fault_append(buf);
        }
    }
    return n;
}

void nsp_fault_capture_install(void) {
    /* first boot: the .noinit ring starts as garbage — stamp a clean head */
    if (s_fault_head < 0 || s_fault_head >= FAULT_SLOTS) {
        s_fault_head = 0;
        s_fault_wrapped = 0;
        for (int i = 0; i < FAULT_SLOTS; i++) s_fault_ring[i][0] = '\0';
    }
    esp_log_set_vprintf(fault_vprintf);
}

std::string nsp_fault_dump(void) {
    std::string out;
    int start = s_fault_wrapped ? s_fault_head : 0;
    int count = s_fault_wrapped ? FAULT_SLOTS : s_fault_head;
    for (int i = 0; i < count; i++) {
        const char *slot = s_fault_ring[(start + i) % FAULT_SLOTS];
        if (slot[0] == '\0') continue;
        if (!out.empty()) out += " || ";
        out += slot;
    }
    return out;
}
