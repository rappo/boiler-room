package system

import (
	"log"
	"os/exec"
	"strings"
	"sync"

	dbus "github.com/godbus/dbus/v5"
)

// PowerState tracks the system's power lifecycle state.
// Values: "on", "sleep", "shutdown", "reboot"
type PowerState struct {
	mu       sync.RWMutex
	state    string
	onChange func(state string)
}

// NewPowerState creates a new PowerState tracker.
// The onChange callback is invoked whenever the state changes (for WebSocket broadcast).
func NewPowerState(onChange func(string)) *PowerState {
	return &PowerState{
		state:    "on",
		onChange: onChange,
	}
}

// Get returns the current power state.
func (ps *PowerState) Get() string {
	ps.mu.RLock()
	defer ps.mu.RUnlock()
	return ps.state
}

// SetOnChange sets the callback invoked on state changes.
// Used to wire up WebSocket broadcast after server creation.
func (ps *PowerState) SetOnChange(fn func(string)) {
	ps.mu.Lock()
	defer ps.mu.Unlock()
	ps.onChange = fn
}

// set updates the power state and invokes the onChange callback.
func (ps *PowerState) set(state string) {
	ps.mu.Lock()
	old := ps.state
	ps.state = state
	ps.mu.Unlock()

	if old != state {
		log.Printf("Power state: %s → %s", old, state)
		if ps.onChange != nil {
			ps.onChange(state)
		}
	}
}

// SetPending sets the power state before executing a power action.
// Called from the API handler so the state is set before the system acts.
func (ps *PowerState) SetPending(action string) {
	switch action {
	case "suspend":
		ps.set("sleep")
	case "shutdown":
		ps.set("shutdown")
	case "reboot":
		ps.set("reboot")
	}
}

// StartDBusListener listens for logind PrepareForSleep and PrepareForShutdown
// signals on the system bus. These signals fire regardless of how the power
// action is initiated (Steam menu, SSH, HDMI-CEC remote, power button, etc.).
//
// Signals:
//   - PrepareForSleep(true)  → state = "sleep"
//   - PrepareForSleep(false) → state = "on" (wake from sleep)
//   - PrepareForShutdown(true) → checks systemctl list-jobs:
//     reboot.target  → state = "reboot"
//     poweroff.target → state = "shutdown"
func (ps *PowerState) StartDBusListener() error {
	conn, err := dbus.SystemBus()
	if err != nil {
		return err
	}

	// Subscribe to logind signals
	if err := conn.AddMatchSignal(
		dbus.WithMatchObjectPath("/org/freedesktop/login1"),
		dbus.WithMatchInterface("org.freedesktop.login1.Manager"),
		dbus.WithMatchMember("PrepareForSleep"),
	); err != nil {
		conn.Close()
		return err
	}

	if err := conn.AddMatchSignal(
		dbus.WithMatchObjectPath("/org/freedesktop/login1"),
		dbus.WithMatchInterface("org.freedesktop.login1.Manager"),
		dbus.WithMatchMember("PrepareForShutdown"),
	); err != nil {
		conn.Close()
		return err
	}

	signals := make(chan *dbus.Signal, 16)
	conn.Signal(signals)

	go func() {
		log.Println("Power state: DBus listener started")
		for sig := range signals {
			switch sig.Name {
			case "org.freedesktop.login1.Manager.PrepareForSleep":
				if len(sig.Body) > 0 {
					if preparing, ok := sig.Body[0].(bool); ok {
						if preparing {
							ps.set("sleep")
						} else {
							// Waking from sleep
							ps.set("on")
						}
					}
				}

			case "org.freedesktop.login1.Manager.PrepareForShutdown":
				if len(sig.Body) > 0 {
					if preparing, ok := sig.Body[0].(bool); ok && preparing {
						// Determine if this is a reboot or a shutdown
						target := detectShutdownTarget()
						ps.set(target)
					}
				}
			}
		}
	}()

	return nil
}

// detectShutdownTarget checks systemctl list-jobs to determine if the
// system is rebooting or powering off.
func detectShutdownTarget() string {
	out, err := exec.Command("systemctl", "list-jobs", "--plain", "--no-legend").Output()
	if err != nil {
		log.Printf("Power state: failed to list-jobs: %v, assuming shutdown", err)
		return "shutdown"
	}

	jobs := string(out)
	if strings.Contains(jobs, "reboot.target") {
		return "reboot"
	}
	if strings.Contains(jobs, "poweroff.target") || strings.Contains(jobs, "halt.target") {
		return "shutdown"
	}

	// Fallback: if we can't determine, assume shutdown (safer — turns off TV)
	log.Printf("Power state: could not determine shutdown target from jobs: %s", jobs)
	return "shutdown"
}
