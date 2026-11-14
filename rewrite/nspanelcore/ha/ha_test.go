package ha_test

import (
	"encoding/json"
	"testing"

	"nspanelcore/ha"
)

func TestBrightnessConvert(t *testing.T) {
	if ha.BrightnessToPct(255) != 100 || ha.BrightnessToPct(0) != 0 {
		t.Fatal("to pct broken")
	}
	if ha.PctToBrightness(100) != 255 || ha.PctToBrightness(0) != 0 {
		t.Fatal("to bri broken")
	}
	if ha.ClampKelvin(1000, 2700, 6500) != 2700 || ha.ClampKelvin(9000, 2700, 6500) != 6500 {
		t.Fatal("clamp broken")
	}
}

func TestTurnOnPayload(t *testing.T) {
	d := ha.TurnOnPayload("light.kitchen", ha.LightCommand{HasBrightness: true, Brightness: 100}, 2700, 6500)
	if d["brightness"] != 255 {
		t.Fatalf("bri: %v", d)
	}
	d2 := ha.TurnOnPayload("light.k", ha.LightCommand{HasColorTemperature: true, ColorTemperature: 1000}, 2700, 6500)
	if d2["kelvin"] != 2700 {
		t.Fatalf("kelvin clamp: %v", d2)
	}
	d3 := ha.TurnOnPayload("light.k", ha.LightCommand{HasHue: true, Hue: 120, HasSaturation: true, Saturation: 80}, 2700, 6500)
	hs, _ := d3["hs_color"].([]int)
	if len(hs) != 2 || hs[0] != 120 || hs[1] != 80 {
		t.Fatalf("hs: %v", d3)
	}
}

func TestWSBuilders(t *testing.T) {
	var m map[string]any
	json.Unmarshal([]byte(ha.AuthMsg("tok")), &m)
	if m["type"] != "auth" {
		t.Fatal("auth broken")
	}
	json.Unmarshal([]byte(ha.CallService(1, "light", "turn_on", map[string]any{"entity_id": "light.k"})), &m)
	if m["domain"] != "light" {
		t.Fatal("call_service broken")
	}
}

func TestApplyLightCommandMirrorsPython(t *testing.T) {
	// Regression: the first Go port built brightness (0-255) + kelvin, but
	// _apply_light_command sends brightness_pct (0-100) + color_temp_kelvin.
	// Brightness 0 must flip to turn_off with empty data.
	l := ha.Light{CanDim: true, CanCT: true}
	svc, data := ha.ApplyLightCommand(&l, &ha.LightCommand{HasBrightness: true, Brightness: 0}, nil, 2700)
	if svc != "turn_off" || len(data) != 0 {
		t.Fatalf("zero-brightness must turn off: %q %v", svc, data)
	}
	if l.State {
		t.Fatal("state must follow brightness>0")
	}
	// Brightness 42 + kelvin: service keys must be the HA names.
	l2 := ha.Light{CanDim: true, CanCT: true, Mode: "default"}
	svc, data = ha.ApplyLightCommand(&l2, &ha.LightCommand{
		HasBrightness: true, Brightness: 42,
		HasColorTemperature: true, ColorTemperature: 3200,
	}, nil, 2700)
	if svc != "turn_on" {
		t.Fatalf("svc=%q", svc)
	}
	if data["brightness_pct"] != 42 || data["color_temp_kelvin"] != 3200 {
		t.Fatalf("service keys wrong: %v", data)
	}
	// Clamp: brightness >100 pins to 100.
	l3 := ha.Light{CanDim: true}
	ha.ApplyLightCommand(&l3, &ha.LightCommand{HasBrightness: true, Brightness: 999}, nil, 2700)
	if l3.Brightness != 100 || !l3.State {
		t.Fatalf("%+v", l3)
	}
	// Partial hue only: Python zeroes the missing side and flips to rgb.
	l4 := ha.Light{CanRGB: true, State: true, Mode: "default"}
	svc, data = ha.ApplyLightCommand(&l4, &ha.LightCommand{HasHue: true, Hue: 120}, nil, 2700)
	if l4.Mode != "rgb" || l4.Saturation != 0 {
		t.Fatalf("%+v", l4)
	}
	hs, _ := data["hs_color"].([]int)
	if svc != "turn_on" || len(hs) != 2 || hs[0] != 120 || hs[1] != 0 {
		t.Fatalf("hs zero-fill broken: %q %v", svc, data)
	}
	// Toggle override wins over everything.
	l5 := ha.Light{State: true}
	b := false
	if svc, _ := ha.ApplyLightCommand(&l5, nil, &b, 2700); svc != "turn_off" || l5.State {
		t.Fatal("toggle-off broken")
	}
}
