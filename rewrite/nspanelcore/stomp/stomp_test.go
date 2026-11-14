package stomp_test

import (
	"testing"

	"nspanelcore/stomp"
)

func TestDecodeConnect(t *testing.T) {
	cmd, h, body := stomp.Decode("CONNECT\naccess_token:abc123\n\n\x00")
	if cmd != "CONNECT" || h["access_token"] != "abc123" || body != "" {
		t.Fatalf("got %q %+v %q", cmd, h, body)
	}
}

func TestFirstHeaderWins(t *testing.T) {
	_, h, _ := stomp.Decode("CONNECT\ndestination:a\ndestination:b\n\n\x00")
	if h["destination"] != "a" {
		t.Fatalf("first header must win: %+v", h)
	}
}

func TestContentLength(t *testing.T) {
	cmd, _, body := stomp.Decode("SEND\ncontent-length:3\ndestination:x\n\nabcDEF\x00")
	if cmd != "SEND" || body != "abc" {
		t.Fatalf("got %q %q", cmd, body)
	}
}

func TestRoundTrip(t *testing.T) {
	enc := stomp.Encode("MESSAGE", map[string]string{"destination": "a/b"}, "hi")
	cmd, h, body := stomp.Decode(enc)
	if cmd != "MESSAGE" || h["destination"] != "a/b" || body != "hi" {
		t.Fatalf("round-trip broken: %q %+v %q", cmd, h, body)
	}
}

func TestGate(t *testing.T) {
	if stomp.Gate("CONNECT", false) != "" {
		t.Fatal("CONNECT must always pass (handshake carries token)")
	}
	if stomp.Gate("SUBSCRIBE", false) == "" || stomp.Gate("SEND", false) == "" {
		t.Fatal("SUBSCRIBE/SEND must require auth (v1.3.41 gate)")
	}
	if stomp.Gate("SEND", true) != "" {
		t.Fatal("authed SEND must pass")
	}
}
