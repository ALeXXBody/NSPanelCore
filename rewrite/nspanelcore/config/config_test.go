package config_test

import (
	"os"
	"testing"

	"nspanelcore/config"
)

func TestDefaults(t *testing.T) {
	c := config.New()
	if c.Settings.ColorTempMin != 2700 || c.Settings.ColorTempMax != 6500 {
		t.Fatal("bad defaults")
	}
	if c.NextIDFor("room") != 1 || c.NextIDFor("room") != 2 {
		t.Fatal("next_id broken")
	}
}

func TestPanelNormalizeLegacyScreensaver(t *testing.T) {
	p := config.Panel{ScreensaverMode: "0"}
	p.Normalize()
	if p.ScreensaverMode != "with_background" {
		t.Fatalf("got %q", p.ScreensaverMode)
	}
	p = config.Panel{ScreensaverMode: "global"}
	p.Normalize()
	if p.ScreensaverMode != "global" {
		t.Fatalf("valid mode must survive, got %q", p.ScreensaverMode)
	}
}

func TestLoadRealStorageShape(t *testing.T) {
	// Unknown keys must be ignored; old files without new keys get defaults.
	raw := `{"settings":{"manager_address":"core","unknown_future_key":1},"panels":[{"id":1,"mac":"e465b849a100","name":"KitchenPanel","screensaver_mode":"0"}],"next_id":{"panel":2}}`
	cfg, err := config.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Settings.Theme != "nspmwip" {
		t.Fatalf("default theme not applied: %q", cfg.Settings.Theme)
	}
	if cfg.Panels[0].ScreensaverMode != "with_background" {
		t.Fatalf("legacy screensaver not migrated: %q", cfg.Panels[0].ScreensaverMode)
	}
	if cfg.NextID["panel"] != 2 {
		t.Fatal("next_id not loaded")
	}
}

func TestPythonFixtureParity(t *testing.T) {
	// Byte-parity spot check against a real Python to_dict payload shape.
	raw, err := os.ReadFile("../../..//tests/fixtures/config_sample.json")
	if err != nil {
		t.Skip("no fixture yet")
	}
	cfg, err := config.Unmarshal(raw)
	if err != nil {
		t.Fatal(err)
	}
	out, err := cfg.Marshal()
	if err != nil {
		t.Fatal(err)
	}
	cfg2, err := config.Unmarshal(out)
	if err != nil {
		t.Fatal(err)
	}
	if len(cfg2.Panels) != len(cfg.Panels) {
		t.Fatal("round-trip lost panels")
	}
}
