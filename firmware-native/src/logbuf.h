/* NSPanel Core — in-RAM log ring buffer (pure, host-testable).
 *
 * The panel's own log view: every notable event lands here AND on the
 * MQTT log topic. Fixed capacity, wraps around, dumps oldest→newest.
 */

#pragma once
#include <string>
#include <vector>
#include <mutex>

class NspLogBuf {
public:
    explicit NspLogBuf(size_t capacity);
    void add(const std::string &line);
    /* Newline-joined, oldest first. Empty buffer → empty string. */
    std::string dump() const;
    size_t size() const;

private:
    /* P279 MEDIUM fix: the buffer was written from 5+ tasks with no lock —
     * the concurrent std::string assignments could corrupt the heap. */
    mutable std::mutex mtx_;
    std::vector<std::string> lines_;
    size_t cap_;
    size_t next_ = 0;
    size_t count_ = 0;
};
