// Relay state store with a TYPED fallback — fixes a Python trap.
//
// manager._relay_state mixes key types in one dict: (mac, relay) tuples for
// known panels and raw topic STRINGS for unknown ones. relay_state() only
// looks up tuples, so fallback entries are write-only garbage, and any
// future tuple-keyed lookup of a raw topic collides silently. Here the two
// live in separate maps (a compile-time guarantee), with an explicit
// lookup order: primary first, fallback second.
package manager

// RelayStore holds per-relay states. Primary keys are normalized MAC +
// relay number; fallback keys are raw topic strings for unparseable or
// unknown-panel frames.
type RelayStore struct {
	primary  map[[2]any]bool
	fallback map[string]bool
}

// NewRelayStore returns an empty store.
func NewRelayStore() *RelayStore {
	return &RelayStore{
		primary:  map[[2]any]bool{},
		fallback: map[string]bool{},
	}
}

// SetPrimary records state for a known panel (mac is normalized by the
// caller via topics.Safe, mirroring topic_safe(panel.mac)).
func (s *RelayStore) SetPrimary(macSafe string, relay int, state bool) {
	s.primary[[2]any{macSafe, relay}] = state
}

// SetFallback records state keyed by the raw topic (unknown panel or
// unparseable frame). Never shares keyspace with primary.
func (s *RelayStore) SetFallback(rawTopic string, state bool) {
	s.fallback[rawTopic] = state
}

// Get returns state: primary first, then the caller's fallback topic.
// ok is false when neither holds the key (mirrors dict.get default).
func (s *RelayStore) Get(macSafe string, relay int, fallbackTopic string) (state, ok bool) {
	if v, found := s.primary[[2]any{macSafe, relay}]; found {
		return v, true
	}
	if v, found := s.fallback[fallbackTopic]; found {
		return v, true
	}
	return false, false
}

// PurgeMAC drops every entry belonging to a panel (mirrors remove_panel's
// relay-state purge so removals don't leak stale on/off states).
func (s *RelayStore) PurgeMAC(macSafe string) {
	for k := range s.primary {
		if k[0] == macSafe {
			delete(s.primary, k)
		}
	}
}

// PurgeTopic drops fallback entries under a topic segment (rename cleanup).
func (s *RelayStore) PurgeTopic(segment string) {
	for t := range s.fallback {
		if len(t) >= len(segment) && containsSegment(t, segment) {
			delete(s.fallback, t)
		}
	}
}

func containsSegment(topic, segment string) bool {
	for i := 0; i+len(segment) <= len(topic); i++ {
		if topic[i:i+len(segment)] == segment {
			return true
		}
	}
	return false
}

// PurgeStringMap drops keys from a MAC-keyed map (telemetry, OTA stamps,
// listeners). Generics keep it type-safe across value types.
func PurgeStringMap[V any](m map[string]V, keys ...string) {
	for _, k := range keys {
		delete(m, k)
	}
}
