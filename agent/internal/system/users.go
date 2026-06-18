package system

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// SteamUser represents a Steam account that has logged in on this device.
type SteamUser struct {
	SteamID     string `json:"steam_id"`
	AccountName string `json:"account_name"`
	PersonaName string `json:"persona_name"`
	MostRecent  bool   `json:"most_recent"`
}

// steamDir returns the path to the Steam config directory.
func steamDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".steam", "steam", "config")
}

// registryPath returns the path to the Steam registry.vdf file.
func registryPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".steam", "registry.vdf")
}

// SteamUsers parses loginusers.vdf and returns all saved accounts.
func SteamUsers() ([]SteamUser, error) {
	path := filepath.Join(steamDir(), "loginusers.vdf")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("cannot read loginusers.vdf: %w", err)
	}

	return parseLoginUsers(string(data)), nil
}

// ActiveSteamUser returns the AccountName of the currently active user
// by reading AutoLoginUser from registry.vdf.
func ActiveSteamUser() string {
	data, err := os.ReadFile(registryPath())
	if err != nil {
		return ""
	}

	re := regexp.MustCompile(`"AutoLoginUser"\s+"([^"]+)"`)
	match := re.FindStringSubmatch(string(data))
	if len(match) > 1 {
		return match[1]
	}
	return ""
}

// SwitchSteamUser changes the active Steam account and restarts Steam.
// It updates both loginusers.vdf (MostRecent flags) and registry.vdf
// (AutoLoginUser), then kills Steam so gamescope relaunches it.
func SwitchSteamUser(accountName string) error {
	// Verify the target account exists
	users, err := SteamUsers()
	if err != nil {
		return err
	}

	found := false
	for _, u := range users {
		if u.AccountName == accountName {
			found = true
			break
		}
	}
	if !found {
		return fmt.Errorf("account %q not found in loginusers.vdf", accountName)
	}

	// Kill Steam first — it writes VDF files on exit, which would
	// overwrite our changes if we wrote them before killing.
	log.Printf("Killing Steam to switch to account %q...", accountName)
	exec.Command("killall", "steam").Run()

	// Wait for Steam to fully exit and flush its VDF files
	for i := 0; i < 20; i++ {
		time.Sleep(500 * time.Millisecond)
		if err := exec.Command("pgrep", "-x", "steam").Run(); err != nil {
			break // Steam is gone
		}
	}

	// Now update the VDF files — Steam will read these on relaunch
	loginUsersPath := filepath.Join(steamDir(), "loginusers.vdf")
	if err := updateLoginUsersMostRecent(loginUsersPath, accountName); err != nil {
		return fmt.Errorf("failed to update loginusers.vdf: %w", err)
	}

	if err := updateRegistryAutoLogin(registryPath(), accountName); err != nil {
		return fmt.Errorf("failed to update registry.vdf: %w", err)
	}

	log.Printf("VDF files updated for %q, gamescope will relaunch Steam.", accountName)
	return nil
}

// parseLoginUsers extracts user entries from loginusers.vdf content.
// This is a simple parser for Valve's VDF format (not a full parser).
func parseLoginUsers(content string) []SteamUser {
	var users []SteamUser
	var current *SteamUser
	depth := 0

	scanner := bufio.NewScanner(strings.NewReader(content))
	steamIDRe := regexp.MustCompile(`^\s*"(\d{17})"`)
	kvRe := regexp.MustCompile(`^\s*"([^"]+)"\s+"([^"]*)"`)

	for scanner.Scan() {
		line := scanner.Text()
		trimmed := strings.TrimSpace(line)

		if trimmed == "{" {
			depth++
			continue
		}
		if trimmed == "}" {
			depth--
			if current != nil && depth <= 1 {
				users = append(users, *current)
				current = nil
			}
			continue
		}

		// Match a SteamID line (17-digit number as a key)
		if m := steamIDRe.FindStringSubmatch(line); len(m) > 1 {
			current = &SteamUser{SteamID: m[1]}
			continue
		}

		// Match key-value pairs within a user block
		if current != nil {
			if m := kvRe.FindStringSubmatch(line); len(m) > 2 {
				switch m[1] {
				case "AccountName":
					current.AccountName = m[2]
				case "PersonaName":
					current.PersonaName = m[2]
				case "MostRecent":
					current.MostRecent = m[2] == "1"
				}
			}
		}
	}

	return users
}

// updateLoginUsersMostRecent rewrites loginusers.vdf, setting MostRecent=1
// for the target account and MostRecent=0 for all others.
func updateLoginUsersMostRecent(path, targetAccount string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}

	lines := strings.Split(string(data), "\n")
	var result []string
	currentAccount := ""
	kvRe := regexp.MustCompile(`^(\s*)"([^"]+)"\s+"([^"]*)"(.*)$`)

	for _, line := range lines {
		m := kvRe.FindStringSubmatch(line)
		if len(m) > 3 {
			key := m[2]
			if key == "AccountName" {
				currentAccount = m[3]
			}
			if key == "MostRecent" {
				val := "0"
				if currentAccount == targetAccount {
					val = "1"
				}
				line = fmt.Sprintf("%s\"%s\"\t\t\"%s\"%s", m[1], key, val, m[4])
			}
			if key == "AllowAutoLogin" {
				val := "0"
				if currentAccount == targetAccount {
					val = "1"
				}
				line = fmt.Sprintf("%s\"%s\"\t\t\"%s\"%s", m[1], key, val, m[4])
			}
		}
		result = append(result, line)
	}

	return os.WriteFile(path, []byte(strings.Join(result, "\n")), 0644)
}

// updateRegistryAutoLogin rewrites registry.vdf, changing the AutoLoginUser value.
func updateRegistryAutoLogin(path, accountName string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}

	re := regexp.MustCompile(`("AutoLoginUser"\s+")([^"]*)(")`)
	updated := re.ReplaceAllString(string(data), "${1}"+accountName+"${3}")

	return os.WriteFile(path, []byte(updated), 0644)
}
