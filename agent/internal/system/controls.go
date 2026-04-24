package system

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
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
//  2. sudo systemctl suspend (desktop mode — needs sudoers rule from install)
//  3. systemctl suspend (last resort — may fail without polkit auth)
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

// powerAction tries multiple methods to execute a power command.
func powerAction(dbusMethod, systemctlAction string) error {
	// 1. Try Steam D-Bus (works in gaming mode)
	if err := steamDBusCall(dbusMethod); err == nil {
		log.Printf("Power action '%s' succeeded via Steam D-Bus", dbusMethod)
		return nil
	} else {
		log.Printf("Steam D-Bus %s unavailable: %v", dbusMethod, err)
	}

	// 2. Try sudo systemctl (works in desktop mode with our sudoers rule)
	if err := exec.Command("sudo", "-n", "systemctl", systemctlAction).Run(); err == nil {
		log.Printf("Power action '%s' succeeded via sudo systemctl", systemctlAction)
		return nil
	} else {
		log.Printf("sudo systemctl %s failed: %v", systemctlAction, err)
	}

	// 3. Last resort: raw systemctl (may prompt for polkit auth and fail)
	log.Printf("Trying raw systemctl %s as last resort", systemctlAction)
	return exec.Command("systemctl", systemctlAction).Run()
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
	return readThermalZone("x86_pkg_temp", "coretemp")
}

// GPUTemp reads GPU temperature in degrees Celsius.
func GPUTemp() (float64, error) {
	return readThermalZone("amdgpu", "radeon")
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

	// Fallback: read first available thermal zone
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "thermal_zone") {
			continue
		}
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

	return 0, fmt.Errorf("no thermal zone found")
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
