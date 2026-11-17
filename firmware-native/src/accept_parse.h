/* NSPanel Core — register_accept payload parser (pure, host-testable).
 *
 * Extracted from the MQTT command handler (R1: this code drives the
 * manager-address adoption — the OTA chain's first link — so it must be
 * unit tested, not trusted).
 */

#pragma once
#include <string>

/* Parse {"command":"register_accept","address":"A.B.C.D","port":N,...}
 * Returns true and fills addr/port when the payload is a well-formed
 * accept with a non-empty address. Tolerates surrounding whitespace and
 * arbitrary key order. */
bool nsp_parse_register_accept(const std::string &payload,
                               std::string &addr, int &port);
