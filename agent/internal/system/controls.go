package system

import (
	"fmt"
	"log"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

// VolumeGet returns the current system volume (0-100) via PipeWire/PulseAudio.
func VolumeGet() (int, error) {
	// Use pactl (works on both PipeWire-Pulse and PulseAudio)
	out, err := exec.Command("pactl", "get-sink-volume", "@DEFAULT_SINK@").Output()
	if err != nil {
		return 0, fmt.Errorf("failed to get volume: %w", err)
	}
	// Output format: "Volume: front-left: 65536 / 100% / ..."
	line := string(out)
	for _, part := range strings.Fields(line) {
		if strings.HasSuffix(part, "%") {
			pct := strings.TrimSuffix(part, "%")
			vol, err := strconv.Atoi(pct)
			if err == nil {
				return vol, nil
			}
		}
	}
	return 0, fmt.Errorf("could not parse volume from: %s", line)
}

// VolumeSet sets the system volume (0-100).
func VolumeSet(level int) error {
	if level < 0 {
		level = 0
	}
	if level > 100 {
		level = 100
	}
	return exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", fmt.Sprintf("%d%%", level)).Run()
}

// VolumeMute toggles or sets mute state.
func VolumeMute(mute bool) error {
	val := "0"
	if mute {
		val = "1"
	}
	return exec.Command("pactl", "set-sink-mute", "@DEFAULT_SINK@", val).Run()
}

// Suspend suspends the system.
// Fallback chain:
//  1. Steam D-Bus (gaming mode — saves game state properly)
//  2. loginctl (desktop mode — talks to logind, no sudo/sudoers needed)
//  3. logind D-Bus (direct D-Bus call to systemd-logind)
//  4. sudo systemctl (legacy — only works if sudoers rule exists)
//  5. systemctl (last resort — may fail without polkit auth)
func Suspend() error {
	return powerAction("Suspend", "suspend")
}

// Shutdown powers off the system.
func Shutdown() error {
	return powerAction("Shutdown", "poweroff")
}

// Reboot restarts the system.
func Reboot() error {
	return powerAction("Reboot", "reboot")
}

// loginctlAction maps systemctl actions to loginctl equivalents.
var loginctlAction = map[string]string{
	"suspend":  "suspend",
	"poweroff": "poweroff",
	"reboot":   "reboot",
}

// logindDBusMethod maps systemctl actions to org.freedesktop.login1.Manager methods.
var logindDBusMethod = map[string]string{
	"suspend":  "Suspend",
	"poweroff": "PowerOff",
	"reboot":   "Reboot",
}

// powerAction tries multiple methods to execute a power command.
func powerAction(dbusMethod, systemctlAction string) error {
	// 1. Try Steam D-Bus (works in gaming mode)
	if err := steamDBusCall(dbusMethod); err == nil {
		log.Printf("Power action '%s' succeeded via Steam D-Bus", dbusMethod)
		return nil
	} else {
		log.Printf("Steam D-Bus %s unavailable: %v", dbusMethod, err)
	}

	// 2. Try loginctl (works for session users without sudo/sudoers)
	if action, ok := loginctlAction[systemctlAction]; ok {
		if err := exec.Command("loginctl", action).Run(); err == nil {
			log.Printf("Power action '%s' succeeded via loginctl", action)
			return nil
		} else {
			log.Printf("loginctl %s failed: %v", action, err)
		}
	}

	// 3. Try logind D-Bus directly (works when loginctl is unavailable)
	if method, ok := logindDBusMethod[systemctlAction]; ok {
		if err := logindDBusCall(method); err == nil {
			log.Printf("Power action '%s' succeeded via logind D-Bus", method)
			return nil
		} else {
			log.Printf("logind D-Bus %s failed: %v", method, err)
		}
	}

	// 4. Try sudo systemctl (legacy — only works if sudoers rule exists)
	if err := exec.Command("sudo", "-n", "systemctl", systemctlAction).Run(); err == nil {
		log.Printf("Power action '%s' succeeded via sudo systemctl", systemctlAction)
		return nil
	} else {
		log.Printf("sudo systemctl %s failed: %v", systemctlAction, err)
	}

	// 5. Last resort: raw systemctl (may prompt for polkit auth and fail)
	log.Printf("Trying raw systemctl %s as last resort", systemctlAction)
	return exec.Command("systemctl", systemctlAction).Run()
}

// logindDBusCall invokes a power method on org.freedesktop.login1.Manager
// via the system bus. This works for session users without sudo or sudoers
// and survives SteamOS updates that wipe /etc/sudoers.d/.
func logindDBusCall(method string) error {
	return exec.Command(
		"dbus-send",
		"--system",
		"--print-reply",
		"--dest=org.freedesktop.login1",
		"/org/freedesktop/login1",
		fmt.Sprintf("org.freedesktop.login1.Manager.%s", method),
		"boolean:true",
	).Run()
}

// steamDBusCall invokes a method on Steam's D-Bus Manager interface.
// Uses --print-reply to get actual errors instead of silent fire-and-forget.
//
// In gaming mode, gamescope-session creates its own D-Bus session at a
// different address than the standard user bus. We try:
//  1. Steam's actual D-Bus address from /proc/<steam-pid>/environ
//  2. The standard systemd user bus (/run/user/<uid>/bus)
func steamDBusCall(method string) error {
	busAddrs := findSteamDBusAddresses()

	var lastErr error
	for _, busAddr := range busAddrs {
		cmd := exec.Command(
			"dbus-send",
			"--session",
			"--print-reply",
			"--dest=com.valvesoftware.steam",
			"--type=method_call",
			"/com/valvesoftware/steam/Manager",
			fmt.Sprintf("com.valvesoftware.steam.Manager.%s", method),
		)
		cmd.Env = append(os.Environ(), "DBUS_SESSION_BUS_ADDRESS="+busAddr)

		output, err := cmd.CombinedOutput()
		if err == nil {
			return nil
		}
		lastErr = fmt.Errorf("%s via %s: %w (output: %s)", method, busAddr, err, string(output))
	}

	if lastErr != nil {
		return lastErr
	}
	return fmt.Errorf("no D-Bus addresses found for Steam")
}

// findSteamDBusAddresses returns candidate D-Bus session bus addresses.
// Tries to read Steam's actual bus address from its process environment first.
func findSteamDBusAddresses() []string {
	var addrs []string

	// Try to get Steam's actual D-Bus address from /proc
	if steamAddr := steamDBusFromProc(); steamAddr != "" {
		addrs = append(addrs, steamAddr)
	}

	// Standard systemd user bus as fallback
	uid := os.Getuid()
	stdAddr := fmt.Sprintf("unix:path=/run/user/%d/bus", uid)
	addrs = append(addrs, stdAddr)

	return addrs
}

// steamDBusFromProc reads DBUS_SESSION_BUS_ADDRESS from Steam's /proc environ.
func steamDBusFromProc() string {
	// Find steam PID
	out, err := exec.Command("pgrep", "-xo", "steam").Output()
	if err != nil {
		return ""
	}
	pid := strings.TrimSpace(string(out))
	if pid == "" {
		return ""
	}

	// Read its environment
	envData, err := os.ReadFile(fmt.Sprintf("/proc/%s/environ", pid))
	if err != nil {
		return ""
	}

	for _, entry := range strings.Split(string(envData), "\x00") {
		if strings.HasPrefix(entry, "DBUS_SESSION_BUS_ADDRESS=") {
			return strings.TrimPrefix(entry, "DBUS_SESSION_BUS_ADDRESS=")
		}
	}

	return ""
}

// CPUTemp reads CPU temperature in degrees Celsius.
func CPUTemp() (float64, error) {
	// Try hwmon first (more reliable across systems)
	if temp, err := readHwmonTemp("k10temp"); err == nil {
		return temp, nil
	}
	if temp, err := readHwmonTemp("coretemp"); err == nil {
		return temp, nil
	}
	// Fallback to thermal zones
	return readThermalZone("k10temp", "x86_pkg_temp", "coretemp")
}

// GPUTemp reads GPU temperature in degrees Celsius.
func GPUTemp() (float64, error) {
	// Try hwmon first (more reliable across systems)
	if temp, err := readHwmonTemp("amdgpu"); err == nil {
		return temp, nil
	}
	if temp, err := readHwmonTemp("radeon"); err == nil {
		return temp, nil
	}
	if temp, err := readHwmonTemp("nouveau"); err == nil {
		return temp, nil
	}
	// Fallback to thermal zones
	return readThermalZone("amdgpu", "radeon")
}

// readHwmonTemp reads temperature from /sys/class/hwmon/ by driver name.
// This is more reliable than thermal zones on many systems.
func readHwmonTemp(driverName string) (float64, error) {
	entries, err := os.ReadDir("/sys/class/hwmon")
	if err != nil {
		return 0, err
	}

	for _, entry := range entries {
		namePath := filepath.Join("/sys/class/hwmon", entry.Name(), "name")
		nameData, err := os.ReadFile(namePath)
		if err != nil {
			continue
		}
		name := strings.TrimSpace(string(nameData))
		if !strings.EqualFold(name, driverName) {
			continue
		}

		// Read temp1_input (primary temp for most drivers)
		tempPath := filepath.Join("/sys/class/hwmon", entry.Name(), "temp1_input")
		tempData, err := os.ReadFile(tempPath)
		if err != nil {
			// Try temp2_input as fallback (some GPUs use this for junction)
			tempPath = filepath.Join("/sys/class/hwmon", entry.Name(), "temp2_input")
			tempData, err = os.ReadFile(tempPath)
			if err != nil {
				continue
			}
		}
		milliC, err := strconv.ParseFloat(strings.TrimSpace(string(tempData)), 64)
		if err != nil {
			continue
		}
		return milliC / 1000.0, nil
	}

	return 0, fmt.Errorf("hwmon sensor %s not found", driverName)
}

// readThermalZone searches /sys/class/thermal/ for a matching zone type.
func readThermalZone(names ...string) (float64, error) {
	entries, err := os.ReadDir("/sys/class/thermal")
	if err != nil {
		return 0, err
	}

	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "thermal_zone") {
			continue
		}

		typePath := filepath.Join("/sys/class/thermal", entry.Name(), "type")
		typeData, err := os.ReadFile(typePath)
		if err != nil {
			continue
		}
		zoneType := strings.TrimSpace(string(typeData))

		for _, name := range names {
			if strings.Contains(strings.ToLower(zoneType), strings.ToLower(name)) {
				tempPath := filepath.Join("/sys/class/thermal", entry.Name(), "temp")
				tempData, err := os.ReadFile(tempPath)
				if err != nil {
					continue
				}
				milliC, err := strconv.ParseFloat(strings.TrimSpace(string(tempData)), 64)
				if err != nil {
					continue
				}
				return milliC / 1000.0, nil
			}
		}
	}

	return 0, fmt.Errorf("no thermal zone found for %v", names)
}

