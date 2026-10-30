package api

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestShouldLog(t *testing.T) {
	cases := []struct {
		method string
		status int
		dur    time.Duration
		want   bool
	}{
		{"GET", 200, 40 * time.Millisecond, false},  // routine HA poll
		{"GET", 404, 1 * time.Millisecond, true},    // error
		{"GET", 200, 3800 * time.Millisecond, true}, // slow (the du case)
		{"POST", 200, 1 * time.Millisecond, true},   // every action
		{"OPTIONS", 204, time.Millisecond, true},
	}
	for _, c := range cases {
		if got := shouldLog(c.method, c.status, c.dur); got != c.want {
			t.Errorf("shouldLog(%s, %d, %s) = %v, want %v", c.method, c.status, c.dur, got, c.want)
		}
	}
}

func TestStatusRecorderCapturesImplicit200(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: httptest.NewRecorder()}
	rec.Write([]byte("ok"))
	if rec.status != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.status)
	}
	rec2 := &statusRecorder{ResponseWriter: httptest.NewRecorder()}
	rec2.WriteHeader(http.StatusNotFound)
	if rec2.status != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec2.status)
	}
}

func TestStatusRecorderIsAHijacker(t *testing.T) {
	var w http.ResponseWriter = &statusRecorder{ResponseWriter: httptest.NewRecorder()}
	if _, ok := w.(http.Hijacker); !ok {
		t.Fatal("statusRecorder must implement http.Hijacker or WebSocket upgrades break")
	}
}
