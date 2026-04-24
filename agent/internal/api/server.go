package api

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/rappo/boiler-room/agent/internal/apps"
	"github.com/rappo/boiler-room/agent/internal/games"
	"github.com/rappo/boiler-room/agent/internal/plugins"
	"github.com/rappo/boiler-room/agent/internal/system"
)

// Server is the HTTP API server for the Boiler Room agent.
type Server struct {
	scanner       *games.Scanner
	sysInfo       *system.Info
	flatpaks      []apps.App
	shortcuts     []games.Shortcut
	pluginManager *plugins.Manager
	port          int
	deviceName    string
	version       string
}

// NewServer creates a new API server.
func NewServer(scanner *games.Scanner, sysInfo *system.Info, pluginMgr *plugins.Manager, port int, deviceName, version string) *Server {
	s := &Server{
		scanner:       scanner,
		sysInfo:       sysInfo,
		pluginManager: pluginMgr,
		port:          port,
		deviceName:    deviceName,
		version:       version,
	}

	// Initial Flatpak scan
	flatpakList, err := apps.ScanFlatpaks()
	if err != nil {
		log.Printf("Warning: Flatpak scan failed: %v", err)
	} else {
		s.flatpaks = flatpakList
		log.Printf("Found %d Flatpak apps", len(flatpakList))
	}

	// Initial Non-Steam shortcuts scan
	shortcutList, err := games.ScanShortcuts()
	if err != nil {
		log.Printf("Warning: Non-Steam shortcut scan failed: %v", err)
	} else {
		s.shortcuts = shortcutList
		log.Printf("Found %d Non-Steam shortcuts", len(shortcutList))
	}

	return s
}

// Start begins serving HTTP requests. Blocks until the server is stopped.
func (s *Server) Start() error {
	mux := http.NewServeMux()

	// Phase 1: Core
	mux.HandleFunc("GET /api/v1/status", s.handleStatus)
	mux.HandleFunc("GET /api/v1/games", s.handleGames)
	mux.HandleFunc("POST /api/v1/launch", s.handleLaunch)

	// Phase 2: Apps & Shortcuts
	mux.HandleFunc("GET /api/v1/apps", s.handleApps)
	mux.HandleFunc("GET /api/v1/shortcuts", s.handleShortcuts)

	// Phase 2: Artwork
	mux.HandleFunc("GET /api/v1/games/{appid}/artwork/{type}", s.handleArtwork)

	// Phase 2: System controls
	mux.HandleFunc("GET /api/v1/system/sensors", s.handleSensors)
	mux.HandleFunc("POST /api/v1/system/volume", s.handleVolume)
	mux.HandleFunc("POST /api/v1/system/power", s.handlePower)

	// Phase 2: Plugins
	mux.HandleFunc("GET /api/v1/plugins", s.handlePluginList)
	mux.HandleFunc("POST /api/v1/plugins/{name}/action", s.handlePluginAction)

	// Health check
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	handler := s.corsMiddleware(s.loggingMiddleware(mux))

	addr := fmt.Sprintf(":%d", s.port)
	log.Printf("API server listening on %s", addr)

	server := &http.Server{
		Addr:         addr,
		Handler:      handler,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	return server.ListenAndServe()
}

// --- Status ---

type statusResponse struct {
	Version       string `json:"version"`
	State         string `json:"state"`
	DeviceName    string `json:"device_name"`
	DeviceID      string `json:"device_id"`
	UptimeSeconds int64  `json:"uptime_seconds"`
	GamingMode    bool   `json:"gaming_mode"`
	IPAddress     string `json:"ip_address,omitempty"`
	MACAddress    string `json:"mac_address,omitempty"`
	GameCount     int    `json:"game_count"`
	AppCount      int    `json:"app_count"`
	ShortcutCount int    `json:"shortcut_count"`
	PluginCount   int    `json:"plugin_count"`
}

func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	resp := statusResponse{
		Version:       s.version,
		State:         "idle",
		DeviceName:    s.deviceName,
		DeviceID:      s.sysInfo.DeviceID,
		UptimeSeconds: s.sysInfo.UptimeSeconds(),
		GamingMode:    system.IsGamingMode(),
		IPAddress:     s.sysInfo.IPAddress,
		MACAddress:    s.sysInfo.MacAddress,
		GameCount:     len(s.scanner.GetCached()),
		AppCount:      len(s.flatpaks),
		ShortcutCount: len(s.shortcuts),
		PluginCount:   len(s.pluginManager.List()),
	}

	s.writeJSON(w, http.StatusOK, resp)
}

// --- Games ---

func (s *Server) handleGames(w http.ResponseWriter, r *http.Request) {
	if r.URL.Query().Get("refresh") == "true" {
		if _, err := s.scanner.Scan(); err != nil {
			s.writeError(w, http.StatusInternalServerError, "Failed to scan games: "+err.Error())
			return
		}
	}

	gameList := s.scanner.GetCached()
	if gameList == nil {
		gameList = []games.Game{}
	}

	s.writeJSON(w, http.StatusOK, gameList)
}

