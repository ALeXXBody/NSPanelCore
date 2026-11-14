// Command nspanel-manage is the Go takeover daemon (decisions-live).

// It maintains the panel registry from live register frames, evaluates OTA
// with the ported guards (cooldown, in-flight, report normalization), and
// fetches the served MD5s over the integration's own REST proof endpoints.
// Outbound publishes go through call_service mqtt/publish and are DISABLED
// unless --publish is passed: the proof run only logs what it WOULD do.
//
// Usage:
//
//	nspanel-manage -ha wss://host/api/websocket -rest https://host \
//	  -token-file FILE [-accepted e465b849a100,...] [-publish] [-seconds 300]
package main

import (
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"nspanelcore/manager"
	"nspanelcore/topics"
)

type panelState struct {
	MAC          string
	Hostname     string
	Model        string
	IsUS         bool
	Accepted     bool
	LastTrigger  float64 // monotonic seconds, OTA cooldown stamp
	LastSighting time.Time
}

func main() {
	haWS := flag.String("ha-ws", "", "HA websocket URL")
	haREST := flag.String("ha-rest", "", "HA base URL for REST proof endpoints")
	tokenFile := flag.String("token-file", "", "long-lived HA token file")
	accepted := flag.String("accepted", "", "comma-separated MACs treated as accepted")
	publish := flag.Bool("publish", false, "actually publish OTA commands (default: log only)")
	rebootHost := flag.String("reboot-host", "", "wifi hostname to reboot once at start (panel subscribes nspanel/<hostname>/command; proves outbound path, no flash risk)")
	seconds := flag.Int("seconds", 300, "run duration")
	flag.Parse()
	if *haWS == "" || *haREST == "" || *tokenFile == "" {
		log.Fatal("usage: nspanel-manage -ha-ws wss://host/api/websocket -ha-rest https://host -token-file FILE")
	}
	tokBytes, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatalf("token: %v", err)
	}
	token := strings.TrimSpace(string(tokBytes))

	acc := map[string]bool{}
	for _, m := range strings.Split(*accepted, ",") {
		if s := topics.Safe(strings.TrimSpace(m)); s != "" {
			acc[s] = true
		}
	}

	// Served MD5s from the integration's own proof endpoints (same bytes the
	// panels download — no direct file access needed).
	served := fetchServed(*haREST, token)

	dialer := websocket.Dialer{HandshakeTimeout: 15 * time.Second,
		TLSClientConfig: &tls.Config{}}
	conn, _, err := dialer.Dial(*haWS, nil)
	if err != nil {
		log.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	var first map[string]any
	if err := conn.ReadJSON(&first); err != nil || first["type"] != "auth_required" {
		log.Fatalf("handshake: %v %v", first, err)
	}
	if err := conn.WriteJSON(map[string]any{"type": "auth", "access_token": token}); err != nil {
		log.Fatalf("auth: %v", err)
	}
	token = ""
	var auth map[string]any
	if err := conn.ReadJSON(&auth); err != nil || auth["type"] != "auth_ok" {
		log.Fatalf("auth failed: %v", auth)
	}
	log.Print("manage: authenticated; subscribing nspanel/#")
	if err := conn.WriteJSON(map[string]any{"id": 10, "type": "mqtt/subscribe", "topic": "nspanel/#"}); err != nil {
		log.Fatal(err)
	}

	panels := map[string]*panelState{} // key: topic_safe(mac)
	callID := 100
	if *rebootHost != "" {
		callID++
		body, _ := json.Marshal(map[string]string{"command": "reboot"})
		_ = conn.WriteJSON(map[string]any{
			"id": callID, "type": "call_service", "domain": "mqtt", "service": "publish",
			"service_data": map[string]any{"topic": topics.PanelTopic(*rebootHost, "command"), "payload": string(body)},
		})
		// Same bytes the Python manager and the UI path produce.
		fmt.Printf("manage: reboot sent to %s, waiting for re-register\n", topics.PanelTopic(*rebootHost, "command"))
	}
	deadline := time.Now().Add(time.Duration(*seconds) * time.Second)
	for time.Now().Before(deadline) {
		conn.SetReadDeadline(deadline)
		var m map[string]any
		if err := conn.ReadJSON(&m); err != nil {
			break
		}
		if m["type"] != "event" {
			continue
		}
		ev, _ := m["event"].(map[string]any)
		if ev == nil {
			continue
		}
		mtopic, _ := ev["topic"].(string)
		payload, _ := ev["payload"].(string)
		if mtopic == "" {
			continue
		}
		seg := topics.Segment(mtopic)
		nowMono := float64(time.Now().UnixNano()) / 1e9

		// Register requests carry MAC/hostname/checksums.
		if strings.HasSuffix(mtopic, "mqttmanager/command") {
			cmd := parseJSON(payload)
			if cmd["command"] == "register_request" {
				mac := topics.Safe(str3(cmd["mac_origin"], cmd["mac_address"], cmd["mac"]))
				host := str1(cmd["friendly_name"], cmd["wifi_hostname"])
				if mac == "" {
					continue
				}
				ps := panels[mac]
				if ps == nil {
					ps = &panelState{MAC: mac, Accepted: acc[mac]}
					panels[mac] = ps
				}
				if host != "" {
					ps.Hostname = host
				}
				ps.LastSighting = time.Now()
				rep := manager.NormalizeReport(map[string]string{
					"md5_firmware": str1(cmd["md5_firmware"]),
					"md5_littlefs": str1(cmd["md5_littlefs"], cmd["md5_data_file"]),
					"md5_tft_file": str1(cmd["md5_tft_file"], cmd["md5_tft_gui"]),
				})
				evaluate(conn, &callID, ps, rep, served, nowMono, *publish)
			}
			continue
		}
		// Status reports keep the registry fresh (segment is the hostname).
		if strings.HasSuffix(mtopic, "/status_report") || strings.HasSuffix(mtopic, "/status") {
			fmt.Printf("manage: sighting seg=%-16q topic=%s %d bytes\n", seg, mtopic, len(payload))
		}
	}
	fmt.Printf("manage: done, %d panels tracked, publishes %s\n", len(panels), onoff(*publish))
}

