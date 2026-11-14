package entities_test

import (
	"testing"

	"nspanelcore/entities"
)

func iptr(n int) *int { return &n }

func TestIngestOnOff(t *testing.T) {
	l := entities.Light{CanDim: true, CanCT: true}
	if !entities.Ingest(&l, "on", entities.HAAttrs{Brightness: iptr(255), ColorMode: "color_temp", Kelvin: iptr(3000)}) {
		t.Fatal("first on must report changed")
	}
	if !l.State || l.Brightness != 100 || l.ColorTemp != 3000 {
		t.Fatalf("%+v", l)
	}
	if entities.Ingest(&l, "on", entities.HAAttrs{Brightness: iptr(255), ColorMode: "color_temp", Kelvin: iptr(3000)}) {
		t.Fatal("identical must not report changed")
	}
	if !entities.Ingest(&l, "off", entities.HAAttrs{}) || l.State {
		t.Fatal("off broken")
	}
}

func TestIngestNoDim(t *testing.T) {
	l := entities.Light{}
	entities.Ingest(&l, "on", entities.HAAttrs{})
	if l.Brightness != 100 {
		t.Fatal("non-dimmable must pin 100")
	}
}

func TestIngestHS(t *testing.T) {
	l := entities.Light{CanRGB: true}
	entities.Ingest(&l, "on", entities.HAAttrs{ColorMode: "hs", HSH: iptr(120), HSS: iptr(80)})
	if l.Mode != "rgb" || l.Hue != 120 || l.Saturation != 80 {
		t.Fatalf("%+v", l)
	}
}

func TestPublish(t *testing.T) {
	m := entities.Publish(entities.Light{State: true, Brightness: 50, ColorTemp: 1000}, 2700, 6500)
	if m["state_brightness_pct"] != "50" || m["state_kelvin"] != "2700" {
		t.Fatalf("%v", m)
	}
	m2 := entities.Publish(entities.Light{State: false, Brightness: 50}, 2700, 6500)
	if m2["state_brightness_pct"] != "0" {
		t.Fatal("off must publish 0 brightness")
	}
}

func TestRelay(t *testing.T) {
	seg, r := entities.ParseRelayTopic("nspanel/KitchenPanel/r1_state")
	if seg != "KitchenPanel" || r != 1 {
		t.Fatalf("got %q %d", seg, r)
	}
	if _, r := entities.ParseRelayTopic("nspanel/x/r3_state"); r != 0 {
		t.Fatal("r3 must not parse")
	}
	if !entities.ParseRelayPayload("ON") || entities.ParseRelayPayload("0") {
		t.Fatal("payload table broken")
	}
}
