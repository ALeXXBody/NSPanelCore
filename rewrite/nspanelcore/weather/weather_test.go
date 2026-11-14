package weather_test

import (
	"strings"
	"testing"

	"nspanelcore/weather"
)

func TestIconFallback(t *testing.T) {
	if weather.Icon(0) != "sunny" || weather.Icon(95) != "thunderstorm" {
		t.Fatal("known icons broken")
	}
	if weather.Icon(999) != "cloudy_weather_day" {
		t.Fatal("fallback broken")
	}
}

func TestFmtTemp(t *testing.T) {
	if weather.FmtTemp(21.4, false) != "21°C" || weather.FmtTemp(70.6, true) != "71°F" {
		t.Fatal("temp format broken")
	}
}

// Regression: Python round() is banker's (half to even); the first Go port
// used half-away, so exact x.5 temps were off by one vs the manager.
func TestBankersRoundingParity(t *testing.T) {
	if weather.FmtTemp(2.5, false) != "2°C" {
		t.Fatalf("2.5 must round to even 2, got %q", weather.FmtTemp(2.5, false))
	}
	if weather.FmtTemp(3.5, false) != "4°C" {
		t.Fatalf("3.5 must round to even 4, got %q", weather.FmtTemp(3.5, false))
	}
	if weather.FmtWind(2.5, "kmh") != "2 km/h" || weather.FmtWind(3.5, "kmh") != "4 km/h" {
		t.Fatal("wind banker's rounding broken")
	}
}

func TestFmtWind(t *testing.T) {
	if weather.FmtWind(12.34, "ms") != "12.3 m/s" {
		t.Fatal("ms broken")
	}
	if weather.FmtWind(12.4, "mph") != "12 mph" {
		t.Fatal("mph broken")
	}
	if weather.FmtWind(12.4, "kn") != "12 kn" {
		t.Fatal("kn broken")
	}
	if weather.FmtWind(12.4, "kmh") != "12 km/h" || weather.FmtWind(12.4, "bogus") != "12 km/h" {
		t.Fatal("kmh fallback broken")
	}
}

func TestUnitsAndURL(t *testing.T) {
	tu, pu, wu := weather.Units(false, "mm", "bogus")
	if tu != "celsius" || pu != "mm" || wu != "kmh" {
		t.Fatal("units fallback broken")
	}
	u := weather.URL(50.5, 4.5, "celsius", "mm", "kmh")
	if !strings.Contains(u, "latitude=50.5") || !strings.Contains(u, "timezone=auto") {
		t.Fatalf("url broken: %s", u)
	}
	if !weather.ValidCoords(50, 4) || weather.ValidCoords(999, 4) {
		t.Fatal("coords guard broken")
	}
}
