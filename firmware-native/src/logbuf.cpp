/* NSPanel Core — in-RAM log ring buffer (pure, host-testable). */

#include "logbuf.h"

NspLogBuf::NspLogBuf(size_t capacity) : cap_(capacity ? capacity : 1) {
    lines_.resize(cap_);
}

void NspLogBuf::add(const std::string &line) {
    std::lock_guard<std::mutex> lock(mtx_);
    lines_[next_] = line;
    next_ = (next_ + 1) % cap_;
    if (count_ < cap_) count_++;
}

std::string NspLogBuf::dump() const {
    std::lock_guard<std::mutex> lock(mtx_);
    std::string out;
    size_t start = (count_ < cap_) ? 0 : next_;
    for (size_t i = 0; i < count_; i++) {
        if (i) out += "\n";
        out += lines_[(start + i) % cap_];
    }
    return out;
}

size_t NspLogBuf::size() const { return count_; }