// --- Apps (Flatpaks) ---

func (s *Server) handleApps(w http.ResponseWriter, r *http.Request) {
	if r.URL.Query().Get("refresh") == "true" {
		flatpakList, err := apps.ScanFlatpaks()
		if err != nil {
			s.writeError(w, http.StatusInternalServerError, "Failed to scan apps: "+err.Error())
			return
		}
		s.flatpaks = flatpakList
	}

	appList := s.flatpaks
	if appList == nil {
		appList = []apps.App{}
	}

	s.writeJSON(w, http.StatusOK, appList)
}

// --- Non-Steam Shortcuts ---

func (s *Server) handleShortcuts(w http.ResponseWriter, r *http.Request) {
	if r.URL.Query().Get("refresh") == "true" {
		shortcutList, err := games.ScanShortcuts()
		if err != nil {
			s.writeError(w, http.StatusInternalServerError, "Failed to scan shortcuts: "+err.Error())
			return
		}
		s.shortcuts = shortcutList
	}

	list := s.shortcuts
	if list == nil {
		list = []games.Shortcut{}
	}

	s.writeJSON(w, http.StatusOK, list)
}

// --- Artwork ---

func (s *Server) handleArtwork(w http.ResponseWriter, r *http.Request) {
	appID := r.PathValue("appid")
	artType := r.PathValue("type")

	if appID == "" || artType == "" {
		s.writeError(w, http.StatusBadRequest, "Must provide appid and artwork type")
		return
	}

	path, err := games.GetArtworkPath(appID, games.ArtworkType(artType))
	if err != nil {
		s.writeError(w, http.StatusNotFound, "Artwork not found: "+err.Error())
		return
	}

	contentType := games.DetectContentType(path)
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Cache-Control", "public, max-age=86400") // Cache 24 hours

	file, err := os.Open(path)
	if err != nil {
		s.writeError(w, http.StatusInternalServerError, "Failed to read artwork")
		return
	}
	defer file.Close()

	http.ServeFile(w, r, path)
}

// --- Launch ---

type launchRequest struct {
	Type   string `json:"type"`   // "game", "app", "url"
	Target string `json:"target"` // game/app name (fuzzy)
	AppID  string `json:"appid"`  // exact Steam AppID or Flatpak ID
	URL    string `json:"url"`    // URL to open (for type "url")
}

type launchResponse struct {
	Status  string      `json:"status"`
	Game    *games.Game `json:"game,omitempty"`
	App     *apps.App   `json:"app,omitempty"`
	Message string      `json:"message,omitempty"`
}

func (s *Server) handleLaunch(w http.ResponseWriter, r *http.Request) {
	var req launchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	switch req.Type {
	case "game", "":
		s.handleLaunchGame(w, req)
	case "app":
		s.handleLaunchApp(w, req)
	case "url":
		s.handleLaunchURL(w, req)
	default:
		s.writeError(w, http.StatusBadRequest, "Invalid launch type: "+req.Type)
	}
}

func (s *Server) handleLaunchGame(w http.ResponseWriter, req launchRequest) {
	var game *games.Game
	var err error

	if req.AppID != "" {
		game, err = s.scanner.FindByAppID(req.AppID)
		if err != nil {
			s.writeJSON(w, http.StatusNotFound, launchResponse{Status: "error", Message: err.Error()})
			return
		}
		err = games.Launch(game.AppID)
	} else if req.Target != "" {
		game, err = games.LaunchByName(s.scanner, req.Target)
	} else {
		s.writeError(w, http.StatusBadRequest, "Must provide 'target' (name) or 'appid'")
		return
	}

	if err != nil {
		s.writeJSON(w, http.StatusNotFound, launchResponse{Status: "error", Message: err.Error()})
		return
	}

	log.Printf("Launched game: %s (AppID: %s)", game.Name, game.AppID)
	s.writeJSON(w, http.StatusOK, launchResponse{Status: "launching", Game: game})
}

func (s *Server) handleLaunchApp(w http.ResponseWriter, req launchRequest) {
	var appID string

	if req.AppID != "" {
		appID = req.AppID
	} else if req.Target != "" {
		// Check well-known apps first
		if id, ok := apps.WellKnownApps[req.Target]; ok {
			appID = id
		} else {
			// Fuzzy match against installed Flatpaks
			found := apps.FindFlatpakByName(s.flatpaks, req.Target)
			if found == nil {
				s.writeJSON(w, http.StatusNotFound, launchResponse{
					Status: "error", Message: fmt.Sprintf("No app matching '%s' found", req.Target),
				})
				return
			}
			appID = found.ID
		}
	} else {
		s.writeError(w, http.StatusBadRequest, "Must provide 'target' (name) or 'appid'")
		return
	}

	if err := apps.LaunchFlatpak(appID); err != nil {
		s.writeJSON(w, http.StatusInternalServerError, launchResponse{
			Status: "error", Message: "Failed to launch app: " + err.Error(),
		})
		return
	}

	log.Printf("Launched app: %s", appID)
	s.writeJSON(w, http.StatusOK, launchResponse{
		Status: "launching",
		App:    &apps.App{ID: appID, Name: req.Target, Type: "flatpak"},
	})
}

