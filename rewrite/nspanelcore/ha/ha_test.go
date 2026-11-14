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
