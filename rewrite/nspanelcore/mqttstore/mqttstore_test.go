package mqttstore_test

import (
	"testing"

	"nspanelcore/mqttstore"
)

func TestMatch(t *testing.T) {
	cases := []struct{ filter, topic string; want bool }{
		{"nspanel/+/status", "nspanel/KitchenPanel/status", true},
		{"nspanel/+/status", "nspanel/a/b/status", false},
		{"nspanel/#", "nspanel/a/b/c", true},
		{"#", "anything/at/all", true},
		{"nspanel/+/command", "nspanel/KitchenPanel/command", true},
		{"nspanel/+/command", "nspanel/KitchenPanel/other", false},
		{"a/b", "a/b/c", false},
		{"a/b/c", "a/b", false},
	}
	for _, c := range cases {
		if got := mqttstore.Match(c.filter, c.topic); got != c.want {
			t.Fatalf("Match(%q,%q) = %v, want %v", c.filter, c.topic, got, c.want)
		}
	}
}

func TestRetainedReplay(t *testing.T) {
	s := mqttstore.New()
	s.Set("nspanel/KitchenPanel/status", `{"temp":21}`)
	s.Set("nspanel/DressingRoom/status", `{"temp":19}`)
	got := s.Replay("nspanel/+/status")
	if len(got) != 2 {
		t.Fatalf("replay got %d", len(got))
	}
	// Empty payload deletes (MQTT retained-delete).
	s.Set("nspanel/KitchenPanel/status", "")
	if s.Len() != 1 {
		t.Fatal("delete broken")
	}
	if _, ok := s.Get("nspanel/KitchenPanel/status"); ok {
		t.Fatal("deleted value must be gone")
	}
}
