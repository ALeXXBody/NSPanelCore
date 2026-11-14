package manager_test

import (
	"testing"

	"nspanelcore/manager"
)

func panels() []manager.Panel {
	return []manager.Panel{
		{ID: 1, MAC: "e465b849a100", Name: "KitchenPanel", WifiHostname: "KitchenPanel", Model: "sonoff"},
		{ID: 2, MAC: "b0cbd8993754", Name: "Dressing Room", WifiHostname: "DressingRoom", Model: "custom"},
	}
}

func TestCommandTopicUsesHostname(t *testing.T) {
	p := manager.Panel{Name: "My Display Name", WifiHostname: "KitchenPanel"}
	if got := manager.CommandTopic(p, "command"); got != "nspanel/KitchenPanel/command" {
		t.Fatalf("got %q", got)
	}
	// Rename must not black-hole commands: falls back to name only when no hostname.
	p2 := manager.Panel{Name: "New Name"}
	if got := manager.CommandTopic(p2, "command"); got != "nspanel/New Name/command" {
		t.Fatalf("got %q", got)
	}
}

func TestFindByTopicVerbatimFirst(t *testing.T) {
	ps := panels()
	got, drift, found := manager.FindByTopic(ps, "KitchenPanel")
	if !found || got.ID != 1 || drift {
		t.Fatalf("verbatim hostname must win without drift: %+v %v", got, drift)
	}
	// Case mismatch falls to normalized with drift warning.
	got, drift, found = manager.FindByTopic(ps, "kitchenpanel")
	if !found || got.ID != 1 || !drift {
		t.Fatalf("normalized match must flag drift: %+v %v", got, drift)
	}
	// Unknown segment finds nothing.
	_, _, found = manager.FindByTopic(ps, "Nope")
	if found {
		t.Fatal("unknown must not match")
	}
}

func TestNoteHostnameHeals(t *testing.T) {
	p := manager.Panel{Name: "KitchenPanel", WifiHostname: "Old"}
	if !manager.NoteHostname(&p, "KitchenPanel") {
		t.Fatal("should report change")
	}
	if p.WifiHostname != "KitchenPanel" {
		t.Fatal("not updated")
	}
	if manager.NoteHostname(&p, "KitchenPanel") {
		t.Fatal("same segment must not report change")
	}
}

func TestDecideOTANeverAutoData(t *testing.T) {
	d := manager.DecideOTA(manager.OTARequest{
		CachedFirmwareMD5: "fw1", ReportFirmwareMD5: "fw2",
		CachedDataMD5: "d1", ReportLittlefsMD5: "d2",
		CachedTFTMD5: "t1", ReportTFTMD5: "t2",
		AutoTFTUpdates: true,
	})
	if !d.Firmware || !d.TFT {
		t.Fatalf("fw+tft must trigger: %+v", d)
	}
	if !d.DataAvailable {
		t.Fatal("data must be reported available")
	}
	// auto_tft off gates TFT only.
	d2 := manager.DecideOTA(manager.OTARequest{
		CachedTFTMD5: "t1", ReportTFTMD5: "t2",
		AutoTFTUpdates: false,
	})
	if d2.TFT {
		t.Fatal("TFT must not trigger when auto disabled")
	}
	// Empty cache never triggers (unknown).
	d3 := manager.DecideOTA(manager.OTARequest{ReportFirmwareMD5: "x"})
	if d3.Firmware || d3.TFT {
		t.Fatal("empty cache must never trigger")
	}
}

func TestModelAndTFTFilename(t *testing.T) {
	if manager.ModelKey("weird") != "sonoff" {
		t.Fatal("model fallback broken")
	}
	if manager.TFTFilename(true) != "gui_us.tft" || manager.TFTFilename(false) != "gui.tft" {
		t.Fatal("tft filename broken")
	}
}

func TestRelayKeyNormalized(t *testing.T) {
	k, r := manager.RelayKey("E4:65:B8:49:A1:00", 1)
	if k != "e465b849a100" || r != 1 {
		t.Fatalf("got %q %d", k, r)
	}
}
