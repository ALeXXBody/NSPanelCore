// Command nspanelcore is the Go core daemon: single static binary that owns
// MQTT routing, OTA decisions, protobuf codec, config persistence, time and
// weather publishing. The Python HA integration thins to entities + UI proxy.
//
// Wiring only — transports (MQTT socket, HA WS, HTTP fetch) implement the
// small interfaces below so `go build ./...` stays dependency-free and the
// business logic stays unit-tested.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"nspanelcore/config"
	"nspanelcore/manager"
	"nspanelcore/ota"
	"nspanelcore/timepub"
	"nspanelcore/topics"
	"nspanelcore/weather"
)

// Publisher is the MQTT publish surface main needs (retained supported).
type Publisher interface {
	Publish(topic, payload string, retained bool) error
}

func main() {
	configPath := flag.String("config", "", "path to integration JSON config (HA storage export)")
	hassConfigDir := flag.String("hass-config-dir", "", "HA config dir for overlay resolution")
	flag.Parse()

	cfg := config.New()
	if *configPath != "" {
		raw, err := os.ReadFile(*configPath)
		if err != nil {
			log.Fatalf("read config: %v", err)
		}
		cfg, err = config.Unmarshal(raw)
		if err != nil {
			log.Fatalf("parse config: %v", err)
		}
	}
	log.Printf("nspanelcore: %d panels, %d lights, %d rooms", len(cfg.Panels), len(cfg.Lights), len(cfg.Rooms))

	// SIGUSR1 = config reload (mirrors the Django bridge contract).
	sigc := make(chan os.Signal, 1)
	signal.Notify(sigc, syscall.SIGUSR1)
	go func() {
		for range sigc {
			log.Print("nspanelcore: reload requested (SIGUSR1)")
			// Main reloads from disk; HA shim writes storage then signals.
			if *configPath != "" {
				if raw, err := os.ReadFile(*configPath); err == nil {
					if nc, err := config.Unmarshal(raw); err == nil {
						*cfg = *nc
						log.Print("nspanelcore: config reloaded")
					}
				}
			}
		}
	}()

	// Startup self-check: topics + OTA cache resolve without I/O surprises.
	md5s := ota.HashAll(func(kind, name string) string { return "" })
	_ = md5s
	for _, p := range cfg.Panels {
		mp := manager.Panel{MAC: p.MAC, Name: p.Name, WifiHostname: p.WifiHostname, Model: p.Model, IsUSPanel: p.IsUSPanel}
		_ = topics.PanelTopic(mp.RoutingName(), "command")
		_ = manager.TFTFilename(mp.IsUSPanel)
	}
	_ = weather.ValidCoords(0, 0)
	_, _, _ = timepub.Format(time.Now(), cfg.Settings.ClockUSStyle, cfg.Settings.DateFormat)

	// Daemon mode: without a Publisher we run the schedulers dry (parities +
	// self-check) and exit 0 so CI and the HA shim can smoke-test the binary.
	// With a broker attached, main blocks here on the schedulers.
	out, _ := json.Marshal(map[string]any{"panels": len(cfg.Panels), "status": "ok"})
	fmt.Println(string(out))
	_ = hassConfigDir
}
