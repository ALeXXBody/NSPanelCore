/* P216: provisioning payload field extraction (pure, host-testable). */

#include "provision_parse.h"
#include <cstdlib>

bool nsp_provision_field(const std::string &body, const char *key, std::string &out) {
    std::string needle = std::string("\"") + key + "\"";
    size_t k = body.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = body.find(':', k + needle.size());
    if (colon == std::string::npos) return false;

    /* string value: "..." */
    size_t q1 = body.find('"', colon + 1);
    if (q1 != std::string::npos && q1 <= colon + 2) {
        size_t q2 = body.find('"', q1 + 1);
        if (q2 == std::string::npos) return false;
        out = body.substr(q1 + 1, q2 - q1 - 1);
        return true;
    }

    /* numeric value: bare digits (possibly signed) */
    size_t start = body.find_first_of("-0123456789", colon + 1);
    if (start == std::string::npos) return false;
    size_t end = body.find_first_not_of("-0123456789", start);
    if (end == std::string::npos) end = body.size();
    out = body.substr(start, end - start);
    return true;
}
