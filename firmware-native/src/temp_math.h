/* NSPanel Core — NTC temperature math (pure, host-testable).
 *
 * 10k NTC (B=3950) divider: raw ADC (12-bit) → °C.
 * raw <= 1 (open/float) → 0.0 (the "no reading" value the wire carries).
 */

#pragma once

float nsp_ntc_temp(int raw);
