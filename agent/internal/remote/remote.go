// Package remote reports presses of chosen keys on one input device as
// named buttons, so Home Assistant can act on a remote control's keys.
//
// The intended source is input-remapper's virtual keyboard: input-remapper
// grabs the physical remote, so remapping a key there (volume up to F21,
// say) both stops SteamOS from acting on it and hands it to this watcher.
// Reading a device never grabs it, so whatever else listens still does.
package remote

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Event is one key transition on a configured key.
type Event struct {
	Button string `json:"button"`
	Action string `json:"action"` // press, repeat or release
}

const (
	evKey = 1
	// A struct input_event on 64-bit Linux: a 16-byte timeval, then type
	// (u16), code (u16) and value (s32).
	eventSize = 24
)

// keyCodes are the key names a config may use, from linux/input-event-codes.h.
// F13-F24 are the useful targets: nothing in SteamOS binds them.
var keyCodes = map[string]uint16{
	"KEY_MUTE":       113,
	"KEY_VOLUMEDOWN": 114,
	"KEY_VOLUMEUP":   115,
	"KEY_F13":        183,
	"KEY_F14":        184,
	"KEY_F15":        185,
	"KEY_F16":        186,
	"KEY_F17":        187,
	"KEY_F18":        188,
	"KEY_F19":        189,
	"KEY_F20":        190,
	"KEY_F21":        191,
	"KEY_F22":        192,
	"KEY_F23":        193,
	"KEY_F24":        194,
}

// ParseKeys turns a config map of key name (or decimal code) to button
// name into codes. It rejects unknown names rather than ignoring them, so
// a typo shows up in the log instead of as a dead button.
func ParseKeys(names map[string]string) (map[uint16]string, error) {
	keys := make(map[uint16]string, len(names))
	for name, button := range names {
		button = strings.TrimSpace(button)
		if button == "" {
			return nil, fmt.Errorf("key %s has no button name", name)
		}
		code, ok := keyCodes[strings.ToUpper(strings.TrimSpace(name))]
		if !ok {
			n, err := strconv.ParseUint(strings.TrimSpace(name), 10, 16)
			if err != nil {
				return nil, fmt.Errorf("unknown key %q: use a KEY_ name or a decimal code", name)
			}
			code = uint16(n)
		}
		keys[code] = button
	}
	return keys, nil
}

// Translate maps one raw input event to a button event, if it is a
// configured key.
func Translate(keys map[uint16]string, typ, code uint16, value int32) (Event, bool) {
	if typ != evKey {
		return Event{}, false
	}
	button, ok := keys[code]
	if !ok {
		return Event{}, false
	}
	switch value {
	case 0:
		return Event{button, "release"}, true
	case 1:
		return Event{button, "press"}, true
	case 2:
		return Event{button, "repeat"}, true
	}
	return Event{}, false
}

func decode(b []byte) (typ, code uint16, value int32) {
	return binary.LittleEndian.Uint16(b[16:18]),
		binary.LittleEndian.Uint16(b[18:20]),
		int32(binary.LittleEndian.Uint32(b[20:24]))
}

// FindDevice returns the /dev/input/eventN node of the first input device
// (by event number) whose name is exactly name, after trimming spaces.
// sysRoot is normally /sys and devRoot /dev.
func FindDevice(sysRoot, devRoot, name string) (string, error) {
	paths, err := filepath.Glob(filepath.Join(sysRoot, "class", "input", "event*"))
	if err != nil {
		return "", err
	}
	sort.Slice(paths, func(i, j int) bool { return eventNumber(paths[i]) < eventNumber(paths[j]) })
	want := strings.TrimSpace(name)
	for _, p := range paths {
		raw, err := os.ReadFile(filepath.Join(p, "device", "name"))
		if err != nil {
			continue
		}
		if strings.TrimSpace(string(raw)) == want {
			return filepath.Join(devRoot, "input", filepath.Base(p)), nil
		}
	}
	return "", errNotFound
}

var errNotFound = errors.New("no input device with that name")

func eventNumber(path string) int {
	n, err := strconv.Atoi(strings.TrimPrefix(filepath.Base(path), "event"))
	if err != nil {
		return -1
	}
	return n
}

// Watcher follows one named device, reopening it when it goes away:
// input-remapper recreates its virtual devices whenever it reloads.
//
// Repeats are the watcher's own. Neither the Rii i25 nor input-remapper's
// virtual keyboard has EV_REP, so the kernel never repeats their keys and a
// held key arrived as one press (seen live 2026-11-07: a 1 s hold was one
// volume step). The watcher drops any kernel repeats and, while a key is
// held, emits "repeat" after RepeatDelay and then every RepeatInterval, so
// holding behaves the same on every device.
type Watcher struct {
	Device string
	Keys   map[uint16]string
	Emit   func(Event)

	SysRoot        string        // default /sys
	DevRoot        string        // default /dev
	Retry          time.Duration // default 5 s
	RepeatDelay    time.Duration // default 400 ms
	RepeatInterval time.Duration // default 150 ms
}

