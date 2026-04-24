package games

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ArtworkType represents the type of game artwork available.
type ArtworkType string

const (
	ArtworkGrid   ArtworkType = "grid"   // 600x900 portrait grid image
	ArtworkHero   ArtworkType = "hero"   // 1920x620 wide hero banner
	ArtworkLogo   ArtworkType = "logo"   // Transparent logo
	ArtworkIcon   ArtworkType = "icon"   // Small square icon
	ArtworkHeader ArtworkType = "header" // 460x215 header capsule
)

// GetArtworkPath returns the local filesystem path for a game's artwork.
// Steam caches artwork in: ~/.steam/steam/appcache/librarycache/
// File naming convention: <appid>_<type>.<ext>
// Types: library_600x900 (grid), library_hero, logo, icon, header
func GetArtworkPath(appID string, artType ArtworkType) (string, error) {
	cacheDir, err := findLibraryCache()
	if err != nil {
		return "", err
	}

	// Map our type names to Steam's file naming
	var patterns []string
	switch artType {
	case ArtworkGrid:
		patterns = []string{
			appID + "_library_600x900.jpg",
			appID + "_library_600x900.png",
			appID + "_library_600x900_2x.jpg",
			appID + "_library_600x900_2x.png",
		}
	case ArtworkHero:
		patterns = []string{
			appID + "_library_hero.jpg",
			appID + "_library_hero.png",
			appID + "_library_hero_blur.jpg",
		}
	case ArtworkLogo:
		patterns = []string{
			appID + "_logo.png",
			appID + "_logo.jpg",
		}
	case ArtworkIcon:
		patterns = []string{
			appID + "_icon.jpg",
			appID + "_icon.png",
		}
	case ArtworkHeader:
		patterns = []string{
			appID + "_header.jpg",
			appID + "_header.png",
		}
	default:
		return "", fmt.Errorf("unknown artwork type: %s", artType)
	}

	// Try each pattern
	for _, pattern := range patterns {
		path := filepath.Join(cacheDir, pattern)
		if _, err := os.Stat(path); err == nil {
			return path, nil
		}
	}

	return "", fmt.Errorf("no %s artwork found for appid %s", artType, appID)
}

// ListArtwork returns all available artwork types for a given appID.
func ListArtwork(appID string) map[ArtworkType]string {
	result := make(map[ArtworkType]string)
	for _, artType := range []ArtworkType{ArtworkGrid, ArtworkHero, ArtworkLogo, ArtworkIcon, ArtworkHeader} {
		if path, err := GetArtworkPath(appID, artType); err == nil {
			result[artType] = path
		}
	}
	return result
}

// HasArtwork returns true if any artwork exists for the given appID.
func HasArtwork(appID string) bool {
	return len(ListArtwork(appID)) > 0
}

// findLibraryCache locates Steam's library cache directory.
func findLibraryCache() (string, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}

	candidates := []string{
		filepath.Join(homeDir, ".steam", "steam", "appcache", "librarycache"),
		filepath.Join(homeDir, ".local", "share", "Steam", "appcache", "librarycache"),
	}

	for _, path := range candidates {
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			return path, nil
		}
	}

	return "", fmt.Errorf("Steam library cache not found")
}

// DetectContentType returns the MIME type based on file extension.
func DetectContentType(path string) string {
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".png":
		return "image/png"
	case ".webp":
		return "image/webp"
	default:
		return "application/octet-stream"
	}
}
