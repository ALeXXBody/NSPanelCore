package timepub_test

import (
	"testing"
	"time"

	"nspanelcore/timepub"
)

func TestEUFormat(t *testing.T) {
	ts := time.Date(2026, 11, 14, 21, 5, 0, 0, time.UTC)
	tstr, ampm, dstr := timepub.Format(ts, false, "%d/%m")
	if tstr != "21:05" || ampm != "" || dstr != "14/11" {
		t.Fatalf("got %q %q %q", tstr, ampm, dstr)
	}
}

func TestUSFormat(t *testing.T) {
	ts := time.Date(2026, 11, 14, 21, 5, 0, 0, time.UTC)
	tstr, ampm, _ := timepub.Format(ts, true, "%d/%m")
	if tstr != "09:05" || ampm != "PM" {
		t.Fatalf("got %q %q", tstr, ampm)
	}
}

func TestBadDateFormatFallsBack(t *testing.T) {
	ts := time.Date(2026, 11, 14, 21, 5, 0, 0, time.UTC)
	_, _, dstr := timepub.Format(ts, false, "%Q")
	if dstr != "14/11" {
		t.Fatalf("fallback broken: %q", dstr)
	}
}
