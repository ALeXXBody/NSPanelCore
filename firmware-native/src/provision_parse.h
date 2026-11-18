/* P216: provisioning payload field extraction (pure, host-testable).
 * The /provision handler parses {"mqtt_server":"..","mqtt_port":N,...} —
 * this module holds that parsing so it can be unit tested (R1: the
 * provision endpoint shipped without tests once; never again). */

#pragma once
#include <string>

/* Extract "key":"value" (string) or "key":N (numeric) from a JSON body.
 * Returns true when the key exists and a value was captured. */
bool nsp_provision_field(const std::string &body, const char *key, std::string &out);
