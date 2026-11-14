// Package ha ports the Home Assistant WebSocket + service-call layer:
// message builders are pure JSON so they are unit-testable; the socket
// itself lives in main. Mirrors manager.py service semantics including
// optimistic mode and kelvin clamping.
package ha

import (
	"encoding/json"
	"fmt"
)

// LightCommand mirrors the lc dict built in _on_manager_command.
type LightCommand struct {
	HasBrightness       bool
	Brightness          int // panel 0-100
	HasColorTemperature bool
	ColorTemperature    int // kelvin, absolute
	HasHue              bool
	Hue                 int
	HasSaturation       bool
	Saturation          int
}

// TurnOnPayload builds light.turn_on service data. Brightness converts
// panel 0-100 to HA 0-255; kelvin is clamped to [minK,maxK]; hs members
// pass through only when set.
func TurnOnPayload(entityID string, cmd LightCommand, minK, maxK int) map[string]any {
	data := map[string]any{"entity_id": entityID}
	if cmd.HasBrightness {
		b := cmd.Brightness * 255 / 100
		if b < 0 {
			b = 0
		}
		if b > 255 {
			b = 255
		}
		// HA ignores brightness 0 on turn_on; callers map 0 to turn_off.
		data["brightness"] = b
	}
	if cmd.HasColorTemperature {
		k := cmd.ColorTemperature
		if k < minK {
			k = minK
		}
		if k > maxK {
			k = maxK
		}
		data["kelvin"] = k
	}
	var hs []int
	hasHS := false
	if cmd.HasHue {
		hs = append(hs, cmd.Hue)
		hasHS = true
	} else {
		hs = append(hs, 0)
	}
	if cmd.HasSaturation {
		if len(hs) == 1 {
			hs = append(hs, cmd.Saturation)
		}
		hasHS = true
	}
	if hasHS && cmd.HasHue && cmd.HasSaturation {
		data["hs_color"] = []int{hs[0], hs[1]}
	} else if hasHS {
		// Partial hs: pass what we have; HA merges with current.
		if cmd.HasHue {
			data["hs_color"] = []int{cmd.Hue, 0}
		} else {
			data["hs_color"] = []int{0, cmd.Saturation}
		}
	}
	return data
}

// WSMessages: minimal builders for the HA websocket API.
func AuthMsg(token string) string {
	m, _ := json.Marshal(map[string]any{"type": "auth", "access_token": token})
	return string(m)
}

func SubscribeEvents(id int) string {
	m, _ := json.Marshal(map[string]any{"id": id, "type": "subscribe_events", "event_type": "state_changed"})
	return string(m)
}

func GetStates(id int) string {
	m, _ := json.Marshal(map[string]any{"id": id, "type": "get_states"})
	return string(m)
}

func CallService(id int, domain, service string, data map[string]any) string {
	m, _ := json.Marshal(map[string]any{
		"id": id, "type": "call_service",
		"domain": domain, "service": service, "service_data": data,
	})
	return string(m)
}

// BrightnessToPct mirrors ingest: HA 0-255 -> panel 0-100 (int truncation).
func BrightnessToPct(bri int) int { return bri * 100 / 255 }

// PctToBrightness mirrors command path: panel 0-100 -> HA 0-255.
func PctToBrightness(pct int) int {
	b := pct * 255 / 100
	if b < 0 {
		return 0
	}
	if b > 255 {
		return 255
	}
	return b
}

// ClampKelvin mirrors _publish_light_state clamping.
func ClampKelvin(k, minK, maxK int) int {
	if k < minK {
		return minK
	}
	if k > maxK {
		return maxK
	}
	return k
}

var _ = fmt.Sprint