func evaluate(conn *websocket.Conn, callID *int, ps *panelState, rep map[string]string, served map[string]string, now float64, allowPublish bool) {
	if !ps.Accepted {
		fmt.Printf("manage: %-12s NOT accepted -> no OTA evaluation\n", ps.MAC)
		return
	}
	state := "online"
	if !manager.ShouldEvaluate(state, ps.LastTrigger, now) {
		fmt.Printf("manage: %-12s cooldown active -> skip\n", ps.MAC)
		return
	}
	model := manager.ModelKey(ps.Model)
	d := manager.DecideOTA(manager.OTARequest{
		Model:             model,
		ReportFirmwareMD5: rep["md5_firmware"],
		ReportLittlefsMD5: rep["md5_littlefs"],
		ReportTFTMD5:      rep["md5_tft_file"],
		CachedFirmwareMD5: served["firmware/"+model+"/firmware.bin"],
		CachedDataMD5:     served["firmware/"+model+"/data_file.bin"],
		CachedTFTMD5:      served["tft/"+manager.TFTFilename(ps.IsUS)],
		AutoTFTUpdates:    true,
	})
	ps.LastTrigger = now // stamp AFTER evaluation (never black out startup)
	fmt.Printf("manage: %-12s host=%-16q fw=%v tft=%v data_avail=%v publish=%v\n",
		ps.MAC, ps.Hostname, d.Firmware, d.TFT, d.DataAvailable, allowPublish)
	if !allowPublish {
		return
	}
	dest := topics.PanelTopic(firstNonEmpty(ps.Hostname, ps.MAC), "command")
	if d.Firmware {
		publishCmd(conn, callID, dest, "firmware_update")
	}
	if d.TFT {
		publishCmd(conn, callID, dest, "tft_update")
	}
}

func publishCmd(conn *websocket.Conn, callID *int, topic, command string) {
	*callID++
	body, _ := json.Marshal(map[string]string{"command": command})
	_ = conn.WriteJSON(map[string]any{
		"id": *callID, "type": "call_service", "domain": "mqtt", "service": "publish",
		"service_data": map[string]any{"topic": topic, "payload": string(body)},
	})
}

// fetchServed pulls served MD5s from firmware_status + checksum endpoints.
func fetchServed(rest, token string) map[string]string {
	out := map[string]string{}
	get := func(path string) map[string]any {
		req, _ := http.NewRequest("GET", rest+path, nil)
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return nil
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		var v map[string]any
		if err := json.Unmarshal(body, &v); err != nil {
			return nil
		}
		return v
	}
	if st := get("/nspanel_core/firmware_status"); st != nil {
		if sf, ok := st["served_firmware"].(map[string]any); ok {
			for _, v := range sf {
				if info, ok := v.(map[string]any); ok {
					md5, _ := info["md5"].(string)
					fn, _ := info["filename"].(string)
					if md5 != "" && fn != "" {
						out["firmware/"+fn] = md5
					}
				}
			}
		}
		if tf, ok := st["served_tft"].(map[string]any); ok {
			for _, v := range tf {
				if info, ok := v.(map[string]any); ok {
					if md5, ok := info["md5"].(string); ok {
						if fn, ok := info["filename"].(string); ok {
							out["tft/"+fn] = md5
						}
					}
				}
			}
		}
	}
	return out
}

func parseJSON(s string) map[string]any {
	var v map[string]any
	if err := json.Unmarshal([]byte(s), &v); err != nil {
		return map[string]any{}
	}
	return v
}

func str1(v ...any) string {
	for _, x := range v {
		if s, ok := x.(string); ok && s != "" {
			return s
		}
	}
	return ""
}

func str3(a, b, c any) string { return str1(a, b, c) }
func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}
func onoff(b bool) string {
	if b {
		return "ENABLED"
	}
	return "disabled (log-only)"
}
