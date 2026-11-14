package fwupdate_test

import (
	"testing"

	"nspanelcore/fwupdate"
)

func TestRotationCovers9600Default(t *testing.T) {
	// A corrupt flash resets the display baud to the Nextion default 9600:
	// rotation must visit it. Upstream bug history: pre-0.1.164 never tried it.
	seen := map[int]bool{}
	b := 115200
	for i := 0; i < 4; i++ {
		seen[b] = true
		b = fwupdate.NextBaud(b, 921600)
	}
	if !seen[115200] || !seen[921600] || !seen[9600] {
		t.Fatalf("rotation must cover 115200/upload/9600: %v", seen)
	}
}

func TestNeighbors(t *testing.T) {
	down, up := fwupdate.Neighbors(115200)
	if down != 57600 || up != 230400 {
		t.Fatalf("got %d/%d", down, up)
	}
	if d, u := fwupdate.Neighbors(999); d != 0 || u != 0 {
		t.Fatal("unknown baud must yield no neighbors")
	}
}

func TestOffsetDecode(t *testing.T) {
	off, ok := fwupdate.DecodeOffset([]byte{0x08, 0x00, 0x10, 0x00, 0x00}, 1<<20)
	if !ok || off != 0x1000 {
		t.Fatalf("got %d %v", off, ok)
	}
	// Offset 0 is a legitimate start-over, not an abort.
	if _, ok := fwupdate.DecodeOffset([]byte{0x08, 0, 0, 0, 0}, 100); !ok {
		t.Fatal("offset 0 must be accepted")
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