// BatteryLevel returns battery percentage (0-100) or -1 if no battery.
func BatteryLevel() int {
	data, err := os.ReadFile("/sys/class/power_supply/BAT0/capacity")
	if err != nil {
		data, err = os.ReadFile("/sys/class/power_supply/BAT1/capacity")
		if err != nil {
			return -1 // No battery (desktop/Steam Machine)
		}
	}
	level, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return -1
	}
	return level
}

// BatteryCharging returns true if the battery is charging.
func BatteryCharging() bool {
	data, err := os.ReadFile("/sys/class/power_supply/BAT0/status")
	if err != nil {
		data, err = os.ReadFile("/sys/class/power_supply/BAT1/status")
		if err != nil {
			return false
		}
	}
	return strings.TrimSpace(string(data)) == "Charging"
}

// ActiveAppInfo contains information about the currently active application.
type ActiveAppInfo struct {
	Name    string `json:"name"`
	AppType string `json:"type"` // "game", "app", "desktop", "steam"
}

// ActiveApp detects what is currently running in the foreground.
// It checks the active window title and running processes.
func ActiveApp(gameNames map[string]string) ActiveAppInfo {
	// Try xdotool to get the active window name
	out, err := exec.Command("xdotool", "getactivewindow", "getwindowname").Output()
	if err == nil {
		windowName := strings.TrimSpace(string(out))
		if windowName != "" {
			return classifyWindow(windowName, gameNames)
		}
	}

	// Fallback: check for running Steam game via process list
	out, err = exec.Command("pgrep", "-a", "reaper").Output()
	if err == nil {
		line := string(out)
		// Steam reaper process contains the AppID
		if strings.Contains(line, "SteamLaunch AppId=") {
			parts := strings.Split(line, "AppId=")
			if len(parts) > 1 {
				appID := strings.Fields(parts[1])[0]
				if name, ok := gameNames[appID]; ok {
					return ActiveAppInfo{Name: name, AppType: "game"}
				}
				return ActiveAppInfo{Name: "Steam Game " + appID, AppType: "game"}
			}
		}
	}

	return ActiveAppInfo{Name: "", AppType: "idle"}
}

