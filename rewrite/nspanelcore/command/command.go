// Package command ports the inbound command parsing from manager.py:
// _on_manager_command (register/set/scene JSON) and _on_stomp_send
// (browser SEND -> panel command normalization). Pure parsing; execution
// lives in main.
package command

import (
	"encoding/json"
	"strings"
)

// ManagerCmd is one parsed nspanel/mqttmanager/command payload.
type ManagerCmd struct {
	Kind      string // "register" | "set" | "activate_scene" | "save_scene" | "unknown"
	MAC       string
	Attribute string // set only: brightness|kelvin|hue|saturation
	Value     int    // set only
	EntityIDs []int  // set only
	SceneID   int    // scene only
	Raw       map[string]any
}

// ParseManager mirrors _on_manager_command dispatch.
func ParseManager(payload string) ManagerCmd {
	var data map[string]any
	if err := json.Unmarshal([]byte(payload), &data); err != nil {
		return ManagerCmd{Kind: "unknown"}
	}
	if data["command"] == "register_request" {
		mac, _ := data["mac_origin"].(string)
		if mac == "" {
			mac, _ = data["mac_address"].(string)
		}
		if mac == "" {
			mac, _ = data["mac"].(string)
		}
		return ManagerCmd{Kind: "register", MAC: mac, Raw: data}
	}
	if data["command"] == "activate_scene" {
		return ManagerCmd{Kind: "activate_scene", SceneID: toInt(data["scene_id"]), Raw: data}
	}
	if data["command"] == "save_scene" {
		return ManagerCmd{Kind: "save_scene", SceneID: toInt(data["scene_id"]), Raw: data}
	}
	if data["method"] == "set" {
		attr, _ := data["attribute"].(string)
		key, ok := map[string]string{
			"brightness": "brightness", "kelvin": "kelvin",
			"hue": "hue", "saturation": "saturation",
		}[attr]
		if !ok {
			return ManagerCmd{Kind: "unknown", Raw: data}
		}
		var ids []int
		if arr, ok := data["entity_ids"].([]any); ok {
			for _, v := range arr {
				ids = append(ids, toInt(v))
			}
		}
		return ManagerCmd{Kind: "set", Attribute: key, Value: toInt(data[key]), EntityIDs: ids, Raw: data}
	}
	return ManagerCmd{Kind: "unknown", Raw: data}
}

// StompSend mirrors _on_stomp_send: only nspanel/<seg>/command from a known
// panel forwards; payload normalizes to {"command": ...}.
func StompSend(destination, body string, knownPanel func(seg string) bool) (topic, payload string, ok bool) {
	parts := strings.Split(destination, "/")
	if len(parts) != 3 || parts[0] != "nspanel" || parts[2] != "command" {
		return "", "", false
	}
	if !knownPanel(parts[1]) {
		return "", "", false
	}
	trimmed := strings.TrimSpace(body)
	var obj map[string]any
	if err := json.Unmarshal([]byte(trimmed), &obj); err == nil {
		if cmd, has := obj["command"]; has {
			_ = cmd
			out, _ := json.Marshal(obj)
			return "nspanel/" + parts[1] + "/command", string(out), true
		}
	}
	word := map[string]string{"gui_update": "tft_update", "firmware_update_force": "firmware_update"}[trimmed]
	if word == "" {
		word = trimmed
	}
	out, _ := json.Marshal(map[string]string{"command": word})
	return "nspanel/" + parts[1] + "/command", string(out), true
}

func toInt(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case int64:
		return int(n)
	default:
		return 0
	}
}
