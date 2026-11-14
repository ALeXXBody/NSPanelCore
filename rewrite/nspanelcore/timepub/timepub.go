// Package timepub ports _publish_time formatting: minute-aligned time/ampm/
// date strings. Pure formatting — scheduling lives in main.
package timepub

import "time"

// Format mirrors the Python strftime logic with safe fallbacks.
func Format(now time.Time, usStyle bool, dateFormat string) (timeStr, ampm, dateStr string) {
	if usStyle {
		timeStr = now.Format("03:04")
		ampm = now.Format("PM")
	} else {
		timeStr = now.Format("15:04")
		ampm = ""
	}
	if dateFormat == "" {
		dateFormat = "%d/%m"
	}
	dateStr = strftime(dateFormat, now)
	return timeStr, ampm, dateStr
}

// strftime supports the subset HA users actually configure (%d %m %Y %y %H
// %M %I %p %a %A %b %B) and falls back to %d/%m on anything else, mirroring
// the Python try/except around strftime.
func strftime(fmt string, t time.Time) string {
	// Translate known verbs; if an unknown %verb appears, fall back.
	out := ""
	for i := 0; i < len(fmt); i++ {
		if fmt[i] != '%' || i+1 >= len(fmt) {
			out += string(fmt[i])
			continue
		}
		i++
		switch fmt[i] {
		case 'd':
			out += t.Format("02")
		case 'm':
			out += t.Format("01")
		case 'Y':
			out += t.Format("2006")
		case 'y':
			out += t.Format("06")
		case 'H':
			out += t.Format("15")
		case 'M':
			out += t.Format("04")
		case 'I':
			out += t.Format("03")
		case 'p':
			out += t.Format("PM")
		case 'a':
			out += t.Format("Mon")
		case 'A':
			out += t.Format("Monday")
		case 'b':
			out += t.Format("Jan")
		case 'B':
			out += t.Format("January")
		case 'e':
			out += t.Format("2")
		case 'k':
			out += t.Format("15")
		case 'l':
			out += t.Format("3")
		case 'j':
			out += t.Format("002")
		case '%':
			out += "%"
		default:
			return t.Format("02/01")
		}
	}
	return out
}
