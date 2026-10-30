package system

import (
	"sync"
	"time"
)

// DirSizeSampler caches an expensive directory-size measurement.
//
// /system/sensors is polled every 15 s by Home Assistant, and measuring
// the home directory with du took 3.8 s per call on a Steam machine (so
// a quarter of the time the disk was being walked for one number that
// changes by gigabytes a day at most). Get never blocks: it returns the
// cached value and, when that value is older than ttl, starts one
// background measurement. Until the first measurement finishes it
// returns 0, which the HA sensor shows as unknown.
type DirSizeSampler struct {
	path    string
	ttl     time.Duration
	measure func(path string) float64
	now     func() time.Time

	mu         sync.Mutex
	value      float64
	measuredAt time.Time
	running    bool
}

// NewDirSizeSampler measures path with DirSizeGB at most once per ttl.
func NewDirSizeSampler(path string, ttl time.Duration) *DirSizeSampler {
	return &DirSizeSampler{
		path:    path,
		ttl:     ttl,
		measure: DirSizeGB,
		now:     time.Now,
	}
}

// Get returns the last measured size in GB, refreshing in the background
// when the cached value is stale. Concurrent callers trigger one refresh.
func (s *DirSizeSampler) Get() float64 {
	s.mu.Lock()
	defer s.mu.Unlock()

	stale := s.measuredAt.IsZero() || s.now().Sub(s.measuredAt) >= s.ttl
	if stale && !s.running {
		s.running = true
		go s.refresh()
	}
	return s.value
}

func (s *DirSizeSampler) refresh() {
	v := s.measure(s.path)

	s.mu.Lock()
	s.value = v
	s.measuredAt = s.now()
	s.running = false
	s.mu.Unlock()
}
