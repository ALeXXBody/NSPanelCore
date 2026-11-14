// Package topics implements NSPanel Core MQTT topic construction and parsing.
//
// A panel is addressed by its wifi hostname, verbatim, exactly as the
// firmware builds it: "nspanel/<wifi_hostname>/...". The manager must use
// the same bytes or nothing arrives (MQTT topics are case-sensitive; only
// structural characters are sanitized, never case or spaces).
package topics

import (
	"regexp"
	"strings"
)

// structuralReplacer maps exactly the characters panel_mqtt_base replaces:
// MQTT wildcards/level separator (+, #, /) and C0 controls + DEL.
// Case and spaces are preserved verbatim to match the firmware.
var structuralReplacer = strings.NewReplacer(
	"+", "_", "#", "_", "/", "_",
	"\x00", "_", "\x01", "_", "\x02", "_", "\x03", "_",
	"\x04", "_", "\x05", "_", "\x06", "_", "\x07", "_",
	"\x08", "_", "\x09", "_", "\x0a", "_", "\x0b", "_",
	"\x0c", "_", "\x0d", "_", "\x0e", "_", "\x0f", "_",
	"\x10", "_", "\x11", "_", "\x12", "_", "\x13", "_",
	"\x14", "_", "\x15", "_", "\x16", "_", "\x17", "_",
	"\x18", "_", "\x19", "_", "\x1a", "_", "\x1b", "_",
	"\x1c", "_", "\x1d", "_", "\x1e", "_", "\x1f", "_",
	"\x7f", "_",
)

var multiUnderscore = regexp.MustCompile(`_+`)

// PanelBase mirrors panel_mqtt_base exactly: strip outer whitespace, replace
// only structural characters, return "panel" when empty. No collapsing, no
// case folding, no underscore trimming — the firmware subscribes verbatim.
func PanelBase(name string) string {
	s := strings.TrimSpace(name)
	s = structuralReplacer.Replace(s)
	if s == "" {
		return "panel"
	}
	return s
}

// Base returns the per-panel topic base: nspanel/<hostname>.
// An empty hostname yields "nspanel/panel" (never an empty level).
func Base(name string) string {
	return "nspanel/" + PanelBase(name)
}

// PanelTopic mirrors panel_mqtt_topic exactly.
func PanelTopic(name, suffix string) string {
	return "nspanel/" + PanelBase(name) + "/" + suffix
}

// Topic appends a suffix to a panel base: nspanel/<hostname>/<suffix>.
func Topic(name, suffix string) string {
	return PanelTopic(name, suffix)
}

// Segment extracts the verbatim second level of an nspanel/<seg>/... topic.
// Unlike lookups that normalize, this preserves case/spaces so the manager
// can store the exact hostname the firmware publishes on.
func Segment(topic string) string {
	parts := strings.SplitN(topic, "/", 4)
	if len(parts) >= 3 && parts[0] == "nspanel" {
		return parts[1]
	}
	return ""
}

// Safe mirrors topic_safe exactly: lowercase, strip colons/dashes (MAC
// forms), map anything outside [a-z0-9_] to underscore, collapse runs,
// strip outer underscores. For *internal* keys only — never panel addressing.
func Safe(value string) string {
	s := strings.ToLower(strings.TrimSpace(value))
	s = strings.NewReplacer(":", "", "-", "").Replace(s)
	s = regexp.MustCompile(`[^a-z0-9_]`).ReplaceAllString(s, "_")
	s = multiUnderscore.ReplaceAllString(s, "_")
	return strings.Trim(s, "_")
}

// SafeTopic normalizes an arbitrary string into a single MQTT topic level
// for *internal* keys (entity ids, dedup keys) — never for panel addressing.
func SafeTopic(value string) string {
	return Safe(value)
}
