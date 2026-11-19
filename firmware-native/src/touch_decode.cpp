/* NSPanel Core — Nextion 0x65 touch-frame decoder (pure, host-testable). */

#include "touch_decode.h"

std::vector<NspTouchEvent> nsp_touch_decode(const unsigned char *buf, size_t len) {
    std::vector<NspTouchEvent> out;
    if (buf == nullptr) return out;
    for (size_t i = 0; i < len; i++) {
        if (buf[i] == 0x65) {
            /* the component frame: 0x65 <page> <comp> <event> FF FF FF */
            if (i + 7 <= len && buf[i + 4] == 0xFF && buf[i + 5] == 0xFF &&
                buf[i + 6] == 0xFF) {
                out.push_back({(int)buf[i + 1], (int)buf[i + 2], (int)buf[i + 3], 7, -1, -1});
                i += 6;
            }
        } else if (buf[i] == 0x67) {
            /* P269: the coordinate frame (sendxy=1):
             * 0x67 <x_hi> <x_lo> <y_hi> <y_lo> <event> FF FF FF */
            if (i + 9 <= len && buf[i + 6] == 0xFF && buf[i + 7] == 0xFF &&
                buf[i + 8] == 0xFF) {
                int x = (int)((buf[i + 1] << 8) | buf[i + 2]);
                int y = (int)((buf[i + 3] << 8) | buf[i + 4]);
                out.push_back({-1, -1, (int)buf[i + 5], 9, x, y});
                i += 8;
            }
        }
    }
    return out;
}
