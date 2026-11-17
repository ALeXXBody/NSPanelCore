/* NSPanel Core — Nextion 0x65 touch-frame decoder (pure, host-testable). */

#include "touch_decode.h"

std::vector<NspTouchEvent> nsp_touch_decode(const unsigned char *buf, size_t len) {
    std::vector<NspTouchEvent> out;
    if (buf == nullptr) return out;
    for (size_t i = 0; i + 7 <= len; i++) {
        if (buf[i] != 0x65) continue;
        if (buf[i + 4] == 0xFF && buf[i + 5] == 0xFF && buf[i + 6] == 0xFF) {
            out.push_back({(int)buf[i + 1], (int)buf[i + 2], (int)buf[i + 3], 7});
            i += 6;  // the loop's i++ makes the next scan start after the frame
        }
    }
    return out;
}
