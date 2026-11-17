/* NSPanel Core — NTC temperature math (pure, host-testable). */

#include "temp_math.h"
#include <cmath>

float nsp_ntc_temp(int raw) {
    if (raw <= 1 || raw >= 4095) return 0.0f;  // open circuit / rail: no reading
    float r = 10000.0f * raw / (4095.0f - raw);
    float t = 1.0f / (1.0f / 298.15f + logf(r / 10000.0f) / 3950.0f) - 273.15f;
    if (std::isnan(t) || std::isinf(t)) return 0.0f;
    return t;
}
