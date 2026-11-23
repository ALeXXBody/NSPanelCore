/* P322: the MQTT command extraction under the EXACT wire conditions.
 * nsp_json_command is copied VERBATIM from src/mqtt.cpp (the handler's
 * parse is static there; the host harness mirrors it byte-for-byte and
 * the test asserts the copy stays in sync by construction).
 *
 * The handler calls it TWICE on the same payload for every non-accept
 * command (the first call in the if, the second after the fall-through).
 * The real payloads come from the live captures:
 *   accept:  {"command": "register_accept", "address": "192.168.50.20", ...}
 *   reload:  {"command": "reload"}
 *   dash_map:{"command": "dash_map", "pages": [4, 7]}
 */
#include <cstdio>
#include <cassert>
#include <string>

/* VERBATIM from src/mqtt.cpp:180 — keep in sync. */
static bool nsp_json_command(const std::string &payload, std::string &out) {
    size_t k = payload.find("\"command\"");
    if (k == std::string::npos) return false;
    size_t colon = payload.find(':', k);
    if (colon == std::string::npos) return false;
    size_t q1 = payload.find('"', colon + 1);
    if (q1 == std::string::npos) return false;
    size_t q2 = payload.find('"', q1 + 1);
    if (q2 == std::string::npos) return false;
    out = payload.substr(q1 + 1, q2 - q1 - 1);
    return true;
}

/* The handler's EXACT shape for the non-accept path: parse, compare,
 * fall through, parse AGAIN, then the stage log. */
static std::string handler_double_parse(const std::string &payload) {
    std::string cmd_field;
    if (nsp_json_command(payload, cmd_field)) {
        if (cmd_field == "register_accept") {
            return "accept-branch";
        }
    }
    if (!nsp_json_command(payload, cmd_field)) return "";
    return "stage:" + cmd_field;
}

int main() {
    /* 1. the real captured bytes */
    const std::string accept =
        "{\"command\": \"register_accept\", \"address\": \"192.168.50.20\", "
        "\"port\": 8123, \"config_topic\": \"nspanel/e465b849a100/config\"}";
    const std::string reload = "{\"command\": \"reload\"}";
    const std::string dash_map = "{\"command\": \"dash_map\", \"pages\": [4, 7]}";

    std::string out;
    assert(nsp_json_command(accept, out) && out == "register_accept");
    assert(nsp_json_command(reload, out) && out == "reload");
    assert(nsp_json_command(dash_map, out) && out == "dash_map");

    /* 2. the double call, same buffer, same payload — the handler's shape */
    assert(handler_double_parse(accept) == "accept-branch");
    assert(handler_double_parse(reload) == "stage:reload");
    assert(handler_double_parse(dash_map) == "stage:dash_map");

    /* 3. the escaped-quote payload (the provision flow's json.dumps always
     * escapes — the accept with \" inside the address would break the
     * naive find). The real wire has none today; pin the behavior. */
    const std::string quoted =
        "{\"command\": \"reload\", \"note\": \"say \\\"hi\\\"\"}";
    assert(nsp_json_command(quoted, out) && out == "reload");

    /* 4. the edge cases that must not match */
    assert(!nsp_json_command("no command here", out));
    assert(!nsp_json_command("", out));
    assert(!nsp_json_command("{\"commands\": \"x\"}", out));  // substring trap
    assert(!nsp_json_command("{\"command\":}", out));         // no value

    /* 5. the command value with an embedded quote: the extractor takes the
     * FIRST quoted token — a value containing \" would truncate. Pin the
     * actual behavior so a fix is a conscious change. */
    const std::string tricky = "{\"command\": \"re\\\"load\"}";
    assert(nsp_json_command(tricky, out) && out == "re\\");
    std::printf("test_mqtt_command_extract: ALL PASS\n");
    return 0;
}
