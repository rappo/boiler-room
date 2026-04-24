package discovery

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/grandcat/zeroconf"
)

// Advertise registers the Boiler Room agent on the local network via mDNS.
// It blocks until the process receives SIGTERM/SIGINT or the returned cancel func is called.
func Advertise(deviceName string, port int, deviceID string, version string) (func(), error) {
	hostname, _ := os.Hostname()

	txt := []string{
		"version=" + version,
		"device_name=" + deviceName,
		"device_id=" + deviceID,
	}

	server, err := zeroconf.Register(
		hostname,                   // Instance name
		"_boiler-room._tcp",        // Service type
		"local.",                   // Domain
		port,                       // Port
		txt,                        // TXT records
		nil,                        // Interfaces (nil = all)
	)
	if err != nil {
		return nil, err
	}

	log.Printf("mDNS: advertising as '%s' on _boiler-room._tcp.local. port %d", deviceName, port)

	// Graceful shutdown on signals
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
		<-sig
		log.Println("mDNS: shutting down advertisement")
		server.Shutdown()
	}()

	return func() { server.Shutdown() }, nil
}
