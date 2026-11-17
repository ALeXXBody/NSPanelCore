/* NSPanel Core — in-RAM log ring buffer (pure, host-testable).
 *
 * The panel's own log view: every notable event lands here AND on the
 * MQTT log topic. Fixed capacity, wraps around, dumps oldest→newest.
 */

#pragma once
#include <string>
#include <vector>

class NspLogBuf {
public:
    explicit NspLogBuf(size_t capacity);
    void add(const std::string &line);
    /* Newline-joined, oldest first. Empty buffer → empty string. */
    std::string dump() const;
    size_t size() const;

private:
    std::vector<std::string> lines_;
    size_t cap_;
    size_t next_ = 0;
    size_t count_ = 0;
};