// classifyWindow determines the app type from a window title.
func classifyWindow(title string, gameNames map[string]string) ActiveAppInfo {
	lower := strings.ToLower(title)

	// Check for known app patterns
	knownApps := map[string]string{
		"jellyfin":    "Jellyfin",
		"firefox":     "Firefox",
		"chrome":      "Chrome",
		"chromium":    "Chromium",
		"vacuumtube":  "VacuumTube",
		"kodi":        "Kodi",
		"retroarch":   "RetroArch",
		"konsole":     "Konsole",
		"dolphin":     "Dolphin",
		"feishin":     "Feishin",
		"spotify":     "Spotify",
	}

	for keyword, appName := range knownApps {
		if strings.Contains(lower, keyword) {
			return ActiveAppInfo{Name: appName, AppType: "app"}
		}
	}

	// Check if it matches a known game name
	for _, name := range gameNames {
		if strings.EqualFold(title, name) || strings.Contains(lower, strings.ToLower(name)) {
			return ActiveAppInfo{Name: name, AppType: "game"}
		}
	}

	// Steam itself
	if lower == "steam" || strings.HasPrefix(lower, "steam -") {
		return ActiveAppInfo{Name: "Steam", AppType: "steam"}
	}

	// Desktop environment
	if strings.Contains(lower, "desktop") || strings.Contains(lower, "plasma") {
		return ActiveAppInfo{Name: "", AppType: "desktop"}
	}

	// Unknown but active window
	return ActiveAppInfo{Name: title, AppType: "app"}
}

