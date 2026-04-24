package system

import (
	"fmt"
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
func Suspend() error {
	return exec.Command("systemctl", "suspend").Run()
}

// Shutdown powers off the system.
func Shutdown() error {
	return exec.Command("systemctl", "poweroff").Run()
}

// Reboot restarts the system.
func Reboot() error {
	return exec.Command("systemctl", "reboot").Run()
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
