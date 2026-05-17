package main

import (
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/rappo/boiler-room/agent/internal/api"
	"github.com/rappo/boiler-room/agent/internal/config"
	"github.com/rappo/boiler-room/agent/internal/discovery"
	"github.com/rappo/boiler-room/agent/internal/games"
	"github.com/rappo/boiler-room/agent/internal/plugins"
	"github.com/rappo/boiler-room/agent/internal/plugins/jellyfin"
	"github.com/rappo/boiler-room/agent/internal/plugins/youtube"
	"github.com/rappo/boiler-room/agent/internal/system"
	"github.com/rappo/boiler-room/agent/internal/updater"
)

var version = "0.4.0"

func main() {
	showVersion := flag.Bool("version", false, "Print version and exit")
	portOverride := flag.Int("port", 0, "Override API port")
	flag.Parse()

	if *showVersion {
		fmt.Printf("boiler-room-agent v%s\n", version)
		os.Exit(0)
	}

	log.SetFlags(log.Ldate | log.Ltime | log.Lshortfile)
	log.Printf("🔥 Boiler Room Agent v%s starting...", version)

	// Load config (auto-defaults if no config file exists)
	cfg := config.Load()
	if *portOverride > 0 {
		cfg.APIPort = *portOverride
	}

	// Gather system info
	sysInfo := system.NewInfo()
	log.Printf("Device ID: %s", sysInfo.DeviceID)
	log.Printf("Device Name: %s", cfg.DeviceName)
	log.Printf("IP Address: %s", sysInfo.IPAddress)
	log.Printf("MAC Address: %s", sysInfo.MacAddress)

	// Scan for installed games
	scanner := games.NewScanner()
	log.Printf("Library paths: %v", scanner.LibraryPaths())

	gameList, err := scanner.Scan()
	if err != nil {
		log.Printf("Warning: game scan failed: %v", err)
	} else {
		log.Printf("Found %d installed games", len(gameList))
	}

	// Scan for Non-Steam shortcuts
	shortcuts, err := games.ScanShortcuts()
	if err != nil {
		log.Printf("Warning: Non-Steam shortcut scan failed: %v", err)
	} else {
		log.Printf("Found %d Non-Steam shortcuts", len(shortcuts))
	}

	// Initialize plugin system
	pluginMgr := plugins.NewManager()

	// Register Jellyfin plugin (only if configured)
	if cfg.JellyfinURL != "" && cfg.JellyfinAPIKey != "" {
		jf := jellyfin.NewPlugin(cfg.JellyfinURL, cfg.JellyfinAPIKey)
		if err := pluginMgr.Register(jf); err != nil {
			log.Printf("Warning: failed to register Jellyfin plugin: %v", err)
		}
	} else {
		log.Printf("Jellyfin plugin: not configured (set jellyfin_url and jellyfin_api_key in config)")
	}

	// YouTube plugin is always available (no config needed)
	yt := youtube.NewPlugin(cfg.PreferredBrowser)
	if err := pluginMgr.Register(yt); err != nil {
		log.Printf("Warning: failed to register YouTube plugin: %v", err)
	}

	// Initialize self-updater
	upd := updater.NewUpdater(cfg.RepoURL, version)
	upd.StartPeriodicCheck()

	// Initialize power state tracker with DBus listener
	powerState := system.NewPowerState(nil) // callback set after server creation
	if err := powerState.StartDBusListener(); err != nil {
		log.Printf("Warning: DBus power state listener failed: %v (power state detection disabled)", err)
	}

	// Start mDNS advertisement
	stopMDNS, err := discovery.Advertise(cfg.DeviceName, cfg.APIPort, sysInfo.DeviceID, version)
	if err != nil {
		log.Printf("Warning: mDNS advertisement failed: %v (discovery disabled)", err)
	} else {
		defer stopMDNS()
	}

	// Start HTTP API server (blocks)
	server := api.NewServer(scanner, sysInfo, pluginMgr, upd, powerState, cfg.APIPort, cfg.DeviceName, version)
	log.Fatal(server.Start())
}
