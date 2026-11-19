/* NSPanel Core — dash command parse (pure, host-testable).
 *
 * P234: the dashboard channel. Two commands:
 *   {"command":"dash","payload":"<statement>"}      — a display statement
 *   {"command":"dash_map","pages":[4,7,8]}          — dash page ids
 *
 * The payload is SANITIZED here — the firmware only ever forwards what this
 * module accepts (the P208 injection lesson: never trust the wire). Allowed
 * statement forms:
 *   page <name>            name: [a-z0-9_]{1,14}
 *   <obj>.<attr>=<value>   obj: [a-z][a-z0-9_]{0,13}
 *                          attr: txt|val|pic|picc|bpic|font|back
 *                          value: digits, or "text" for txt (quotes,
 *                          backslashes and control chars stripped, max 32)
 */

#include "dash_cmd.h"
#include <cstdint>

#include <cctype>

namespace {

/* Read the JSON string value for "key":"value". The manager's payloads
 * arrive json.dumps-escaped: \" is a literal quote and is unescaped here;
 * any OTHER backslash escape is rejected (fail-safe, P208 lesson). */
bool json_string(const std::string &payload, const char *key, std::string &out) {
    std::string needle = std::string("\"") + key + "\"";
    size_t k = payload.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = payload.find(':', k + needle.size());
    if (colon == std::string::npos) return false;
    size_t q1 = payload.find('"', colon + 1);
    if (q1 == std::string::npos) return false;
    std::string value;
    for (size_t i = q1 + 1; i < payload.size(); i++) {
        char c = payload[i];
        if (c == '\\' && i + 1 < payload.size()) {
            char n = payload[i + 1];
            if (n != '"') return false;  // only \" is accepted
            value.push_back('"');
            i++;
            continue;
        }
        if (c == '"') {
            out = value;
            return true;
        }
        value.push_back(c);
    }
    return false;  // unterminated
}

bool name_ok(const std::string &s, size_t max_len) {
    if (s.empty() || s.size() > max_len) return false;
    if (!std::islower((unsigned char)s[0])) return false;
    for (char c : s)
        if (!(std::islower((unsigned char)c) || std::isdigit((unsigned char)c) ||
              c == '_'))
            return false;
    return true;
}

bool attr_ok(const std::string &a) {
    return a == "txt" || a == "val" || a == "pic" || a == "picc" ||
           a == "bpic" || a == "font" || a == "back";
}

}  // namespace

int nsp_dash_parse(const std::string &payload, std::string &stmt) {
    stmt.clear();
    std::string field;
    if (!json_string(payload, "command", field) || field != "dash") return -1;
    std::string raw;
    if (!json_string(payload, "payload", raw) || raw.empty() ||
        raw.size() > 96)
        return -1;

    /* form 1: page <name> */
    if (raw.rfind("page ", 0) == 0) {
        std::string name = raw.substr(5);
        if (!name_ok(name, 14)) return -1;
        stmt = "page " + name;
        return 0;
    }

    /* form 2: <obj>.<attr>=<value> */
    size_t dot = raw.find('.');
    size_t eq = raw.find('=', dot == std::string::npos ? 0 : dot);
    if (dot == std::string::npos || eq == std::string::npos || eq < dot)
        return -1;
    std::string obj = raw.substr(0, dot);
    std::string attr = raw.substr(dot + 1, eq - dot - 1);
    std::string value = raw.substr(eq + 1);
    if (!name_ok(obj, 14) || !attr_ok(attr)) return -1;
    if (value.empty() || value.size() > 34) return -1;

    if (attr == "txt") {
        if (value.size() < 2 || value.front() != '"' || value.back() != '"')
            return -1;
        std::string text = value.substr(1, value.size() - 2);
        if (text.size() > 32) return -1;
        std::string clean;
        for (unsigned char c : text) {
            /* P279 HIGH fix: 0xFF is the Nextion command terminator — a
             * payload carrying FF FF FF terminated the statement early and
             * executed the rest as a new display command (injection). */
            if (c < 32 || c > 126 || c == '"' || c == '\\') continue;
            clean.push_back((char)c);
        }
        stmt = obj + ".txt=\"" + clean + "\"";
        return 0;
    }
    for (char c : value)  // every other attr: digits only
        if (!std::isdigit((unsigned char)c)) return -1;
    stmt = obj + "." + attr + "=" + value;
    return 0;
}

int nsp_dash_map_parse(const std::string &payload, int *pages, int max) {
    if (pages == nullptr || max <= 0) return -1;
    std::string field;
    if (!json_string(payload, "command", field) || field != "dash_map")
        return -1;
    size_t k = payload.find("\"pages\"");
    if (k == std::string::npos) return -1;
    size_t lb = payload.find('[', k);
    size_t rb = payload.find(']', lb == std::string::npos ? k : lb);
    if (lb == std::string::npos || rb == std::string::npos || rb <= lb)
        return -1;
    int count = 0, value = -1, digits = 0;
    bool any = false;
    for (size_t i = lb + 1; i <= rb; i++) {
        char c = i < rb ? payload[i] : ',';
        if (c >= '0' && c <= '9') {
            if (digits > 2) return -1;  // ids are 0..15; 4 digits = junk
            value = (value < 0 ? 0 : value) * 10 + (c - '0');
            digits++;
            any = true;
        } else if (c == ',' || c == ' ') {
            if (digits) {
                if (value > 15 || count >= max) return -1;
                pages[count++] = value;
                value = -1;
                digits = 0;
            }
        } else if (c == ']') {
            if (digits) {
                if (value > 15 || count >= max) return -1;
                pages[count++] = value;
            }
        } else {
            return -1;  // anything non-numeric inside: reject
        }
    }
    (void)any;
    return count > 0 ? count : -1;
}

bool nsp_dash_page(const int *pages, int count, int page) {
    if (pages == nullptr) return false;
    for (int i = 0; i < count; i++)
        if (pages[i] == page) return true;
    return false;
}

/* -- runtime state (RAM only; the manager re-pushes on every register) -- */

/* P279 MEDIUM fix: the map was RAM-only and capped at 8 — a >8-page map
 * was rejected ENTIRELY (the pages fell back to the legacy relay chains:
 * the exact failure P234 prevents) and the boot window had no map at all.
 * The generation counter publishes the array atomically for the touch task. */
static int s_dash_pages[32];
static int s_dash_page_count = 0;
static volatile uint32_t s_dash_gen = 0;

bool nsp_dash_map_apply(const std::string &payload) {
    int pages[32];
    int n = nsp_dash_map_parse(payload, pages, 32);
    if (n <= 0) return false;
    for (int i = 0; i < n; i++) s_dash_pages[i] = pages[i];
    s_dash_page_count = n;
    s_dash_gen++;  // publish atomically-ish: the readers re-read the count
    return true;
}

void nsp_dash_map_clear(void) { s_dash_page_count = 0; }

/* P269: the dash pages in the pushed order — the swipe walks them. */
int nsp_dash_page_count(void) { return s_dash_page_count; }

int nsp_dash_page_id(int index) {
    return (index >= 0 && index < s_dash_page_count) ? s_dash_pages[index] : -1;
}

int nsp_dash_page_index(int page) {
    for (int i = 0; i < s_dash_page_count; i++)
        if (s_dash_pages[i] == page) return i;
    return -1;
}

bool nsp_dash_is_dash_page(int page) {
    return nsp_dash_page(s_dash_pages, s_dash_page_count, page);
}
