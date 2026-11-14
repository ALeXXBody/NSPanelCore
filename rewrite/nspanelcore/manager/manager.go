// Package manager ports the pure routing/OTA-decision logic from manager.py.
//
// Deliberately free of I/O: all functions are deterministic and unit-tested.
// The Python manager had three routing bugs fixed across v1.3.36–v1.3.41:
//   1. rename black-holed inbound routing (name vs wifi_hostname split),
//   2. MAC-keyed relay state collided after normalization,
//   3. data_file auto-OTA wiped remote WiFi (now never auto).
// Those rules are encoded here and locked by tests.
package manager

import (
	"nspanelcore/topics"
)

// Panel is the minimal routing surface (full shape lives in config.Panel).
type Panel struct {
	ID           int
	MAC          string
	Name         string
	WifiHostname string
	Model        string // "sonoff" | "custom" (anything else -> sonoff)
	IsUSPanel    bool
}

// RoutingName returns the name the firmware subscribes on.
func (p Panel) RoutingName() string {
	if p.WifiHostname != "" {
		return p.WifiHostname
	}
	return p.Name
}

// CommandTopic mirrors _panel_cmd_topic: always hostname-based.
func CommandTopic(p Panel, suffix string) string {
	return topics.PanelTopic(p.RoutingName(), suffix)
}

// NoteHostname mirrors _note_panel_hostname: heal routing on drift.
func NoteHostname(p *Panel, segment string) bool {
	if segment != "" && segment != p.WifiHostname {
		p.WifiHostname = segment
		return true
	}
	return false
}

// FindByTopic mirrors _panel_by_topic: verbatim hostname first, then
// name/MAC verbatim, then normalized with drift flag.
func FindByTopic(panels []Panel, segment string) (*Panel, bool, bool) {
	if segment == "" {
		return nil, false, false
	}
	for i := range panels {
		if panels[i].WifiHostname != "" && panels[i].WifiHostname == segment {
			return &panels[i], false, true
		}
	}
	for i := range panels {
		if panels[i].Name == segment || panels[i].MAC == segment {
			return &panels[i], false, true
		}
	}
	want := topics.Safe(segment)
	for i := range panels {
		if topics.Safe(panels[i].Name) == want || topics.Safe(panels[i].MAC) == want {
			return &panels[i], true, true
		}
	}
	return nil, false, false
}

// FindByMAC mirrors _panel_by_mac (normalized).
func FindByMAC(panels []Panel, mac string) *Panel {
	want := topics.Safe(mac)
	for i := range panels {
		if topics.Safe(panels[i].MAC) == want {
			return &panels[i]
		}
	}
	return nil
}

// RelayKey mirrors relay_state keying: (topic_safe(mac), relay).
func RelayKey(mac string, relay int) (string, int) {
	return topics.Safe(mac), relay
}

// OTARequest mirrors the report + cache inputs to _maybe_trigger_firmware_ota.
type OTARequest struct {
	Model            string // panel model (fallback sonoff)
	ReportFirmwareMD5 string
	ReportLittlefsMD5 string
	ReportTFTMD5      string
	CachedFirmwareMD5 string
	CachedDataMD5     string
	CachedTFTMD5      string
	AutoTFTUpdates   bool
	IsUSPanel        bool
}

// OTADecision is what to trigger. Data is NEVER auto (wipes WiFi).
type OTADecision struct {
	Firmware bool
	TFT      bool
	// DataAvailable is informational only — caller must NOT auto-trigger.
	DataAvailable bool
}

// DecideOTA mirrors _maybe_trigger_firmware_ota without I/O.
func DecideOTA(r OTARequest) OTADecision {
	var d OTADecision
	if r.CachedFirmwareMD5 != "" && r.ReportFirmwareMD5 != "" &&
		r.ReportFirmwareMD5 != r.CachedFirmwareMD5 {
		d.Firmware = true
	}
	if r.CachedDataMD5 != "" && r.ReportLittlefsMD5 != "" &&
		r.ReportLittlefsMD5 != r.CachedDataMD5 {
		d.DataAvailable = true // never auto-triggered
	}
	if r.CachedTFTMD5 != "" && r.ReportTFTMD5 != "" &&
		r.ReportTFTMD5 != r.CachedTFTMD5 && r.AutoTFTUpdates {
		d.TFT = true
	}
	return d
}

// ModelKey mirrors the model fallback in _maybe_trigger_firmware_ota.
func ModelKey(model string) string {
	if model == "sonoff" || model == "custom" {
		return model
	}
	return "sonoff"
}

// TFTFilename mirrors the EU/US selection.
func TFTFilename(isUS bool) string {
	if isUS {
		return "gui_us.tft"
	}
	return "gui.tft"
}
