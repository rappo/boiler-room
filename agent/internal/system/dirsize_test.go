package system

import (
	"sync"
	"testing"
	"time"
)

func TestDirSizeSamplerCachesAndRefreshesOncePerTTL(t *testing.T) {
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	var mu sync.Mutex
	calls := 0
	done := make(chan struct{}, 10)

	s := &DirSizeSampler{
		path: "/x", ttl: time.Hour,
		now: func() time.Time { mu.Lock(); defer mu.Unlock(); return clock },
		measure: func(string) float64 {
			mu.Lock()
			calls++
			n := calls
			mu.Unlock()
			done <- struct{}{}
			return float64(n) * 10
		},
	}

	if got := s.Get(); got != 0 {
		t.Fatalf("first Get should return 0 before any measurement, got %v", got)
	}
	<-done
	// Give refresh() a moment to store the result after signalling.
	waitFor(t, func() bool { return s.Get() == 10 })

	// Within the TTL: no new measurement, same value.
	for i := 0; i < 5; i++ {
		if got := s.Get(); got != 10 {
			t.Fatalf("cached Get = %v, want 10", got)
		}
	}
	mu.Lock()
	if calls != 1 {
		mu.Unlock()
		t.Fatalf("measure called %d times within ttl, want 1", calls)
	}
	clock = clock.Add(2 * time.Hour)
	mu.Unlock()

	// Past the TTL: returns the old value immediately, measures once more.
	if got := s.Get(); got != 10 {
		t.Fatalf("stale Get should still return old value, got %v", got)
	}
	<-done
	waitFor(t, func() bool { return s.Get() == 20 })
	mu.Lock()
	defer mu.Unlock()
	if calls != 2 {
		t.Fatalf("measure called %d times after ttl, want 2", calls)
	}
}

func TestDirSizeSamplerSingleFlight(t *testing.T) {
	release := make(chan struct{})
	var mu sync.Mutex
	calls := 0
	s := &DirSizeSampler{
		path: "/x", ttl: time.Hour, now: time.Now,
		measure: func(string) float64 {
			mu.Lock()
			calls++
			mu.Unlock()
			<-release
			return 1
		},
	}
	for i := 0; i < 20; i++ {
		s.Get()
	}
	close(release)
	waitFor(t, func() bool { return s.Get() == 1 })
	mu.Lock()
	defer mu.Unlock()
	if calls != 1 {
		t.Fatalf("concurrent stale Gets triggered %d measurements, want 1", calls)
	}
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("condition not met in time")
}
