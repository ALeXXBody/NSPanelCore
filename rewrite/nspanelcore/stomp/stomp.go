// Package stomp ports the STOMP 1.2 frame codec + auth gate from
// stomp_server.py. The v1.3.41 fix gated SUBSCRIBE/SEND behind an
// authenticated CONNECT (access_token validated against HA auth); the
// handshake itself stays public so browsers can connect before login.
package stomp

import (
	"strconv"
	"strings"
)

// Commands mirrors FRAME_COMMANDS.
var Commands = map[string]bool{
	"CONNECT": true, "DISCONNECT": true, "SEND": true,
	"SUBSCRIBE": true, "UNSUBSCRIBE": true, "ACK": true, "NACK": true,
	"CONNECTED": true, "MESSAGE": true, "RECEIPT": true, "ERROR": true,
}

// unescape mirrors the header unescaping in decode_frame.
func unescape(s string) string {
	// Order matters: \\r \\n \\c first, \\\\ last would double-unescape;
	// Python does value.replace calls in order \\r, \\n, \\c, \\\\.
	// Mirror exactly.
	s = strings.ReplaceAll(s, "\\r", "\r")
	s = strings.ReplaceAll(s, "\\n", "\n")
	s = strings.ReplaceAll(s, "\\c", ":")
	s = strings.ReplaceAll(s, "\\\\", "\\")
	return s
}

func escape(s string) string {
	s = strings.ReplaceAll(s, "\\", "\\\\")
	s = strings.ReplaceAll(s, "\r", "\\r")
	s = strings.ReplaceAll(s, "\n", "\\n")
	s = strings.ReplaceAll(s, ":", "\\c")
	return s
}

// Decode mirrors decode_frame: returns command, headers, body.
func Decode(data string) (string, map[string]string, string) {
	headers := map[string]string{}
	var command string
	lines := strings.Split(data, "\n")
	i := 0
	for idx, line := range lines {
		i = idx
		line = strings.TrimSuffix(line, "\r")
		if line == "" {
			i++
			break
		}
		if j := strings.Index(line, ":"); j >= 0 {
			k, v := line[:j], line[j+1:]
			if _, ok := headers[k]; !ok {
				headers[k] = unescape(v) // first header wins (STOMP 1.2)
			}
		} else if Commands[line] {
			command = line
		}
		i = idx + 1
	}
	var body string
	if i < len(lines) {
		body = strings.Join(lines[i:], "\n")
	}
	if nstr, ok := headers["content-length"]; ok {
		if n, err := strconv.Atoi(strings.TrimSpace(nstr)); err == nil && n >= 0 && n <= len(body) {
			body = body[:n]
		}
	} else if j := strings.Index(body, "\x00"); j >= 0 {
		body = body[:j]
	}
	return command, headers, body
}

// Encode mirrors encode_frame.
func Encode(command string, headers map[string]string, body string) string {
	var b strings.Builder
	b.WriteString(command + "\n")
	for k, v := range headers {
		b.WriteString(k + ":" + escape(v) + "\n")
	}
	b.WriteString("\n")
	b.WriteString(body)
	b.WriteString("\x00")
	return b.String()
}

// Gate mirrors the v1.3.41 auth boundary:
//   - CONNECT is always allowed (handshake carries the token).
//   - SUBSCRIBE/UNSUBSCRIBE/SEND require an authenticated connection.
// Returns "" when allowed, otherwise the ERROR message to send.
func Gate(command string, authenticated bool) string {
	switch command {
	case "CONNECT", "DISCONNECT":
		return ""
	case "SUBSCRIBE", "UNSUBSCRIBE", "SEND":
		if !authenticated {
			return "Not authenticated"
		}
		return ""
	default:
		return ""
	}
}