// AmbientTemp reads the ambient/case temperature from ACPI thermal zones.
func AmbientTemp() (float64, error) {
	// Try ACPI thermal zone first
	if temp, err := readThermalZone("acpitz"); err == nil {
		return temp, nil
	}
	// Try gigabyte_wmi or other board sensors via hwmon
	if temp, err := readHwmonTemp("gigabyte_wmi"); err == nil {
		return temp, nil
	}
	return 0, fmt.Errorf("no ambient temp sensor found")
}

// DiskUsage returns total, used, and free space in GB for the given path.
func DiskUsage(path string) (totalGB, usedGB, freeGB float64) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(path, &stat); err != nil {
		return 0, 0, 0
	}

	total := float64(stat.Blocks) * float64(stat.Bsize)
	free := float64(stat.Bavail) * float64(stat.Bsize)
	used := total - free

	const gb = 1024 * 1024 * 1024
	return math.Round(total/gb*10) / 10,
		math.Round(used/gb*10) / 10,
		math.Round(free/gb*10) / 10
}

// DirSizeGB returns the size of a directory in GB using du.
func DirSizeGB(path string) float64 {
	if path == "" {
		path = "/home/deck"
	}
	out, err := exec.Command("du", "-sb", path).Output()
	if err != nil {
		return 0
	}
	fields := strings.Fields(string(out))
	if len(fields) == 0 {
		return 0
	}
	bytes, err := strconv.ParseFloat(fields[0], 64)
	if err != nil {
		return 0
	}
	const gb = 1024 * 1024 * 1024
	return math.Round(bytes/gb*10) / 10
}
