package manager_test

import (
	"testing"

	"nspanelcore/manager"
)

func TestCooldownGatesRetrigger(t *testing.T) {
	// First evaluation ever (no stamp) must run.
	if !manager.ShouldEvaluate("online", 0, 999999) {
		t.Fatal("first evaluation must run")
	}
	// 29 minutes after a trigger: blocked (mid-download reports arrive ~30s).
	if manager.ShouldEvaluate("online", 1000, 1000+29*60) {
		t.Fatal("cooldown must block re-trigger mid-flash window")
	}
	// Past 30 minutes: allowed again.
	if !manager.ShouldEvaluate("online", 1000, 1000+30*60) {
		t.Fatal("cooldown must expire at 30 minutes")
	}
}

func TestUpdatingStateNeverRetriggers(t *testing.T) {
	for _, s := range []string{"updating_tft", "updating_fw", "updating_fs"} {
		if manager.ShouldEvaluate(s, 0, 999999) {
			t.Fatalf("state %q is mid-flash: must never re-trigger", s)
		}
	}
}

func TestNormalizeReportAliases(t *testing.T) {
	// Firmware sends md5_data_file / md5_tft_gui; evaluator reads
	// md5_littlefs / md5_tft_file. Without this the data branch goes dead
	// on the register path while living on the status path.
	r := manager.NormalizeReport(map[string]string{
		"md5_data_file": "d1", "md5_tft_gui": "t1", "md5_firmware": "f1",
	})
	if r["md5_littlefs"] != "d1" || r["md5_tft_file"] != "t1" {
		t.Fatalf("aliases not applied: %v", r)
	}
	// Explicit evaluator names win over aliases.
	r2 := manager.NormalizeReport(map[string]string{
		"md5_littlefs": "explicit", "md5_data_file": "alias",
	})
	if r2["md5_littlefs"] != "explicit" {
		t.Fatal("explicit value must win")
	}
}