const (
	defaultRepeatDelay    = 400 * time.Millisecond
	defaultRepeatInterval = 150 * time.Millisecond
)

// repeater turns press/release into press, repeat..., release.
type repeater struct {
	delay, interval time.Duration
	emit            func(Event)

	mu    sync.Mutex
	held  map[string]chan struct{} // button -> closed on release
	group sync.WaitGroup
}

func newRepeater(delay, interval time.Duration, emit func(Event)) *repeater {
	if delay <= 0 {
		delay = defaultRepeatDelay
	}
	if interval <= 0 {
		interval = defaultRepeatInterval
	}
	return &repeater{delay: delay, interval: interval, emit: emit, held: map[string]chan struct{}{}}
}

func (r *repeater) handle(ev Event) {
	switch ev.Action {
	case "press":
		r.stop(ev.Button)
		r.emit(ev)
		done := make(chan struct{})
		r.mu.Lock()
		r.held[ev.Button] = done
		r.mu.Unlock()
		r.group.Add(1)
		go r.repeat(ev.Button, done)
	case "release":
		r.stop(ev.Button)
		r.emit(ev)
	}
	// Kernel repeats are dropped: the repeater makes its own.
}

func (r *repeater) repeat(button string, done chan struct{}) {
	defer r.group.Done()
	timer := time.NewTimer(r.delay)
	defer timer.Stop()
	for {
		select {
		case <-done:
			return
		case <-timer.C:
			// Emit only while this press is still the held one, checked under
			// the lock that stop takes: a repeat can then never land after
			// the release, which would be one step too many.
			r.mu.Lock()
			if r.held[button] != done {
				r.mu.Unlock()
				return
			}
			r.emit(Event{button, "repeat"})
			r.mu.Unlock()
			timer.Reset(r.interval)
		}
	}
}

// stop ends the repeats of one button; none can be emitted after it returns.
func (r *repeater) stop(button string) {
	r.mu.Lock()
	done, ok := r.held[button]
	delete(r.held, button)
	r.mu.Unlock()
	if ok {
		close(done)
	}
}

// stopAll ends every held key, for when the device goes away mid-press.
// It waits for the repeat goroutines, so no repeat follows it.
func (r *repeater) stopAll() {
	r.mu.Lock()
	for button, done := range r.held {
		close(done)
		delete(r.held, button)
	}
	r.mu.Unlock()
	r.group.Wait()
}

// Run blocks until ctx is cancelled.
func (w *Watcher) Run(ctx context.Context) {
	sysRoot, devRoot, retry := w.SysRoot, w.DevRoot, w.Retry
	if sysRoot == "" {
		sysRoot = "/sys"
	}
	if devRoot == "" {
		devRoot = "/dev"
	}
	if retry == 0 {
		retry = 5 * time.Second
	}

	missingLogged := false
	for ctx.Err() == nil {
		path, err := FindDevice(sysRoot, devRoot, w.Device)
		if err == nil {
			missingLogged = false
			log.Printf("Remote buttons: reading %q at %s", w.Device, path)
			err = w.read(ctx, path)
			if ctx.Err() != nil {
				return
			}
			log.Printf("Remote buttons: %s stopped: %v; looking for it again", path, err)
		} else if !missingLogged {
			log.Printf("Remote buttons: no input device named %q yet; checking every %s", w.Device, retry)
			missingLogged = true
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(retry):
		}
	}
}

func (w *Watcher) read(ctx context.Context, path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	// Closing the file is the only way to unblock a pending read.
	stop := context.AfterFunc(ctx, func() { f.Close() })
	defer stop()
	defer f.Close()
	return w.consume(f)
}

// consume reads events until the reader fails. A key still held when the
// device goes away stops repeating; no release is invented for it.
func (w *Watcher) consume(r io.Reader) error {
	rep := newRepeater(w.RepeatDelay, w.RepeatInterval, w.Emit)
	defer rep.stopAll()
	buf := make([]byte, eventSize)
	for {
		if _, err := io.ReadFull(r, buf); err != nil {
			return err
		}
		typ, code, value := decode(buf)
		if ev, ok := Translate(w.Keys, typ, code, value); ok {
			rep.handle(ev)
		}
	}
}