func (s *Server) handleLaunchURL(w http.ResponseWriter, req launchRequest) {
	if req.URL == "" {
		s.writeError(w, http.StatusBadRequest, "Must provide 'url'")
		return
	}

	if err := apps.LaunchURL(req.URL, ""); err != nil {
		s.writeJSON(w, http.StatusInternalServerError, launchResponse{
			Status: "error", Message: "Failed to open URL: " + err.Error(),
		})
		return
	}

	log.Printf("Opened URL: %s", req.URL)
	s.writeJSON(w, http.StatusOK, launchResponse{Status: "launching", Message: "URL opened"})
}

// --- System Sensors ---

type sensorsResponse struct {
	CPUTemp         float64 `json:"cpu_temp"`
	GPUTemp         float64 `json:"gpu_temp"`
	Volume          int     `json:"volume"`
	BatteryLevel    int     `json:"battery_level"`    // -1 if no battery
	BatteryCharging bool    `json:"battery_charging"`
}

func (s *Server) handleSensors(w http.ResponseWriter, r *http.Request) {
	cpuTemp, _ := system.CPUTemp()
	gpuTemp, _ := system.GPUTemp()
	volume, _ := system.VolumeGet()

	resp := sensorsResponse{
		CPUTemp:         cpuTemp,
		GPUTemp:         gpuTemp,
		Volume:          volume,
		BatteryLevel:    system.BatteryLevel(),
		BatteryCharging: system.BatteryCharging(),
	}

	s.writeJSON(w, http.StatusOK, resp)
}

// --- Volume ---

type volumeRequest struct {
	Level *int  `json:"level"` // 0-100, nil = get current
	Mute  *bool `json:"mute"`
}

func (s *Server) handleVolume(w http.ResponseWriter, r *http.Request) {
	var req volumeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	if req.Mute != nil {
		if err := system.VolumeMute(*req.Mute); err != nil {
			s.writeError(w, http.StatusInternalServerError, "Failed to set mute: "+err.Error())
			return
		}
	}

	if req.Level != nil {
		if err := system.VolumeSet(*req.Level); err != nil {
			s.writeError(w, http.StatusInternalServerError, "Failed to set volume: "+err.Error())
			return
		}
	}

	currentVol, _ := system.VolumeGet()
	s.writeJSON(w, http.StatusOK, map[string]int{"volume": currentVol})
}

// --- Power ---

type powerRequest struct {
	Action string `json:"action"` // "suspend", "shutdown", "reboot"
}

func (s *Server) handlePower(w http.ResponseWriter, r *http.Request) {
	var req powerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	s.writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "action": req.Action})

	// Execute after response is sent
	go func() {
		time.Sleep(500 * time.Millisecond)
		switch req.Action {
		case "suspend":
			log.Println("Suspending system...")
			system.Suspend()
		case "shutdown":
			log.Println("Shutting down system...")
			system.Shutdown()
		case "reboot":
			log.Println("Rebooting system...")
			system.Reboot()
		}
	}()
}

// --- Plugins ---

func (s *Server) handlePluginList(w http.ResponseWriter, r *http.Request) {
	list := s.pluginManager.List()
	if list == nil {
		list = []plugins.PluginInfo{}
	}
	s.writeJSON(w, http.StatusOK, list)
}

type pluginActionRequest struct {
	Action string                 `json:"action"`
	Params map[string]interface{} `json:"params"`
}

func (s *Server) handlePluginAction(w http.ResponseWriter, r *http.Request) {
	pluginName := r.PathValue("name")

	var req pluginActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	if req.Action == "" {
		s.writeError(w, http.StatusBadRequest, "Must provide 'action'")
		return
	}

	result, err := s.pluginManager.HandleAction(pluginName, req.Action, req.Params)
	if err != nil {
		s.writeJSON(w, http.StatusBadRequest, map[string]string{
			"status":  "error",
			"message": err.Error(),
		})
		return
	}

	s.writeJSON(w, http.StatusOK, map[string]interface{}{
		"status": "ok",
		"result": result,
	})
}

// --- Middleware ---

func (s *Server) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s %s", r.Method, r.URL.Path, time.Since(start))
	})
}

func (s *Server) corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

// --- Helpers ---

func (s *Server) writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func (s *Server) writeError(w http.ResponseWriter, status int, msg string) {
	s.writeJSON(w, status, map[string]string{"status": "error", "message": msg})
}
