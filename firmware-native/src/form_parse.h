/* NSPanel Core — form encoding parser (pure, host-testable).
 *
 * Extracted from the setup server so the parsing logic can be UNIT TESTED
 * on the host (R1: no untested code ships — the setup path is the one that
 * crashed the panel; the parser is its input layer).
 */

#pragma once
#include <string>
#include <map>

/* Parse an application/x-www-form-urlencoded body into key→value pairs.
 * Handles: '+'→space, %XX decoding, missing keys, repeated keys (last wins). */
void nsp_parse_form(const std::string &body, std::map<std::string, std::string> &out);
