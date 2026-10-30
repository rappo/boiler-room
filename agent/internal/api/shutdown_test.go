package api

import (
	"context"
	"net"
	"net/http"
	"testing"
	"time"
)

func TestServeUntilCancelledStopsOnContext(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- serveUntilCancelled(ctx, srv, ln) }()

	resp, err := http.Get("http://" + ln.Addr().String() + "/")
	if err != nil {
		t.Fatalf("server not answering: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("status %d", resp.StatusCode)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("clean stop returned %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("server did not stop after context cancellation")
	}
	if _, err := http.Get("http://" + ln.Addr().String() + "/"); err == nil {
		t.Fatal("server still accepting connections after shutdown")
	}
}

func TestServeUntilCancelledReportsListenerFailure(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ln.Close() // Serve on a closed listener fails at once
	srv := &http.Server{Handler: http.NotFoundHandler()}
	if err := serveUntilCancelled(context.Background(), srv, ln); err == nil {
		t.Fatal("expected an error from a dead listener")
	}
}
