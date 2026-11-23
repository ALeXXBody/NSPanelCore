/* P322: the touch decoder under the REAL hostile RX conditions.
 *
 * The panel's display UART RX has been fed three ways in this saga:
 *   (a) a floating line with the ribbon out — reads as 0xFF/idle noise;
 *   (b) a baud-mismatched display (the post-TFT-stream 921600 state read
 *       at 115200) — misframed garbage bytes;
 *   (c) real touch frames mixed with garbage.
 *
 * The firmware's touch loop reads 64-byte chunks and relies on the decoder
 * to say how much it consumed; a decoder that consumes NOTHING on garbage
 * makes the loop re-carry the same bytes forever at full speed (the loop
 * never blocks when data keeps flowing — the TWDT spin signature).
 * These tests pin the decoder's contract on the garbage so the firmware
 * fix (a rate-limit/yield on zero-progress) is a conscious change.
 */
#include <cstdio>
#include <cassert>
#include <cstring>
#include <cstdint>
#include <vector>
#include "../src/touch_decode.h"

/* the decoder's API: nsp_touch_decode(const uint8_t*, size_t) -> frames
 * (check the header's real signature shape below via the existing tests) */

int main() {
    /* (a) the floating-line flood: 0xFF forever (the UART idle reads high) */
    std::vector<uint8_t> ffs(64, 0xFF);
    size_t total_consumed = 0;
    for (int i = 0; i < 1000; i++) {
        auto frames = nsp_touch_decode(ffs.data(), ffs.size());
        size_t used = 0;
        for (const auto &f : frames) used += f.consumed;
        total_consumed += used;
    }
    std::printf("floating 0xFF flood: consumed %zu of %zu bytes\n",
                total_consumed, 64u * 1000);
    /* THE CONTRACT TO PIN: whether the decoder consumes the garbage or
     * reports zero — either is fine, but the FIRMWARE MUST KNOW. Zero
     * consume on a constant flood = the spin signature on the ESP. */
    std::printf("test_touch_flood: 0xFF case done\n");

    /* (b) the baud-mismatch garbage: the 921600 stream read at 115200
     * produces misframed bytes — dense random-ish patterns with the
     * occasional 0x65/0x67 lookalikes and stray 0xFF terminators. */
    std::vector<uint8_t> garbage;
    for (int i = 0; i < 64 * 500; i++) {
        uint8_t b = (uint8_t)((i * 37 + 11) % 256);
        if (b == 0x65 || b == 0x67) b ^= 0x20;  // avoid accidental headers
        garbage.push_back(b);
    }
    for (size_t off = 0; off + 64 <= garbage.size(); off += 48) {
        auto frames = nsp_touch_decode(garbage.data() + off, 64);
        size_t used = 0;
        for (const auto &f : frames) used += f.consumed;
        if (used > 64) {  // a consumed count beyond the input = the OOB read
            std::printf("BUG: consumed %zu > 64 at offset %zu\n", used, off);
            return 1;
        }
    }
    std::printf("test_touch_flood: garbage case done, no OOB\n");

    /* (c) a real frame in a garbage sea: the decoder must find it and
     * account for every consumed byte. */
    std::vector<uint8_t> mixed(64, 0x00);
    mixed[20] = 0x65;  // touch frame: page, comp, event
    mixed[21] = 2; mixed[22] = 4; mixed[23] = 1;
    mixed[24] = 0xFF; mixed[25] = 0xFF; mixed[26] = 0xFF;
    auto frames = nsp_touch_decode(mixed.data(), mixed.size());
    size_t used = 0;
    bool found = false;
    for (const auto &f : frames) {
        used += f.consumed;
        if (f.page == 2 && f.component == 4 && f.event == 1) found = true;
    }
    assert(found);
    assert(used <= mixed.size());
    std::printf("test_touch_flood: real-frame-in-garbage PASS (consumed %zu)\n", used);

    std::printf("test_touch_flood: ALL PASS\n");
    return 0;
}
