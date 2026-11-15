package topics_test

import (
	"testing"

	"nspanelcore/topics"
)

func TestBaseVerbatimHostname(t *testing.T) {
	if got := topics.Base("DemoPanel"); got != "nspanel/DemoPanel" {
		t.Fatalf("Base = %q", got)
	}
	// Case and spaces are preserved: the firmware subscribes verbatim.
	if got := topics.Base("My Panel"); got != "nspanel/My Panel" {
		t.Fatalf("Base = %q", got)
	}
}

func TestBaseSanitizesStructureOnly(t *testing.T) {
	if got := topics.Base("a/b#c+d"); got != "nspanel/a_b_c_d" {
		t.Fatalf("Base = %q", got)
	}
	if got := topics.Base(""); got != "nspanel/panel" {
		t.Fatalf("Base = %q", got)
	}
	// Verbatim: double spaces are preserved (firmware subscribes verbatim).
	if got := topics.PanelBase("A  B"); got != "A  B" {
		t.Fatalf("PanelBase = %q", got)
	}
	// Only structural chars are replaced; case kept.
	if got := topics.PanelBase("My Panel"); got != "My Panel" {
		t.Fatalf("PanelBase = %q", got)
	}
}

func TestTopicCommand(t *testing.T) {
	if got := topics.Topic("DemoPanel", "command"); got != "nspanel/DemoPanel/command" {
		t.Fatalf("Topic = %q", got)
	}
	if got := topics.Topic("DemoPanel", "r1_state"); got != "nspanel/DemoPanel/r1_state" {
		t.Fatalf("Topic = %q", got)
	}
}

func TestSegmentVerbatim(t *testing.T) {
	if got := topics.Segment("nspanel/Demo Panel/status"); got != "Demo Panel" {
		t.Fatalf("Segment = %q", got)
	}
	if got := topics.Segment("nspanel/aa/r1_state"); got != "aa" {
		t.Fatalf("Segment = %q", got)
	}
	if got := topics.Segment("other/x/y"); got != "" {
		t.Fatalf("Segment = %q", got)
	}
	if got := topics.Segment("nspanel"); got != "" {
		t.Fatalf("Segment = %q", got)
	}
}

func TestSafeTopic(t *testing.T) {
	cases := map[string]string{
		"AA:BB:CC:DD:EE:FF": "aabbccddeeff",
		"Demo Panel":     "demo_panel",
		"My-Panel 2":        "mypanel_2",
		"  __Hi__  ":        "hi",
	}
	for in, want := range cases {
		if got := topics.SafeTopic(in); got != want {
			t.Fatalf("SafeTopic(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestWhitespaceOnlyYieldsPanel(t *testing.T) {
	// Python: panel_mqtt_base("   ") strips to "" -> "panel".
	if got := topics.PanelBase("   "); got != "panel" {
		t.Fatalf("got %q", got)
	}
	if got := topics.Base("   "); got != "nspanel/panel" {
		t.Fatalf("got %q", got)
	}
}
