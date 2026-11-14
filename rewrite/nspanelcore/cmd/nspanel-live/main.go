// Command nspanel-live is the read-only live proof of the Go rewrite.
//
// It connects to Home Assistant over WebSocket (exactly like a browser
// would), authenticates with a long-lived token, subscribes to the MQTT
// broker traffic via the mqtt.subscribe service, and decodes real panel
// frames with the ported packages. It NEVER publishes: no command, no OTA,
// no state change — the panel and HA are untouched.
//
// Usage:
//
//	nspanel-live -ha wss://ha.example.com/api/websocket -token-file /run/secrets/ha_token [-topic nspanel/#] [-seconds 60]
package main

import (
	"crypto/tls"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"nspanelcore/topics"
)

type wsMsg map[string]any

func send(conn *websocket.Conn, v any) error {
	conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return conn.WriteJSON(v)
}

func main() {
	haURL := flag.String("ha", "", "HA websocket URL (ws(s)://host/api/websocket)")
	tokenFile := flag.String("token-file", "", "file containing a long-lived HA access token")
	topic := flag.String("topic", "nspanel/#", "MQTT topic filter to watch")
	seconds := flag.Int("seconds", 60, "how long to watch")
	insecure := flag.Bool("insecure", false, "skip TLS verification (self-signed proxies)")
	flag.Parse()

	if *haURL == "" || *tokenFile == "" {
		log.Fatal("usage: nspanel-live -ha wss://host/api/websocket -token-file FILE")
	}
	tokRaw, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatalf("read token: %v", err)
	}
	token := strings.TrimSpace(string(tokRaw))
	if token == "" {
		log.Fatal("empty token")
	}

	dialer := websocket.Dialer{HandshakeTimeout: 15 * time.Second}
	if *insecure {
		dialer.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} //nolint:gosec
	} else {
		dialer.TLSClientConfig = &tls.Config{} // system roots; proxy certs included
	}
	_ = http.Header{}
	conn, resp, err := dialer.Dial(*haURL, nil)
	if err != nil {
		if resp != nil {
			log.Fatalf("dial %s: %v (http %d)", *haURL, err, resp.StatusCode)
		}
		log.Fatalf("dial %s: %v", *haURL, err)
	}
	defer conn.Close()

	read := func() wsMsg {
		conn.SetReadDeadline(time.Now().Add(30 * time.Second))
		var m wsMsg
		if err := conn.ReadJSON(&m); err != nil {
			log.Fatalf("read: %v", err)
		}
		return m
	}

	// 1. auth_required -> auth -> auth_ok (same handshake a browser does).
	m := read()
	if m["type"] != "auth_required" {
		log.Fatalf("expected auth_required, got %v", m["type"])
	}
	if err := send(conn, map[string]any{"type": "auth", "access_token": token}); err != nil {
		log.Fatalf("auth send: %v", err)
	}
	// Best-effort token redaction: never log the token back.
	token = ""
	m = read()
	if m["type"] != "auth_ok" {
		log.Fatalf("auth failed: %v", m)
	}
	log.Print("live: authenticated with Home Assistant")

	// 2. Subscribe the BROKER (server-side) to the topic filter. This only
	// adds a subscription — it publishes nothing to any topic.
	// Raw broker frames use the frontend mechanism: a message-type
	// mqtt/subscribe whose forwards arrive tagged with our id. (The
	// call_service variant subscribes the broker but never forwards to WS.)
	if err := send(conn, map[string]any{
		"id": 10, "type": "mqtt/subscribe", "topic": *topic,
	}); err != nil {
		log.Fatalf("mqtt subscribe: %v", err)
	}

	// 3. Also subscribe to HA events so entity state changes stream too.
	if err := send(conn, map[string]any{
		"id": 2, "type": "subscribe_events", "event_type": "state_changed",
	}); err != nil {
		log.Fatalf("subscribe_events: %v", err)
	}

	deadline := time.Now().Add(time.Duration(*seconds) * time.Second)
	seen := 0
	for time.Now().Before(deadline) {
		conn.SetReadDeadline(deadline)
		var m wsMsg
		if err := conn.ReadJSON(&m); err != nil {
			if websocket.IsUnexpectedCloseError(err) {
				log.Printf("live: connection closed: %v", err)
			}
			break
		}
		t, _ := m["type"].(string)
		if t == "result" {
			continue // acks for our two requests
		}
		if t != "event" {
			continue
		}
		ev, _ := m["event"].(map[string]any)
		if ev == nil {
			continue
		}
		// MQTT forwards (from mqtt.subscribe) carry topic/payload directly
		// on the event object — no event_type. Handle before the switch.
		if mtopic, hasTopic := ev["topic"].(string); hasTopic {
			payload, _ := ev["payload"].(string)
			seg := topics.Segment(mtopic)
			fmt.Printf("MQTT %-48s seg=%-16q %d bytes %s\n", mtopic, seg, len(payload), preview(payload, 140))
			seen++
			continue
		}
		etype, _ := ev["event_type"].(string)
		data, _ := ev["data"].(map[string]any)
		switchType := etype
		_ = switchType
		switch etype {
		case "mqtt_message":
			mtopic, _ := data["topic"].(string)
			payload, _ := data["payload"].(string)
			seg := topics.Segment(mtopic)
			fmt.Printf("MQTT %-48s seg=%-16q %d bytes %s\n", mtopic, seg, len(payload), preview(payload, 140))
			seen++
		case "state_changed":
			eid, _ := data["entity_id"].(string)
			if strings.Contains(eid, "kitchenpanel") || strings.Contains(eid, "nspanel") ||
				strings.Contains(eid, "dressing") {
				ns, _ := data["new_state"].(map[string]any)
				st := ""
				if ns != nil {
					st, _ = ns["state"].(string)
				}
				fmt.Printf("HA   %-48s -> %s\n", eid, st)
				seen++
			}
		}
	}
	fmt.Printf("live: done, %d panel-related frames in %ds (zero publishes sent)\n", seen, *seconds)
}

func preview(s string, n int) string {
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.TrimSpace(s)
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}
