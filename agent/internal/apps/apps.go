package apps

import (
	"encoding/json"
	"os"
	"os/exec"
	"sort"
	"strings"
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
	cmd := exec.Command("flatpak", "run", appID)
	cmd.Env = append(cmd.Environ(), getDisplayEnv()...)
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}

// getDisplayEnv discovers display-related environment variables from the
// running desktop session (gamescope, KDE, etc.) by reading /proc.
// Returns env vars like DISPLAY=:0, WAYLAND_DISPLAY=wayland-1, etc.
func getDisplayEnv() []string {
	// Try to find a session process (gamescope, kwin, or steam)
	targets := []string{"gamescope", "kwin_wayland", "steam"}
	for _, target := range targets {
		out, err := exec.Command("pgrep", "-xo", target).Output()
		if err != nil {
			continue
		}
		pid := strings.TrimSpace(string(out))
		if pid == "" {
			continue
		}

		envData, err := os.ReadFile("/proc/" + pid + "/environ")
		if err != nil {
			continue
		}

		var displayEnv []string
		for _, entry := range strings.Split(string(envData), "\x00") {
			for _, prefix := range []string{
				"DISPLAY=",
				"WAYLAND_DISPLAY=",
				"XDG_RUNTIME_DIR=",
				"DBUS_SESSION_BUS_ADDRESS=",
			} {
				if strings.HasPrefix(entry, prefix) {
					displayEnv = append(displayEnv, entry)
				}
			}
		}
		if len(displayEnv) > 0 {
			return displayEnv
		}
	}
	return nil
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
