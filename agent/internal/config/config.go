package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Config holds all agent configuration
type Config struct {
	DeviceName string `yaml:"device_name"`
	APIPort    int    `yaml:"api_port"`
	LogLevel   string `yaml:"log_level"`

	// Plugin settings (optional — plugins work without config)
	JellyfinURL      string `yaml:"jellyfin_url"`
	JellyfinAPIKey   string `yaml:"jellyfin_api_key"`
	PreferredBrowser string `yaml:"preferred_browser"` // For YouTube plugin: "firefox", "chrome", or Flatpak ID

	// Update settings
	RepoURL string `yaml:"repo_url"` // GitHub/Forgejo repo URL for self-updates
}

// DefaultConfig returns a config with sensible defaults
func DefaultConfig() *Config {
	hostname, _ := os.Hostname()
	if hostname == "" {
		hostname = "SteamOS Device"
	}
	return &Config{
		DeviceName: hostname,
		APIPort:    9451,
		LogLevel:   "info",
	}
}

// Load reads config from the standard location, falling back to defaults.
// Config path: ~/.config/boiler-room/config.yaml
func Load() *Config {
	cfg := DefaultConfig()

	homeDir, err := os.UserHomeDir()
	if err != nil {
		return cfg
	}

	configPath := filepath.Join(homeDir, ".config", "boiler-room", "config.yaml")
	data, err := os.ReadFile(configPath)
	if err != nil {
		// No config file — use defaults, which is fine
		return cfg
	}

	if err := yaml.Unmarshal(data, cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to parse %s: %v (using defaults)\n", configPath, err)
		return DefaultConfig()
	}

	// Ensure critical defaults
	if cfg.APIPort == 0 {
		cfg.APIPort = 9451
	}
	if cfg.DeviceName == "" {
		cfg.DeviceName = "SteamOS Device"
	}

	return cfg
}

// ConfigDir returns the path to the config directory
func ConfigDir() string {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(homeDir, ".config", "boiler-room")
}
