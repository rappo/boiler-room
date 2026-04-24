package games

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Game represents an installed Steam game
type Game struct {
	AppID      string `json:"appid"`
	Name       string `json:"name"`
	InstallDir string `json:"install_dir,omitempty"`
	SizeOnDisk int64  `json:"size_on_disk,omitempty"`
	LastPlayed int64  `json:"last_played,omitempty"`
}

// Scanner discovers installed Steam games by reading local manifest files.
// It auto-detects all Steam library folders — no manual config needed.
type Scanner struct {
	libraryPaths []string
	games        []Game
}

// NewScanner creates a scanner with auto-detected library paths.
func NewScanner() *Scanner {
	s := &Scanner{}
	s.libraryPaths = s.discoverLibraryPaths()
	return s
}

// discoverLibraryPaths finds all Steam library folders automatically.
// It checks the default location and parses libraryfolders.vdf for extras.
func (s *Scanner) discoverLibraryPaths() []string {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil
	}

	// Possible base Steam directories
	steamRoots := []string{
		filepath.Join(homeDir, ".steam", "steam"),
		filepath.Join(homeDir, ".local", "share", "Steam"),
	}

	// Find the actual Steam root
	var steamRoot string
	for _, root := range steamRoots {
		if _, err := os.Stat(filepath.Join(root, "steamapps")); err == nil {
			steamRoot = root
			break
		}
	}
	if steamRoot == "" {
		return nil
	}

	paths := []string{filepath.Join(steamRoot, "steamapps")}

	// Parse libraryfolders.vdf for additional library paths
	vdfPath := filepath.Join(steamRoot, "steamapps", "libraryfolders.vdf")
	extraPaths := parseLibraryFolders(vdfPath)
	for _, p := range extraPaths {
		appsDir := filepath.Join(p, "steamapps")
		if _, err := os.Stat(appsDir); err == nil {
			paths = append(paths, appsDir)
		}
	}

	// Also check common SD card path (Steam Deck)
	sdCardPath := "/run/media/mmcblk0p1/steamapps"
	if _, err := os.Stat(sdCardPath); err == nil {
		// Avoid duplicates
		found := false
		for _, p := range paths {
			if p == sdCardPath {
				found = true
				break
			}
		}
		if !found {
			paths = append(paths, sdCardPath)
		}
	}

	return paths
}

// parseLibraryFolders extracts library paths from libraryfolders.vdf.
// The VDF format is a simple nested key-value format used by Valve.
func parseLibraryFolders(path string) []string {
	file, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer file.Close()

	var paths []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// Look for "path" keys — they contain library folder paths
		if strings.HasPrefix(line, `"path"`) {
			parts := strings.SplitN(line, `"`, 5)
			if len(parts) >= 4 {
				paths = append(paths, parts[3])
			}
		}
	}
	return paths
}

// Scan reads all appmanifest_*.acf files and returns installed games.
func (s *Scanner) Scan() ([]Game, error) {
	seen := make(map[string]bool)
	var games []Game

	for _, libPath := range s.libraryPaths {
		pattern := filepath.Join(libPath, "appmanifest_*.acf")
		matches, err := filepath.Glob(pattern)
		if err != nil {
			continue
		}

		for _, manifest := range matches {
			game, err := parseACF(manifest)
			if err != nil {
				continue
			}
			// Skip tools, redistributables, etc.
			if game.Name == "" || game.AppID == "" {
				continue
			}
			// Deduplicate by AppID (symlinked library paths cause doubles)
			if seen[game.AppID] {
				continue
			}
			seen[game.AppID] = true
			games = append(games, game)
		}
	}

	// Sort alphabetically by name
	sort.Slice(games, func(i, j int) bool {
		return strings.ToLower(games[i].Name) < strings.ToLower(games[j].Name)
	})

	s.games = games
	return games, nil
}

// GetCached returns the last scan result without re-scanning.
func (s *Scanner) GetCached() []Game {
	return s.games
}

// FindByName does case-insensitive substring matching against installed games.
// Returns the best match or an error if nothing matches.
func (s *Scanner) FindByName(query string) (*Game, error) {
	if len(s.games) == 0 {
		if _, err := s.Scan(); err != nil {
			return nil, err
		}
	}

	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return nil, fmt.Errorf("empty search query")
	}

	// Exact match first (case-insensitive)
	for i := range s.games {
		if strings.ToLower(s.games[i].Name) == query {
			return &s.games[i], nil
		}
	}

	// Substring match
	var matches []Game
	for i := range s.games {
		if strings.Contains(strings.ToLower(s.games[i].Name), query) {
			matches = append(matches, s.games[i])
		}
	}

	if len(matches) == 1 {
		return &matches[0], nil
	}
	if len(matches) > 1 {
		// Return the shortest name (most specific match)
		sort.Slice(matches, func(i, j int) bool {
			return len(matches[i].Name) < len(matches[j].Name)
		})
		return &matches[0], nil
	}

	return nil, fmt.Errorf("no game matching '%s' found", query)
}

// FindByAppID returns a game by its AppID.
func (s *Scanner) FindByAppID(appID string) (*Game, error) {
	if len(s.games) == 0 {
		if _, err := s.Scan(); err != nil {
			return nil, err
		}
	}

	for i := range s.games {
		if s.games[i].AppID == appID {
			return &s.games[i], nil
		}
	}

	return nil, fmt.Errorf("no game with AppID '%s' found", appID)
}

// LibraryPaths returns the auto-detected library paths (for diagnostics).
func (s *Scanner) LibraryPaths() []string {
	return s.libraryPaths
}

// parseACF reads a Valve ACF manifest file and extracts game metadata.
// ACF is a simple key-value text format:
//
//	"AppState"
//	{
//	    "appid"    "12345"
//	    "name"     "My Game"
//	}
func parseACF(path string) (Game, error) {
	file, err := os.Open(path)
	if err != nil {
		return Game{}, err
	}
	defer file.Close()

	game := Game{}
	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		// Parse "key" "value" pairs
		parts := splitACFLine(line)
		if len(parts) != 2 {
			continue
		}

		key, value := parts[0], parts[1]
		switch strings.ToLower(key) {
		case "appid":
			game.AppID = value
		case "name":
			game.Name = value
		case "installdir":
			game.InstallDir = value
		case "sizeondisk":
			if n, err := strconv.ParseInt(value, 10, 64); err == nil {
				game.SizeOnDisk = n
			}
		case "lastupdated":
			if n, err := strconv.ParseInt(value, 10, 64); err == nil {
				game.LastPlayed = n
			}
		}
	}

	return game, scanner.Err()
}

// splitACFLine splits a line like `"key" "value"` into [key, value].
func splitACFLine(line string) []string {
	var parts []string
	inQuote := false
	current := strings.Builder{}

	for _, r := range line {
		switch {
		case r == '"':
			if inQuote {
				parts = append(parts, current.String())
				current.Reset()
			}
			inQuote = !inQuote
		case inQuote:
			current.WriteRune(r)
		}
	}

	return parts
}
