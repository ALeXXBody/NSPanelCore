/* P216: provisioning payload field extraction (pure, host-testable). */

#include "provision_parse.h"
#include <cstdlib>

bool nsp_provision_field(const std::string &body, const char *key, std::string &out) {
    std::string needle = std::string("\"") + key + "\"";
    size_t k = body.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = body.find(':', k + needle.size());
    if (colon == std::string::npos) return false;

    /* string value: "..." — json.dumps escapes inner quotes as \";
     * unescape them (a password may legitimately contain a quote).
     * Any other backslash escape is rejected: fail-safe. */
    size_t q1 = body.find('"', colon + 1);
    if (q1 != std::string::npos && q1 <= colon + 2) {
        std::string value;
        for (size_t i = q1 + 1; i < body.size(); i++) {
            char c = body[i];
            if (c == '\\' && i + 1 < body.size()) {
                char n = body[i + 1];
                /* P279 MEDIUM fix: a password with a BACKSLASH was
                 * silently dropped to an empty string (auth then failed
                 * with no visible cause). json.dumps escapes the standard
                 * set — unescape the common ones, reject the exotic. */
                if (n == '"') { value.push_back('"'); i++; continue; }
                if (n == '\\') { value.push_back('\\'); i++; continue; }
                if (n == 'n') { value.push_back('\n'); i++; continue; }
                if (n == 't') { value.push_back('\t'); i++; continue; }
                return false;  // the exotic escapes: reject
            }
            if (c == '"') {
                out = value;
                return true;
            }
            value.push_back(c);
        }
        return false;  // unterminated string
    }

    /* numeric value: bare digits (possibly signed) */
    size_t start = body.find_first_of("-0123456789", colon + 1);
    if (start == std::string::npos) return false;
    size_t end = body.find_first_not_of("-0123456789", start);
    if (end == std::string::npos) end = body.size();
    out = body.substr(start, end - start);
    return true;
}
