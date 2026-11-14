// Package parity locks Go↔Python behavioral equivalence at the logic level.
//
// Each vector is a (input → expected) pair copied from the Python
// implementation's observed behavior. If a future change breaks parity with
// the panels' firmware contract, these tests fail first. This is the
// traffic-diff gate in unit-test form; the live broker diff runs in CI
// once main gains its transports.
package parity_test

import (
	"testing"

	"nspanelcore/command"
	"nspanelcore/entities"
	"nspanelcore/ha"
	"nspanelcore/manager"
	"nspanelcore/mqttstore"
	"nspanelcore/ota"
	"nspanelcore/stomp"
	"nspanelcore/topics"
	"nspanelcore/weather"
)

func TestTopicParity(t *testing.T) {
	// Python: panel_mqtt_topic("KitchenPanel","command") == "nspanel/KitchenPanel/command"
	if topics.PanelTopic("KitchenPanel", "command") != "nspanel/KitchenPanel/command" {
		t.Fatal("panel topic parity broken")
	}
	// Python: topic_safe("E4:65:B8:49:A1:00") == "e465b849a100"
	if topics.Safe("E4:65:B8:49:A1:00") != "e465b849a100" {
		t.Fatal("topic_safe parity broken")
	}
	// Python: panel_mqtt_base("My Panel") == "My Panel" (verbatim)
	if topics.PanelBase("My Panel") != "My Panel" {
		t.Fatal("hostname verbatim parity broken")
	}
}

func TestOTANeverAutoDataParity(t *testing.T) {
	// Python: data_file updates are NEVER auto-triggered (would wipe WiFi).
	d := manager.DecideOTA(manager.OTARequest{
		CachedDataMD5: "d1", ReportLittlefsMD5: "d2",
		AutoTFTUpdates: true,
	})
	if d.DataAvailable != true {
		t.Fatal("data-available flag parity broken")
	}
	// No Firmware/TFT fields exist for data: nothing to auto-fire.
	if d.Firmware || d.TFT {
		t.Fatal("unrelated triggers must stay off")
	}
}

func TestVersionParity(t *testing.T) {
	// Python: _version_tuple zero-pads ("1.0" == "1.0.0", not newer).
	if ota.IsNewer("1.0", "1.0.0") {
		t.Fatal("version zero-pad parity broken")
	}
	if !ota.IsNewer("1.3.43", "1.3.42") {
		t.Fatal("patch ordering parity broken")
	}
}

func TestLightIngestParity(t *testing.T) {
	// Python: brightness 255 -> 100; off publishes 0 brightness.
	l := entities.Light{CanDim: true, CanCT: true}
	bri := 255
	entities.Ingest(&l, "on", entities.HAAttrs{Brightness: &bri, ColorMode: "color_temp", Kelvin: &[]int{3000}[0]})
	m := entities.Publish(l, 2700, 6500)
	if m["state_brightness_pct"] != "100" || m["state_kelvin"] != "3000" {
		t.Fatalf("light parity broken: %v", m)
	}
}

func TestCommandParity(t *testing.T) {
	c := command.ParseManager(`{"method":"set","attribute":"kelvin","kelvin":3200,"entity_ids":[5]}`)
	if c.Kind != "set" || c.Value != 3200 {
		t.Fatal("set parse parity broken")
	}
	known := func(s string) bool { return s == "KitchenPanel" }
	_, payload, ok := command.StompSend("nspanel/KitchenPanel/command", "gui_update", known)
	if !ok || payload != `{"command":"tft_update"}` {
		t.Fatal("stomp alias parity broken")
	}
}

func TestSTOMPGateParity(t *testing.T) {
	// Python v1.3.41: SUBSCRIBE/SEND before authed CONNECT get ERROR.
	if stomp.Gate("SUBSCRIBE", false) == "" {
		t.Fatal("auth gate parity broken")
	}
}

func TestMQTTMatchParity(t *testing.T) {
	// Python subscribes nspanel/+/status: must match panels, not deeper.
	if !mqttstore.Match("nspanel/+/status", "nspanel/KitchenPanel/status") {
		t.Fatal("wildcard parity broken")
	}
	if mqttstore.Match("nspanel/+/status", "nspanel/a/b/status") {
		t.Fatal("single-level + must not span levels")
	}
}

func TestWeatherParity(t *testing.T) {
	if weather.Icon(0) != "sunny" || weather.FmtTemp(21.4, false) != "21°C" {
		t.Fatal("weather parity broken")
	}
	if ha.PctToBrightness(100) != 255 || ha.BrightnessToPct(255) != 100 {
		t.Fatal("brightness map parity broken")
	}
}
