// Package fwupdate locks the firmware TFT-upload protocol rules in
// host-runnable form (the C++ itself only runs on ESP32): fixed-115200
// comms/handshake + one configured upload baud, 0x08 LE32 offset
// validation, chunk accounting. Mirrors
// NSPanel::_initTFTUpdate/_updateTFTOTA.
package fwupdate

// CommBaud mirrors init/handshake: normal communication ALWAYS runs at the
// fixed 115200 (the HMI default). The display only switches baud when it
// accepts whmi-wris — opening anywhere else is shouting into the void.
func CommBaud() uint32 { return 115200 }

// UploadBaud mirrors _tftBaud(): the ONE configured baud, used for the
// whmi-wris param and the bulk stream after the display accepts it.
// Falls back to 115200 when unset.
func UploadBaud(configured uint32) uint32 {
	if configured == 0 {
		return 115200
	}
	return configured
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

// ResponseWindowMs mirrors the per-block response window: upstream waits
// 5000ms after each 4KB block. A 500ms window misses late 0x08 retransmit
// requests and permanently diverges the v1.2 stream (display-brick bug).
const ResponseWindowMs = 5000

// ShouldJump mirrors the 0x08 handling: jump only for offsets in range,
// IGNORE offset 0 (keep streaming forward), never abort.
func ShouldJump(offset, fileSize uint32) bool {
	return offset > 0 && offset <= fileSize
}
