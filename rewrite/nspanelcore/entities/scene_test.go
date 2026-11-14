package entities_test

import (
	"testing"

	"nspanelcore/entities"
)

func TestLegacyColorModeKeepsItsColor(t *testing.T) {
	// Regression: stored color_mode "color" (old exports/panels) fell
	// through the Python activator's "rgb" check — the light turned on
	// with NO color applied. The rewrite must not copy that fault.
	if entities.NormalizeColorMode("color") != "rgb" {
		t.Fatal("legacy color must map to rgb")
	}
	l := entities.Light{CanRGB: true}
	svc, data := entities.ApplyScene(&l, entities.SceneState{
		LightLevel: 60, ColorMode: "color", Hue: 200, Saturation: 70,
	}, 2700)
	if svc != "turn_on" {
		t.Fatalf("svc=%q", svc)
	}
	hs, _ := data["hs_color"].([]int)
	if l.Mode != "rgb" || len(hs) != 2 || hs[0] != 200 || hs[1] != 70 {
		t.Fatalf("color lost: %+v %v", l, data)
	}
}

func TestSceneOffAndDimmer(t *testing.T) {
	l := entities.Light{State: true}
	if svc, _ := entities.ApplyScene(&l, entities.SceneState{LightLevel: 0}, 2700); svc != "turn_off" || l.State {
		t.Fatal("level 0 must turn off")
	}
	l2 := entities.Light{CanCT: true, Mode: "rgb"}
	svc, data := entities.ApplyScene(&l2, entities.SceneState{
		LightLevel: 40, ColorMode: "dimmer", ColorTemperature: 3000,
	}, 2700)
	if svc != "turn_on" || data["brightness_pct"] != 40 || data["color_temp_kelvin"] != 3000 {
		t.Fatalf("%q %v", svc, data)
	}
	if l2.Mode != "default" {
		t.Fatal("dimmer must reset mode to default")
	}
}

func TestSceneUnknownModeBrightnessOnly(t *testing.T) {
	// Unknown modes fall through to brightness-only (Python parity, but
	// explicit and tested instead of accidental).
	l := entities.Light{CanRGB: true, CanCT: true}
	svc, data := entities.ApplyScene(&l, entities.SceneState{LightLevel: 50, ColorMode: "x"}, 2700)
	if svc != "turn_on" || len(data) != 1 || data["brightness_pct"] != 50 {
		t.Fatalf("%q %v", svc, data)
	}
}
