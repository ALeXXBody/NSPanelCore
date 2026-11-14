// Package mqttstore ports the MQTT topic matching + retained registry from
// manager.py / stomp_server.py: + matches one level, # matches the rest
// (only as the final level), and retained values replay to late subscribers.
// Bounded publish-retry lives in main; matching and storage here are pure.
package mqttstore

import "strings"

// Match reports whether topic matches an MQTT subscription filter.
// + = exactly one level, # = rest (final level only).
func Match(filter, topic string) bool {
	if filter == "#" {
		return true
	}
	f := strings.Split(filter, "/")
	t := strings.Split(topic, "/")
	for i, part := range f {
		if part == "#" {
			return i == len(f)-1 // # only valid as final level
		}
		if i >= len(t) {
			return false
		}
		if part == "+" {
			continue
		}
		if part != t[i] {
			return false
		}
	}
	return len(f) == len(t)
}

// Store is a retained-value registry: last retained payload per topic.
type Store struct {
	values map[string]string
}

// New returns an empty Store.
func New() *Store { return &Store{values: map[string]string{}} }

// Set stores a retained payload (empty payload deletes, per MQTT).
func (s *Store) Set(topic, payload string) {
	if payload == "" {
		delete(s.values, topic)
		return
	}
	s.values[topic] = payload
}

// Get returns the retained payload for an exact topic.
func (s *Store) Get(topic string) (string, bool) {
	v, ok := s.values[topic]
	return v, ok
}

// Replay returns all retained payloads matching filter (for new subscribers).
func (s *Store) Replay(filter string) map[string]string {
	out := map[string]string{}
	for topic, payload := range s.values {
		if Match(filter, topic) {
			out[topic] = payload
		}
	}
	return out
}

// Len is for tests.
func (s *Store) Len() int { return len(s.values) }
