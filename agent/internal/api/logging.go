package api

import (
	"bufio"
	"errors"
	"log"
	"net"
	"net/http"
	"time"
)

// slowRequest is the duration above which a successful GET is still logged.
const slowRequest = time.Second

// shouldLog decides whether a finished request earns a journal line.
//
// Home Assistant polls six GET endpoints every 15 s. Logging each one
// wrote about 35k lines a day to the user journal and pushed the lines
// that matter (power state transitions, launch results) out of it. So:
// every non-GET, every error, and any slow request is logged; routine
// successful GETs are not.
func shouldLog(method string, status int, dur time.Duration) bool {
	return method != http.MethodGet || status >= 400 || dur >= slowRequest
}

// statusRecorder captures the status code written by a handler.
// It passes Hijack through because gorilla/websocket type-asserts
// http.Hijacker on the writer it is handed.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(b []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	return r.ResponseWriter.Write(b)
}

func (r *statusRecorder) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	h, ok := r.ResponseWriter.(http.Hijacker)
	if !ok {
		return nil, nil, errors.New("underlying ResponseWriter does not support hijacking")
	}
	return h.Hijack()
}

func (r *statusRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// Unwrap lets http.ResponseController reach the real writer.
func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

func (s *Server) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)
		dur := time.Since(start)
		status := rec.status
		if status == 0 {
			status = http.StatusOK // handler wrote nothing (e.g. hijacked WebSocket)
		}
		if shouldLog(r.Method, status, dur) {
			log.Printf("%s %s %d %s", r.Method, r.URL.Path, status, dur)
		}
	})
}
