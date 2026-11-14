// Package publish ports the bounded MQTT publish-retry from manager.py.
//
// The audit fix: publish retries must be bounded (3 attempts, exponential
// backoff) — the old code retried forever and wedged the event loop on a
// dead broker. Backoff computation is pure so it is unit-tested; sleeping
// lives in main.
package publish

import "time"

// Policy mirrors the retry bounds.
type Policy struct {
	MaxAttempts int
	BaseDelay   time.Duration
	MaxDelay    time.Duration
}

// Default mirrors the manager defaults.
func Default() Policy {
	return Policy{MaxAttempts: 3, BaseDelay: 200 * time.Millisecond, MaxDelay: 2 * time.Second}
}

// Backoff returns the delay before attempt n (1-based). attempt 1 = no wait.
func (p Policy) Backoff(attempt int) time.Duration {
	if attempt <= 1 {
		return 0
	}
	d := p.BaseDelay
	for i := 2; i < attempt; i++ {
		d *= 2
		if d >= p.MaxDelay {
			return p.MaxDelay
		}
	}
	if d > p.MaxDelay {
		return p.MaxDelay
	}
	return d
}

// ShouldRetry reports whether another attempt is allowed after attempt n failed.
func (p Policy) ShouldRetry(attempt int) bool {
	return attempt < p.MaxAttempts
}
