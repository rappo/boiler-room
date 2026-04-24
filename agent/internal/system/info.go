package system

import (
	"crypto/sha256"
	"fmt"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// Info holds system information about the SteamOS device
type Info struct {
	DeviceID   string `json:"device_id"`
	Hostname   string `json:"hostname"`
	OS         string `json:"os"`
	Arch       string `json:"arch"`
	MacAddress string `json:"mac_address,omitempty"`
	IPAddress  string `json:"ip_address,omitempty"`
	startTime  time.Time
}

// NewInfo gathers system information.
func NewInfo() *Info {
	hostname, _ := os.Hostname()

	info := &Info{
		Hostname:  hostname,
		OS:        runtime.GOOS,
		Arch:      runtime.GOARCH,
		startTime: time.Now(),
	}

	info.DeviceID = info.generateDeviceID()
	info.MacAddress = info.getMACAddress()
	info.IPAddress = info.getIPAddress()

	return info
}

// UptimeSeconds returns the number of seconds since the agent started.
func (i *Info) UptimeSeconds() int64 {
	return int64(time.Since(i.startTime).Seconds())
}

// generateDeviceID creates a stable identifier for this device.
// Uses machine-id if available, falls back to hostname hash.
func (i *Info) generateDeviceID() string {
	// Try /etc/machine-id (standard on systemd systems including SteamOS)
	data, err := os.ReadFile("/etc/machine-id")
	if err == nil {
		machineID := strings.TrimSpace(string(data))
		if machineID != "" {
			hash := sha256.Sum256([]byte("boiler-room:" + machineID))
			return fmt.Sprintf("%x", hash[:8])
		}
	}

	// Fallback: hash the hostname
	hash := sha256.Sum256([]byte("boiler-room:" + i.Hostname))
	return fmt.Sprintf("%x", hash[:8])
}

// getMACAddress returns the MAC address of the first non-loopback interface.
func (i *Info) getMACAddress() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return ""
	}

	for _, iface := range interfaces {
		// Skip loopback and interfaces without a hardware address
		if iface.Flags&net.FlagLoopback != 0 || len(iface.HardwareAddr) == 0 {
			continue
		}
		// Skip virtual interfaces
		if strings.HasPrefix(iface.Name, "veth") || strings.HasPrefix(iface.Name, "docker") || strings.HasPrefix(iface.Name, "br-") {
			continue
		}
		return iface.HardwareAddr.String()
	}
	return ""
}

// getIPAddress returns the primary local IP address.
func (i *Info) getIPAddress() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return ""
	}
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)
	return localAddr.IP.String()
}

// IsGamingMode detects if SteamOS is in Gaming Mode by checking for gamescope.
func IsGamingMode() bool {
	out, err := exec.Command("pgrep", "-x", "gamescope").Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) != ""
}
