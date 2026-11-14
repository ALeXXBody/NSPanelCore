package command_test

import (
	"testing"

	"nspanelcore/command"
)

func TestParseRegister(t *testing.T) {
	c := command.ParseManager(`{"command":"register_request","mac_origin":"aa","friendly_name":"K"}`)
	if c.Kind != "register" || c.MAC != "aa" {
		t.Fatalf("%+v", c)
	}
}

func TestParseSet(t *testing.T) {
	c := command.ParseManager(`{"method":"set","attribute":"brightness","brightness":42,"entity_ids":[3,4]}`)
	if c.Kind != "set" || c.Attribute != "brightness" || c.Value != 42 || len(c.EntityIDs) != 2 {
		t.Fatalf("%+v", c)
	}
	if bad := command.ParseManager(`{"method":"set","attribute":"zoom","zoom":1}`); bad.Kind != "unknown" {
		t.Fatal("unknown attribute must be unknown")
	}
}

func TestParseScenes(t *testing.T) {
	if c := command.ParseManager(`{"command":"activate_scene","scene_id":7}`); c.Kind != "activate_scene" || c.SceneID != 7 {
		t.Fatalf("%+v", c)
	}
	if c := command.ParseManager(`not json`); c.Kind != "unknown" {
		t.Fatal("bad json must be unknown")
	}
}

// Regression: panel ints sometimes arrive as strings; Python int(x) parses
// them, the first Go port dropped them to 0 and black-holed the command.
func TestStringIntsParity(t *testing.T) {
	c := command.ParseManager(`{"method":"set","attribute":"brightness","brightness":"42","entity_ids":["3","x",4]}`)
	if c.Kind != "set" || c.Value != 42 {
		t.Fatalf("string value must parse: %+v", c)
	}
	if len(c.EntityIDs) != 3 || c.EntityIDs[0] != 3 || c.EntityIDs[1] != 0 || c.EntityIDs[2] != 4 {
		t.Fatalf("string entity_ids must parse (bad -> 0, skipped later): %+v", c.EntityIDs)
	}
}

func TestStompSend(t *testing.T) {
	known := func(s string) bool { return s == "KitchenPanel" }
	_, _, ok := command.StompSend("nspanel/Nope/command", "reboot", known)
	if ok {
		t.Fatal("unknown panel must not forward")
	}
	_, _, ok = command.StompSend("nspanel/x/other", "reboot", known)
	if ok {
		t.Fatal("bad dest must not forward")
	}
	topic, payload, ok := command.StompSend("nspanel/KitchenPanel/command", "reboot", known)
	if !ok || topic != "nspanel/KitchenPanel/command" || payload != `{"command":"reboot"}` {
		t.Fatalf("got %q %q", topic, payload)
	}
	topic, payload, ok = command.StompSend("nspanel/KitchenPanel/command", "gui_update", known)
	if !ok || payload != `{"command":"tft_update"}` {
		t.Fatalf("alias broken: %q", payload)
	}
}
