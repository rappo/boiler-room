package discovery

import (
	"log"
	"os"

	"github.com/grandcat/zeroconf"
)

// Advertise registers the Boiler Room agent on the local network via mDNS
// and returns a function that withdraws the advertisement. It does not
// block; the caller stops it on shutdown.
func Advertise(deviceName string, port int, deviceID string, version string) (func(), error) {
	hostname, _ := os.Hostname()

	txt := []string{
		"version=" + version,
		"device_name=" + deviceName,
		"device_id=" + deviceID,
	}

	server, err := zeroconf.Register(
		hostname,            // Instance name
		"_boiler-room._tcp", // Service type
		"local.",            // Domain
		port,                // Port
		txt,                 // TXT records
		nil,                 // Interfaces (nil = all)
	)
	if err != nil {
		return nil, err
	}

	log.Printf("mDNS: advertising as '%s' on _boiler-room._tcp.local. port %d", deviceName, port)

	return func() {
		log.Println("mDNS: shutting down advertisement")
		server.Shutdown()
	}, nil
}
