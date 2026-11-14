// OTA trigger gating: cooldown + in-flight guard + report normalization.
//
// This is a FIX port of _maybe_trigger_firmware_ota_cooled +
// _normalize_ota_report. The first Go port had DecideOTA but no gating at
// all: evaluated on every ~30s status report with no cooldown, it would
// re-trigger a panel mid-download and corrupt the flash. The rules:
//
//   - Panels already reporting updating_tft/updating_fw/updating_fs are
//     mid-flash: never re-trigger.
//   - One evaluation per panel per 30 minutes (cooldown), stamped AFTER the
//     evaluation attempt so a startup-window pass (cache not ready) does not
//     black out the next real chance.
//   - Register payloads use md5_data_file / md5_tft_gui; the evaluator uses
//     md5_littlefs / md5_tft_file. Normalize once so neither path goes dead.
package manager

// Cooldown between OTA evaluations per panel.
const OTACooldownSeconds = 1800

// UpdatingStates are panel states that mean a flash is in flight.
var UpdatingStates = map[string]bool{
	"updating_tft": true,
	"updating_fw":  true,
	"updating_fs":  true,
}

// NormalizeReport mirrors _normalize_ota_report: alias register-payload
// keys to the evaluator's names without overwriting explicit values.
func NormalizeReport(report map[string]string) map[string]string {
	out := map[string]string{}
	for k, v := range report {
		out[k] = v
	}
	if _, ok := out["md5_littlefs"]; !ok {
		if v, ok := out["md5_data_file"]; ok {
			out["md5_littlefs"] = v
		}
	}
	if _, ok := out["md5_tft_file"]; !ok {
		if v, ok := out["md5_tft_gui"]; ok {
			out["md5_tft_file"] = v
		}
	}
	return out
}

// ShouldEvaluate mirrors the cooled wrapper's gates (not the publish —
// that stays in DecideOTA + main). Returns true when the evaluator may run.
func ShouldEvaluate(panelState string, lastTriggerMonotonic, nowMonotonic float64) bool {
	if UpdatingStates[panelState] {
		return false
	}
	return nowMonotonic-lastTriggerMonotonic >= OTACooldownSeconds
}
