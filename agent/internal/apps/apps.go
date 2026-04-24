package apps

import (
	"encoding/json"
	"log"
	"os"
	"os/exec"
	"sort"
	"strings"
	"syscall"
)

// App represents an installed non-Steam application (Flatpak, etc.)
type App struct {
	ID          string `json:"id"`           // e.g., "com.github.iwalton3.jellyfin-media-player"
	Name        string `json:"name"`         // e.g., "Jellyfin Media Player"
	Type        string `json:"type"`         // "flatpak"
	Description string `json:"description"`  // Short description
	Version     string `json:"version"`
}

// ScanFlatpaks discovers all installed Flatpak applications.
// No manual config needed — uses `flatpak list` directly.
func ScanFlatpaks() ([]App, error) {
	// flatpak list --app --columns=application,name,description,version
	out, err := exec.Command(
		"flatpak", "list", "--app",
		"--columns=application,name,description,version",
	).Output()
	if err != nil {
		return nil, err
	}

	var apps []App
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 4)
		if len(parts) < 2 {
			continue
		}
		app := App{
			ID:   strings.TrimSpace(parts[0]),
			Name: strings.TrimSpace(parts[1]),
			Type: "flatpak",
		}
		if len(parts) > 2 {
			app.Description = strings.TrimSpace(parts[2])
		}
		if len(parts) > 3 {
			app.Version = strings.TrimSpace(parts[3])
		}
		apps = append(apps, app)
	}

	sort.Slice(apps, func(i, j int) bool {
		return strings.ToLower(apps[i].Name) < strings.ToLower(apps[j].Name)
	})

	return apps, nil
}

// LaunchFlatpak starts a Flatpak application by its application ID.
// GUI apps need display environment variables that the systemd service
// doesn't have. We discover them from the running desktop session.
func LaunchFlatpak(appID string) error {
	displayEnv := getDisplayEnv()
	log.Printf("LaunchFlatpak(%s): injecting display env: %v", appID, displayEnv)

	cmd := exec.Command("flatpak", "run", appID)
	cmd.Env = append(os.Environ(), displayEnv...)
	if err := cmd.Start(); err != nil {
		log.Printf("LaunchFlatpak(%s): Start() failed: %v", appID, err)
		return err
	}
	go func() {
		if err := cmd.Wait(); err != nil {
			log.Printf("LaunchFlatpak(%s): process exited with error: %v", appID, err)
		}
	}()
	return nil
}

// getDisplayEnv discovers display-related environment variables from the
// running desktop session by reading /proc.
//
// Strategy: scan all user-owned processes for WAYLAND_DISPLAY. If found,
// use that process's env. If no Wayland session is found, fall back to
// known process names (gamescope, steam) for X11 DISPLAY.
func getDisplayEnv() []string {
	wantedPrefixes := []string{
		"DISPLAY=",
		"WAYLAND_DISPLAY=",
		"XDG_RUNTIME_DIR=",
		"DBUS_SESSION_BUS_ADDRESS=",
		"XAUTHORITY=",
	}

	uid := os.Getuid()
	var bestEnv []string

	// Scan /proc for any process with WAYLAND_DISPLAY
	procEntries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}

	for _, entry := range procEntries {
		if !entry.IsDir() {
			continue
		}
		// Only look at numeric PIDs
		pid := entry.Name()
		if pid[0] < '0' || pid[0] > '9' {
			continue
		}

		// Check if it's our process (same UID)
		info, err := entry.Info()
		if err != nil {
			continue
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || stat.Uid != uint32(uid) {
			continue
		}

		envData, err := os.ReadFile("/proc/" + pid + "/environ")
		if err != nil {
			continue
		}

		var displayEnv []string
		hasWayland := false
		for _, e := range strings.Split(string(envData), "\x00") {
			for _, prefix := range wantedPrefixes {
				if strings.HasPrefix(e, prefix) {
					displayEnv = append(displayEnv, e)
					if prefix == "WAYLAND_DISPLAY=" {
						hasWayland = true
					}
				}
			}
		}

		// Found WAYLAND_DISPLAY — this is the best source, use it
		if hasWayland {
			return displayEnv
		}

		// Track best fallback (most env vars found)
		if len(displayEnv) > len(bestEnv) {
			bestEnv = displayEnv
		}
	}

	return bestEnv
}

// LaunchURL opens a URL in the default browser or a specified Flatpak browser.
func LaunchURL(url string, browser string) error {
	var cmd *exec.Cmd
	if browser != "" {
		// Use a specific Flatpak browser
		cmd = exec.Command("flatpak", "run", browser, url)
	} else {
		// Use xdg-open (system default)
		cmd = exec.Command("xdg-open", url)
	}

	cmd.Env = append(cmd.Environ(), getDisplayEnv()...)
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}

// FindFlatpakByName does case-insensitive matching against installed Flatpaks.
func FindFlatpakByName(apps []App, query string) *App {
	query = strings.ToLower(strings.TrimSpace(query))

	// Exact match
	for i := range apps {
		if strings.ToLower(apps[i].Name) == query {
			return &apps[i]
		}
	}

	// Substring match
	for i := range apps {
		if strings.Contains(strings.ToLower(apps[i].Name), query) {
			return &apps[i]
		}
	}

	return nil
}

// WellKnownApps maps common names to Flatpak IDs for voice commands.
// This allows "open jellyfin" to match even without fuzzy search.
var WellKnownApps = map[string]string{
	"jellyfin":     "com.github.iwalton3.jellyfin-media-player",
	"firefox":      "org.mozilla.firefox",
	"chrome":       "com.google.Chrome",
	"chromium":     "org.chromium.Chromium",
	"spotify":      "com.spotify.Client",
	"discord":      "com.discordapp.Discord",
	"vlc":          "org.videolan.VLC",
	"kodi":         "tv.kodi.Kodi",
	"retroarch":    "org.libretro.RetroArch",
	"moonlight":    "com.moonlight_stream.Moonlight",
	"bottles":      "com.usebottles.bottles",
	"heroic":       "com.heroicgameslauncher.hgl",
	"lutris":       "net.lutris.Lutris",
}

// ToJSON serializes apps to JSON (for caching)
func ToJSON(apps []App) ([]byte, error) {
	return json.Marshal(apps)
}
