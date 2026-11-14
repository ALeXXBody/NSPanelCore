// Package fwupdate locks the firmware TFT-upload protocol rules in
// host-runnable form (the C++ itself only runs on ESP32):
// baud rotation order, neighbor hunting, 0x08 LE32 offset validation,
// chunk accounting. Mirrors NSPanel::_initTFTUpdate/_updateTFTOTA.
package fwupdate

// Rotation mirrors _next_baud: 115200 -> upload -> 9600 -> 115200.
// up is NSPMConfig tft_upload_baud.
func NextBaud(current, up int) int {
	if current == 9600 {
		return 115200
	}
	if current == up && up != 9600 {
		return 9600
	}
	if current == 115200 {
		if up != 115200 && up != 9600 {
			return up
		}
		return 9600
	}
	return 115200
}

// BlindPassBauds returns the talk baud for blind attempt n: attempt 0 uses
// the configured baud, then steps down for marginal links. Talk baud and
// the whmi-wris baud param must ALWAYS be equal — a hardcoded talk side
// with a different param deafens both sides (0.1.171 root-cause fix).
func BlindPassBauds(configured int, attempt int) int {
	if configured <= 0 {
		configured = 115200
	}
	switch {
	case attempt <= 0:
		return configured
	case attempt == 1:
		return 38400
	case attempt == 2:
		return 19200
	default:
		return 9600
	}
}

// BlindPasses mirrors the silent-small-file second pass at 9600.
// then 9600 (Nextion default after a corrupt flash) when the first pass
// heard nothing — capped to recovery-sized files (<=1MB): 16MB at 9600
// baud is ~4.5h and needs USB-TTL instead.
func BlindPasses(firstHeardAny bool, fileSize uint32) []int {
	if firstHeardAny {
		return []int{}
	}
	const maxRecovery = 1048576
	if fileSize <= maxRecovery {
		return []int{9600}
	}
	return []int{}
}

// PowerSettleMs mirrors _powerCycleDisplay: 3s off (drain caps) + 3s settle
// (Nextion cold-boot to bootloader). The old 1.2s settle shouted whmi-wris
// at a display that was still booting.
const PowerOffMs = 3000
const PowerSettleMs = 3000

// Neighbors mirrors _neighborBaud hunting (garbled reply = 2x off).
func Neighbors(baud int) (down, up int) {
	std := []int{9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600}
	for i, b := range std {
		if b != baud {
			continue
		}
		if i > 0 {
			down = std[i-1]
		}
		if i+1 < len(std) {
			up = std[i+1]
		}
		return down, up
	}
	return 0, 0
}

// DecodeOffset mirrors the 0x08 frame decode: first byte 0x08 + 4 LE bytes.
// Returns offset, ok. Offsets beyond fileSize must abort the attempt.
func DecodeOffset(frame []byte, fileSize uint32) (uint32, bool) {
	if len(frame) < 5 || frame[0] != 0x08 {
		return 0, false
	}
	off := uint32(frame[1]) | uint32(frame[2])<<8 | uint32(frame[3])<<16 | uint32(frame[4])<<24
	if off > fileSize {
		return 0, false
	}
	return off, true
}

// NextChunk mirrors the chunk-size accounting: 4096 except the tail.
func NextChunk(remaining uint32) int {
	if remaining > 4096 {
		return 4096
	}
	return int(remaining)
}
