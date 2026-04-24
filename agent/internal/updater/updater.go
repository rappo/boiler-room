package updater

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// Release represents a GitHub/Forgejo release.
type Release struct {
	TagName string  `json:"tag_name"`
	Assets  []Asset `json:"assets"`
}

// Asset represents a release binary.
type Asset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

// Updater checks for and applies agent updates.
type Updater struct {
	repoURL        string // e.g., "https://github.com/rappo/boiler-room"
	currentVersion string
	binaryPath     string
	checkInterval  time.Duration
	client         *http.Client
}

// NewUpdater creates a new self-updater.
func NewUpdater(repoURL, currentVersion string) *Updater {
	binaryPath, _ := os.Executable()
	return &Updater{
		repoURL:        strings.TrimRight(repoURL, "/"),
		currentVersion: currentVersion,
		binaryPath:     binaryPath,
		checkInterval:  6 * time.Hour,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// CheckForUpdate queries the releases API and returns the latest version, or empty if current.
func (u *Updater) CheckForUpdate() (string, error) {
	apiURL := u.repoURL + "/releases/latest"
	// Try GitHub API first, then raw endpoint
	if strings.Contains(u.repoURL, "github.com") {
		apiURL = strings.Replace(u.repoURL, "github.com", "api.github.com/repos", 1) + "/releases/latest"
	}

	req, _ := http.NewRequest("GET", apiURL, nil)
	req.Header.Set("Accept", "application/json")

	resp, err := u.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to check for updates: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", fmt.Errorf("update check returned %d", resp.StatusCode)
	}

	var release Release
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return "", fmt.Errorf("failed to parse release: %w", err)
	}

	latestVersion := strings.TrimPrefix(release.TagName, "v")
	if latestVersion == u.currentVersion {
		return "", nil // Up to date
	}

	return latestVersion, nil
}

// Update downloads and applies the latest release.
func (u *Updater) Update() error {
	apiURL := u.repoURL + "/releases/latest"
	if strings.Contains(u.repoURL, "github.com") {
		apiURL = strings.Replace(u.repoURL, "github.com", "api.github.com/repos", 1) + "/releases/latest"
	}

	req, _ := http.NewRequest("GET", apiURL, nil)
	req.Header.Set("Accept", "application/json")

	resp, err := u.client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to fetch release: %w", err)
	}
	defer resp.Body.Close()

	var release Release
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return err
	}

	// Find the right binary for this architecture
	binaryName := fmt.Sprintf("boiler-room-agent-linux-%s", runtime.GOARCH)
	var downloadURL string
	for _, asset := range release.Assets {
		if strings.Contains(asset.Name, binaryName) {
			downloadURL = asset.BrowserDownloadURL
			break
		}
	}

	if downloadURL == "" {
		return fmt.Errorf("no binary found for %s in release %s", runtime.GOARCH, release.TagName)
	}

	// Download to a temp file
	tmpPath := u.binaryPath + ".new"
	log.Printf("Downloading update from %s", downloadURL)

	dlResp, err := u.client.Get(downloadURL)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}
	defer dlResp.Body.Close()

	tmpFile, err := os.Create(tmpPath)
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}

	if _, err := io.Copy(tmpFile, dlResp.Body); err != nil {
		tmpFile.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("download incomplete: %w", err)
	}
	tmpFile.Close()

	// Make executable
	if err := os.Chmod(tmpPath, 0755); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to chmod: %w", err)
	}

	// Replace the old binary
	oldPath := u.binaryPath + ".old"
	os.Remove(oldPath) // Clean up any previous .old file

	if err := os.Rename(u.binaryPath, oldPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to backup old binary: %w", err)
	}

	if err := os.Rename(tmpPath, u.binaryPath); err != nil {
		// Rollback
		os.Rename(oldPath, u.binaryPath)
		return fmt.Errorf("failed to install new binary: %w", err)
	}

	// Clean up old binary
	os.Remove(oldPath)

	log.Printf("Update to %s complete, restarting via systemd...", release.TagName)

	// Restart via systemd (doesn't kill the current process immediately)
	exec.Command("systemctl", "--user", "restart", "boiler-room").Start()

	return nil
}

// StartPeriodicCheck begins background update checks.
func (u *Updater) StartPeriodicCheck() {
	go func() {
		// Wait a bit after startup before first check
		time.Sleep(5 * time.Minute)

		ticker := time.NewTicker(u.checkInterval)
		defer ticker.Stop()

		for {
			newVersion, err := u.CheckForUpdate()
			if err != nil {
				log.Printf("Update check failed: %v", err)
			} else if newVersion != "" {
				log.Printf("Update available: v%s → v%s", u.currentVersion, newVersion)
				// Don't auto-update — just log. The HA integration can trigger the update.
			}

			<-ticker.C
		}
	}()
}

// Info returns the current update status for the API.
func (u *Updater) Info() map[string]interface{} {
	info := map[string]interface{}{
		"current_version": u.currentVersion,
		"binary_path":     u.binaryPath,
	}

	newVersion, err := u.CheckForUpdate()
	if err != nil {
		info["update_check"] = "failed"
		info["error"] = err.Error()
	} else if newVersion != "" {
		info["update_available"] = true
		info["latest_version"] = newVersion
	} else {
		info["update_available"] = false
	}

	return info
}
