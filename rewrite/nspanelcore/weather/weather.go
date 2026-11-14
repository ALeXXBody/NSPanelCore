// Package weather ports the open-meteo formatting from _poll_weather:
// icon mapping, temperature/wind formatting, unit selection, URL building.
// Network fetch lives in main; everything here is pure and tested.
package weather

import "fmt"

// Icon mirrors the ICONS dict lookup with cloudy_weather_day fallback.
func Icon(code int) string {
	switch code {
	case 0:
		return "sunny"
	case 1:
		return "partlytuner_day"
	case 2:
		return "cloudy_weather_day"
	case 3:
		return "overcast"
	case 45, 48:
		return "fog"
	case 51, 53, 55, 80, 81, 82:
		return "rainy"
	case 56, 57, 66, 67:
		return "sleet"
	case 61, 63, 65:
		return "rainy"
	case 71, 73, 75, 77, 85, 86:
		return "snowy"
	case 95, 96, 99:
		return "thunderstorm"
	default:
		return "cloudy_weather_day"
	}
}

// FmtTemp mirrors fmt_temp: rounded int + degree unit.
func FmtTemp(v float64, fahrenheit bool) string {
	if fahrenheit {
		return fmt.Sprintf("%d°F", int(round(v)))
	}
	return fmt.Sprintf("%d°C", int(round(v)))
}

func round(v float64) float64 {
	if v < 0 {
		return float64(int(v - 0.5))
	}
	return float64(int(v + 0.5))
}

// FmtWind mirrors fmt_wind.
func FmtWind(v float64, format string) string {
	switch format {
	case "ms":
		return fmt.Sprintf("%.1f m/s", v)
	case "mph":
		return fmt.Sprintf("%d mph", int(round(v)))
	case "kn":
		return fmt.Sprintf("%d kn", int(round(v)))
	default: // "kmh" and unknown
		return fmt.Sprintf("%d km/h", int(round(v)))
	}
}

// Units mirrors the temp/precip/wind unit selection.
func Units(useFahrenheit bool, precipFormat, windFormat string) (temp, precip, wind string) {
	if useFahrenheit {
		temp = "fahrenheit"
	} else {
		temp = "celsius"
	}
	if precipFormat == "inch" {
		precip = "inch"
	} else {
		precip = "mm"
	}
	switch windFormat {
	case "ms", "mph", "kn":
		wind = windFormat
	default:
		wind = "kmh"
	}
	return temp, precip, wind
}

// URL mirrors the open-meteo URL construction.
func URL(lat, lon float64, tempUnit, precipUnit, windUnit string) string {
	return fmt.Sprintf(
		"https://api.open-meteo.com/v1/forecast?latitude=%v&longitude=%v"+
			"&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m"+
			"&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max"+
			"&timeformat=unixtime&temperature_unit=%s&precipitation_unit=%s&wind_speed_unit=%s&timezone=auto",
		lat, lon, tempUnit, precipUnit, windUnit)
}

// ValidCoords mirrors the lat/lon guard.
func ValidCoords(lat, lon float64) bool {
	return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
}
