package remote

import (
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func rawEvent(typ, code uint16, value int32) []byte {
	b := make([]byte, eventSize)
	binary.LittleEndian.PutUint16(b[16:], typ)
	binary.LittleEndian.PutUint16(b[18:], code)
	binary.LittleEndian.PutUint32(b[20:], uint32(value))
	return b
}

func TestParseKeys(t *testing.T) {
	keys, err := ParseKeys(map[string]string{"KEY_F21": "volume_up", "key_f22": "volume_down", "193": "volume_mute"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[uint16]string{191: "volume_up", 192: "volume_down", 193: "volume_mute"}
	for code, button := range want {
		if keys[code] != button {
			t.Errorf("code %d = %q, want %q", code, keys[code], button)
		}
	}
	if _, err := ParseKeys(map[string]string{"KEY_F99": "x"}); err == nil {
		t.Error("an unknown key name must be an error, not a dead button")
	}
	if _, err := ParseKeys(map[string]string{"KEY_F21": " "}); err == nil {
		t.Error("a key with no button name must be an error")
	}
}

func TestTranslate(t *testing.T) {
	keys := map[uint16]string{191: "volume_up"}
	cases := []struct {
		typ, code uint16
		value     int32
		want      Event
		ok        bool
	}{
		{evKey, 191, 1, Event{"volume_up", "press"}, true},
		{evKey, 191, 2, Event{"volume_up", "repeat"}, true},
		{evKey, 191, 0, Event{"volume_up", "release"}, true},
		{evKey, 192, 1, Event{}, false}, // not configured
		{0, 191, 1, Event{}, false},     // EV_SYN, not a key
		{4, 191, 1, Event{}, false},     // EV_MSC scan code
	}
	for _, c := range cases {
		got, ok := Translate(keys, c.typ, c.code, c.value)
		if ok != c.ok || got != c.want {
			t.Errorf("Translate(%d,%d,%d) = %v,%v want %v,%v", c.typ, c.code, c.value, got, ok, c.want, c.ok)
		}
	}
}

func TestConsumeEmitsConfiguredKeysOnly(t *testing.T) {
	var stream bytes.Buffer
	stream.Write(rawEvent(4, 4, 0xc00e9)) // MSC_SCAN before the key, as real devices send
	stream.Write(rawEvent(evKey, 191, 1))
	stream.Write(rawEvent(0, 0, 0)) // SYN_REPORT
	stream.Write(rawEvent(evKey, 30, 1))
	stream.Write(rawEvent(evKey, 191, 2))
	stream.Write(rawEvent(evKey, 191, 0))

	var got []Event
	// A long repeat delay: the kernel repeat in the stream must be dropped and
	// no synthetic one can fire before the release.
	w := &Watcher{Keys: map[uint16]string{191: "volume_up"}, Emit: func(e Event) { got = append(got, e) }, RepeatDelay: time.Hour}
	if err := w.consume(&stream); err != io.EOF {
		t.Fatalf("consume ended with %v, want EOF", err)
	}
	want := []Event{{"volume_up", "press"}, {"volume_up", "release"}}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("event %d = %v, want %v", i, got[i], want[i])
		}
	}
}

func fakeSys(t *testing.T, names map[string]string) string {
	t.Helper()
	root := t.TempDir()
	for node, name := range names {
		dir := filepath.Join(root, "class", "input", node, "device")
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "name"), []byte(name+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestFindDevice(t *testing.T) {
	sys := fakeSys(t, map[string]string{
		"event13":  "  AirMouse Consumer Control",
		"event260": "input-remapper keyboard",
		"event9":   "input-remapper keyboard",
	})
	got, err := FindDevice(sys, "/dev", "input-remapper keyboard")
	if err != nil {
		t.Fatal(err)
	}
	if got != "/dev/input/event9" {
		t.Errorf("got %s, want the lowest-numbered match /dev/input/event9", got)
	}
	// Names are compared trimmed: the Rii pads its name with spaces.
	if got, _ := FindDevice(sys, "/dev", "AirMouse Consumer Control"); got != "/dev/input/event13" {
		t.Errorf("trimmed name lookup got %s", got)
	}
	if _, err := FindDevice(sys, "/dev", "nope"); err == nil {
		t.Error("a missing device must be an error")
	}
}

// The watcher reopens the device after it disappears and stops on cancel.
func TestRunReopensAndStops(t *testing.T) {
	root := t.TempDir()
	sys := fakeSys(t, map[string]string{"event5": "remote"})
	dev := filepath.Join(root, "dev")
	if err := os.MkdirAll(filepath.Join(dev, "input"), 0o755); err != nil {
		t.Fatal(err)
	}
	node := filepath.Join(dev, "input", "event5")
	// A plain file reads to EOF, which the watcher treats like the device
	// going away: it must look again and read the new contents.
	if err := os.WriteFile(node, rawEvent(evKey, 191, 1), 0o644); err != nil {
		t.Fatal(err)
	}

	events := make(chan Event, 64)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	w := &Watcher{Device: "remote", Keys: map[uint16]string{191: "volume_up"}, Emit: func(e Event) { events <- e },
		SysRoot: sys, DevRoot: dev, Retry: 10 * time.Millisecond}
	go func() { w.Run(ctx); close(done) }()

	select {
	case e := <-events:
		if e != (Event{"volume_up", "press"}) {
			t.Fatalf("first event %v", e)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no event from the device")
	}
	if err := os.WriteFile(node, rawEvent(evKey, 191, 0), 0o644); err != nil {
		t.Fatal(err)
	}
	deadline := time.After(2 * time.Second)
	for {
		select {
		case e := <-events:
			if e.Action == "release" {
				cancel()
				select {
				case <-done:
					return
				case <-time.After(2 * time.Second):
					t.Fatal("Run did not stop after cancel")
				}
			}
		case <-deadline:
			t.Fatal("the reopened device was not read")
		}
	}
}

type recorder struct {
	mu     sync.Mutex
	events []Event
}

func (r *recorder) emit(e Event) { r.mu.Lock(); r.events = append(r.events, e); r.mu.Unlock() }
func (r *recorder) get() []Event {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]Event(nil), r.events...)
}

func count(events []Event, action string) int {
	n := 0
	for _, e := range events {
		if e.Action == action {
			n++
		}
	}
	return n
}

// The Rii sends no kernel repeats: a held key must repeat by itself.
func TestHeldKeyRepeatsUntilRelease(t *testing.T) {
	var rec recorder
	rep := newRepeater(40*time.Millisecond, 20*time.Millisecond, rec.emit)
	rep.handle(Event{"volume_up", "press"})
	time.Sleep(150 * time.Millisecond)
	rep.handle(Event{"volume_up", "release"})
	got := rec.get()
	if got[0] != (Event{"volume_up", "press"}) || got[len(got)-1] != (Event{"volume_up", "release"}) {
		t.Fatalf("want press first and release last, got %v", got)
	}
	if n := count(got, "repeat"); n < 3 || n > 7 {
		t.Errorf("150 ms hold with 40 ms delay and 20 ms interval gave %d repeats, want about 5", n)
	}
	time.Sleep(60 * time.Millisecond)
	if after := rec.get(); len(after) != len(got) {
		t.Errorf("repeats continued after release: %v", after[len(got):])
	}
}

func TestQuickTapDoesNotRepeat(t *testing.T) {
	var rec recorder
	rep := newRepeater(100*time.Millisecond, 20*time.Millisecond, rec.emit)
	rep.handle(Event{"volume_down", "press"})
	rep.handle(Event{"volume_down", "release"})
	time.Sleep(150 * time.Millisecond)
	if got := rec.get(); count(got, "repeat") != 0 || len(got) != 2 {
		t.Errorf("a tap must be press and release only, got %v", got)
	}
}

func TestKernelRepeatsAreDropped(t *testing.T) {
	var rec recorder
	rep := newRepeater(time.Hour, time.Hour, rec.emit)
	rep.handle(Event{"volume_up", "press"})
	rep.handle(Event{"volume_up", "repeat"})
	rep.handle(Event{"volume_up", "release"})
	if got := rec.get(); count(got, "repeat") != 0 {
		t.Errorf("kernel repeat passed through: %v", got)
	}
}

// The device vanishing mid-hold (input-remapper reloading) must stop the repeats.
func TestStopAllEndsHeldKeys(t *testing.T) {
	var rec recorder
	rep := newRepeater(10*time.Millisecond, 10*time.Millisecond, rec.emit)
	rep.handle(Event{"volume_up", "press"})
	rep.handle(Event{"volume_down", "press"})
	time.Sleep(40 * time.Millisecond)
	rep.stopAll()
	n := len(rec.get())
	time.Sleep(40 * time.Millisecond)
	if len(rec.get()) != n {
		t.Error("repeats continued after stopAll")
	}
}

// Release racing a due repeat: the release must always be the last event.
func TestReleaseIsAlwaysLast(t *testing.T) {
	for i := 0; i < 200; i++ {
		var rec recorder
		rep := newRepeater(time.Millisecond, time.Millisecond, rec.emit)
		rep.handle(Event{"volume_up", "press"})
		time.Sleep(time.Duration(i%5) * time.Millisecond)
		rep.handle(Event{"volume_up", "release"})
		rep.stopAll()
		got := rec.get()
		if got[len(got)-1].Action != "release" {
			t.Fatalf("run %d: event after release: %v", i, got[len(got)-3:])
		}
	}
}
