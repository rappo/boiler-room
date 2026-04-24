package games

import (
	"fmt"
	"os/exec"
	"strconv"
)

// Launch starts a Steam game by AppID using the steam:// protocol.
// This works in both Gaming Mode and Desktop Mode.
func Launch(appID string) error {
	if appID == "" {
		return fmt.Errorf("empty AppID")
	}

	url := fmt.Sprintf("steam://rungameid/%s", appID)
	cmd := exec.Command("steam", url)

	// Start without waiting — the game runs independently
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to launch game %s: %w", appID, err)
	}

	// Release the process — we don't need to wait for it
	go func() {
		_ = cmd.Wait()
	}()

	return nil
}

// LaunchShortcut starts a non-Steam shortcut by its VDF appid.
// Non-Steam shortcuts use a 64-bit gameid: (appid << 32) | 0x02000000
// Regular steam://rungameid/ only works with raw appids for Steam games.
func LaunchShortcut(appID string) error {
	if appID == "" {
		return fmt.Errorf("empty AppID")
	}

	id, err := strconv.ParseUint(appID, 10, 32)
	if err != nil {
		return fmt.Errorf("invalid shortcut appid %q: %w", appID, err)
	}

	gameID := (id << 32) | 0x02000000
	url := fmt.Sprintf("steam://rungameid/%d", gameID)
	cmd := exec.Command("steam", url)

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to launch shortcut %s: %w", appID, err)
	}
	go func() { _ = cmd.Wait() }()

	return nil
}

// LaunchByName finds a game by name using the scanner and launches it.
// Returns the matched game on success.
func LaunchByName(scanner *Scanner, query string) (*Game, error) {
	game, err := scanner.FindByName(query)
	if err != nil {
		return nil, err
	}

	if err := Launch(game.AppID); err != nil {
		return game, err
	}

	return game, nil
}

