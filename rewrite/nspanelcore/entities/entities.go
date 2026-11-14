// Package entities ports the light ingest + publish paths from manager.py
// (_ingest_light_state, _publish_light_state) plus relay-topic parsing from
// _on_relay_state. All pure: no HA, no MQTT, fully tested.
package entities

import (
	"strings"

	"nspanelcore/ha"
)

// Light mirrors the live fields of LightConfig relevant to state sync.
type Light struct {
	State      bool
	Brightness int // 0-100
	ColorTemp  int // kelvin
	Hue        int
	Saturation int
	Mode       string // "default" | "rgb"
	CanDim     bool
	CanCT      bool
	CanRGB     bool
}

// HAAttrs mirrors the subset of new_state.attributes the manager reads.
type HAAttrs struct {
	Brightness *int
	ColorMode  string
	Kelvin     *int
	HSH        *int
	HSS        *int
}

// Ingest mirrors _ingest_light_state. Returns changed.
func Ingest(l *Light, haState string, a HAAttrs) bool {
	changed := false
	if haState == "on" {
		if !l.State {
			changed = true
		}
		l.State = true
		if l.CanDim {
			b := 100
			if a.Brightness != nil {
				b = *a.Brightness * 100 / 255
			}
			if b != l.Brightness {
				changed = true
			}
			l.Brightness = b
		} else {
			if l.Brightness != 100 {
				changed = true
			}
			l.Brightness = 100
		}
	} else if haState == "off" {
		if l.State {
			changed = true
		}
		l.State = false
	}
	if a.ColorMode == "color_temp" && l.CanCT {
		l.Mode = "default"
		if a.Kelvin != nil && *a.Kelvin != l.ColorTemp {
			changed = true
			l.ColorTemp = *a.Kelvin
		}
	} else if a.ColorMode == "hs" && l.CanRGB {
		l.Mode = "rgb"
		if a.HSH != nil && a.HSS != nil && (*a.HSH != l.Hue || *a.HSS != l.Saturation) {
			changed = true
			l.Hue = *a.HSH
			l.Saturation = *a.HSS
		}
	}
	return changed
}

// Publish mirrors _publish_light_state: four retained payloads.
func Publish(l Light, minK, maxK int) map[string]string {
	k := l.ColorTemp
	if k == 0 {
		k = minK
	}
	k = ha.ClampKelvin(k, minK, maxK)
	bri := 0
	if l.State {
		bri = l.Brightness
	}
	return map[string]string{
		"state_brightness_pct": itoa(bri),
		"state_kelvin":         itoa(k),
		"state_hue":            itoa(l.Hue),
		"state_sat":            itoa(l.Saturation),
	}
}

// ParseRelayTopic mirrors _on_relay_state parsing: nspanel/<seg>/r1_state|
// r2_state. Returns segment, relay (0 when unparseable).
func ParseRelayTopic(topic string) (string, int) {
	parts := strings.Split(topic, "/")
	if len(parts) == 3 && parts[0] == "nspanel" &&
		(parts[2] == "r1_state" || parts[2] == "r2_state") {
		return parts[1], int(parts[2][1] - '0')
	}
	return "", 0
}

// ParseRelayPayload mirrors the payload truth table.
func ParseRelayPayload(payload string) bool {
	switch strings.TrimSpace(strings.ToLower(payload)) {
	case "1", "true", "on":
		return true
	default:
		return false
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}
