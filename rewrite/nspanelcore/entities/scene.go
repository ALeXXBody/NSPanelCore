package entities

// SceneState mirrors one NSPM-managed light_states entry as stored.
type SceneState struct {
	LightID          int
	LightLevel       int    // 0-100, 0 means off
	ColorMode        string // "dimmer" | "rgb" | legacy "color"
	ColorTemperature int
	Hue              int
	Saturation       int
}

// NormalizeColorMode maps legacy stored values to the live enum. Panels and
// old exports wrote "color" for RGB scenes; the Python activator only
// matched "rgb" and silently turned those lights on WITHOUT their color.
// That silent color loss is the bug — normalize once, here.
func NormalizeColorMode(m string) string {
	if m == "color" {
		return "rgb"
	}
	if m == "rgb" || m == "dimmer" {
		return m
	}
	return ""
}

// ApplyScene mirrors _activate_scene's NSPM-managed branch for one light:
// level<=0 turns off; otherwise turn on with brightness_pct plus kelvin or
// hs color. Returns service, service data (without entity_id), and the
// updated light. Unknown color modes fall through to brightness-only,
// exactly like Python.
func ApplyScene(l *Light, st SceneState, minK int) (string, map[string]any) {
	if st.LightLevel <= 0 {
		l.State = false
		return "turn_off", map[string]any{}
	}
	l.State = true
	l.Brightness = st.LightLevel
	data := map[string]any{"brightness_pct": st.LightLevel}
	switch NormalizeColorMode(st.ColorMode) {
	case "dimmer":
		if l.CanCT {
			l.Mode = "default"
			l.ColorTemp = st.ColorTemperature
			data["color_temp_kelvin"] = st.ColorTemperature
		}
	case "rgb":
		if l.CanRGB {
			l.Mode = "rgb"
			l.Hue = st.Hue
			l.Saturation = st.Saturation
			data["hs_color"] = []int{st.Hue, st.Saturation}
		}
	}
	return "turn_on", data
}
