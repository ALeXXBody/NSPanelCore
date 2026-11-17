/* NSPanel Core — Nextion 0x65 touch-frame decoder (pure, host-testable).
 *
 * Frame: 0x65 <page> <component> <event> 0xFF 0xFF 0xFF.
 * Extracted from the UART touch task so the byte-level decode is unit
 * tested (R1): partial frames, garbage-prefixed frames, multiple frames
 * per buffer.
 */

#pragma once
#include <cstddef>
#include <vector>

struct NspTouchEvent {
    int page;
    int component;
    int event;      // 1 = pressed, 0 = released
    size_t consumed;  // bytes consumed for this frame (7)
};

/* Decode touch frames from buf[0..len). Returns the frames found (in
 * order). Bytes before a valid frame are skipped (display garbage). */
std::vector<NspTouchEvent> nsp_touch_decode(const unsigned char *buf, size_t len);
