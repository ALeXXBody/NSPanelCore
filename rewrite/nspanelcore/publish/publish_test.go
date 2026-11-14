package publish_test

import (
	"testing"
	"time"

	"nspanelcore/publish"
)

func TestBounds(t *testing.T) {
	p := publish.Default()
	if p.Backoff(1) != 0 || p.Backoff(2) != 200*time.Millisecond {
		t.Fatal("backoff base broken")
	}
	if !p.ShouldRetry(1) || !p.ShouldRetry(2) || p.ShouldRetry(3) {
		t.Fatal("attempt bounds broken (3 attempts max)")
	}
	if p.Backoff(99) != p.MaxDelay {
		t.Fatal("backoff must cap at max")
	}
}
