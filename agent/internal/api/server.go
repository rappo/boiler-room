package api

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/rappo/boiler-room/agent/internal/games"
	"github.com/rappo/boiler-room/agent/internal/system"
)

// Server is the HTTP API server for the Boiler Room agent.
type Server struct {
	scanner    *games.Scanner
	sysInfo    *system.Info
	port       int
	deviceName string
	version    string
}

// NewServer creates a new API server.
func NewServer(scanner *games.Scanner, sysInfo *system.Info, port int, deviceName, version string) *Server {
	return &Server{
		scanner:    scanner,
		sysInfo:    sysInfo,
		port:       port,
		deviceName: deviceName,
		version:    version,
	}
}

// Start begins serving HTTP requests. Blocks until the server is stopped.
func (s *Server) Start() error {
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("GET /api/v1/status", s.handleStatus)
	mux.HandleFunc("GET /api/v1/games", s.handleGames)
	mux.HandleFunc("POST /api/v1/launch", s.handleLaunch)

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

// --- Handlers ---

type statusResponse struct {
	Version      string `json:"version"`
	State        string `json:"state"`
	DeviceName   string `json:"device_name"`
	DeviceID     string `json:"device_id"`
	UptimeSeconds int64 `json:"uptime_seconds"`
	GamingMode   bool   `json:"gaming_mode"`
	IPAddress    string `json:"ip_address,omitempty"`
	MACAddress   string `json:"mac_address,omitempty"`
	GameCount    int    `json:"game_count"`
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
	}

	s.writeJSON(w, http.StatusOK, resp)
}

func (s *Server) handleGames(w http.ResponseWriter, r *http.Request) {
	// Re-scan if requested
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

type launchRequest struct {
	Type   string `json:"type"`   // "game"
	Target string `json:"target"` // game name (fuzzy)
	AppID  string `json:"appid"`  // or exact AppID
}

type launchResponse struct {
	Status  string      `json:"status"`
	Game    *games.Game `json:"game,omitempty"`
	Message string      `json:"message,omitempty"`
}

func (s *Server) handleLaunch(w http.ResponseWriter, r *http.Request) {
	var req launchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	var game *games.Game
	var err error

	if req.AppID != "" {
		// Launch by AppID
		game, err = s.scanner.FindByAppID(req.AppID)
		if err != nil {
			s.writeJSON(w, http.StatusNotFound, launchResponse{
				Status:  "error",
				Message: err.Error(),
			})
			return
		}
		err = games.Launch(game.AppID)
	} else if req.Target != "" {
		// Launch by name (fuzzy match)
		game, err = games.LaunchByName(s.scanner, req.Target)
	} else {
		s.writeError(w, http.StatusBadRequest, "Must provide 'target' (name) or 'appid'")
		return
	}

	if err != nil {
		s.writeJSON(w, http.StatusNotFound, launchResponse{
			Status:  "error",
			Message: err.Error(),
		})
		return
	}

	log.Printf("Launched game: %s (AppID: %s)", game.Name, game.AppID)

	s.writeJSON(w, http.StatusOK, launchResponse{
		Status: "launching",
		Game:   game,
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
