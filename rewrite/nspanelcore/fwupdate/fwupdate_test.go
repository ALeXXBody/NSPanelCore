package fwupdate_test

import (
	"testing"

	"nspanelcore/fwupdate"
)

func TestOffsetDecode(t *testing.T) {
	off, ok := fwupdate.DecodeOffset([]byte{0x08, 0x00, 0x10, 0x00, 0x00}, 1<<20)
	if !ok || off != 0x1000 {
		t.Fatalf("got %d %v", off, ok)
	}
	// Offset 0 decodes fine here; the jump DECISION lives in ShouldJump,
	// which ignores it (keep streaming forward, never rewind to zero).
	if _, ok := fwupdate.DecodeOffset([]byte{0x08, 0, 0, 0, 0}, 100); !ok {
		t.Fatal("offset 0 must decode (jump decision is ShouldJump's job)")
	}
	// Beyond file size aborts.
	if _, ok := fwupdate.DecodeOffset([]byte{0x08, 0xFF, 0xFF, 0xFF, 0xFF}, 100); ok {
		t.Fatal("beyond-size offset must abort")
	}
	// Short frame aborts (no blocking forever).
	if _, ok := fwupdate.DecodeOffset([]byte{0x08, 0x01}, 100); ok {
		t.Fatal("short frame must abort")
	}
}

func TestChunk(t *testing.T) {
	if fwupdate.NextChunk(9000) != 4096 || fwupdate.NextChunk(100) != 100 {
		t.Fatal("chunk accounting broken")
	}
}

func TestWindowAndJumpRules(t *testing.T) {
	if fwupdate.ResponseWindowMs != 5000 {
		t.Fatal("response window must be 5000ms (upstream-proven)")
	}
	if !fwupdate.ShouldJump(0x1000, 1<<20) {
		t.Fatal("in-range offset must jump")
	}
	if fwupdate.ShouldJump(0, 100) {
		t.Fatal("offset 0 must be IGNORED (keep streaming forward)")
	}
	if fwupdate.ShouldJump(1<<21, 1<<20) {
		t.Fatal("beyond-size offset must not jump")
	}
}

func TestSingleBaudRule(t *testing.T) {
	// One configured baud drives handshake, whmi param and streaming.
	// Talk==param by construction — the 0.1.171 divergence class cannot exist.
	if fwupdate.SingleBaud(921600) != 921600 {
		t.Fatal("configured baud must pass through")
	}
	if fwupdate.SingleBaud(0) != 115200 {
		t.Fatal("unset baud must fall back to 115200")
	}
}
