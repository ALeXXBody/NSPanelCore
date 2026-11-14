package manager_test

import (
	"testing"

	"nspanelcore/manager"
)

func TestRelayPrimaryAndFallbackSeparate(t *testing.T) {
	s := manager.NewRelayStore()
	// Unknown panel frame: stored under the raw topic, still retrievable
	// via the fallback path (Python stored it but could never read it back
	// through relay_state — write-only garbage).
	s.SetFallback("nspanel/Ghost/r1_state", true)
	st, ok := s.Get("ghost", 1, "nspanel/Ghost/r1_state")
	if !ok || !st {
		t.Fatal("fallback must be retrievable by raw topic")
	}
	// Primary lookup for a DIFFERENT panel must not see it (no keyspace
	// collision between tuple keys and raw strings — impossible by type).
	if _, ok := s.Get("e465b849a100", 1, "nspanel/KitchenPanel/r1_state"); ok {
		t.Fatal("fallback for one topic must not leak into another panel")
	}
	// Known panel: primary wins.
	s.SetPrimary("e465b849a100", 1, false)
	if st, ok := s.Get("e465b849a100", 1, "nspanel/KitchenPanel/r1_state"); !ok || st {
		t.Fatal("primary must win and report stored state")
	}
}

func TestRelayPurgeOnRemove(t *testing.T) {
	s := manager.NewRelayStore()
	s.SetPrimary("aa", 1, true)
	s.SetPrimary("aa", 2, false)
	s.SetPrimary("bb", 1, true)
	s.PurgeMAC("aa")
	if _, ok := s.Get("aa", 1, "x"); ok {
		t.Fatal("removed panel state must be purged")
	}
	if _, ok := s.Get("bb", 1, "x"); !ok {
		t.Fatal("other panels must survive purge")
	}
}

func TestPurgeStringMap(t *testing.T) {
	m := map[string]int{"a": 1, "b": 2}
	manager.PurgeStringMap(m, "a", "missing")
	if _, ok := m["a"]; ok {
		t.Fatal("key must be gone")
	}
	if m["b"] != 2 {
		t.Fatal("other keys must survive")
	}
}
