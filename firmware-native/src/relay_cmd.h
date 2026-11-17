/* NSPanel Core — relay command payload parse (pure, host-testable).
 *
 * The v1 contract: relay cmd payloads are "1" / "0". Accepted exactly
 * (with surrounding whitespace tolerated); anything else → -1 (ignored —
 * a fail-safe against corrupt/foreign payloads driving the GPIOs).
 */

#pragma once
#include <string>

/* Returns 1, 0, or -1 (invalid). */
int nsp_relay_parse(const std::string &payload);
