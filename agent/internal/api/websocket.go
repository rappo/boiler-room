package api

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// WSHub manages WebSocket connections and broadcasts state changes.
type WSHub struct {
	mu          sync.RWMutex
	clients     map[*wsClient]bool
	broadcast   chan StateEvent
	register    chan *wsClient
	unregister  chan *wsClient
	upgrader    websocket.Upgrader
}

// StateEvent is a real-time state update pushed to connected clients.
type StateEvent struct {
	Type      string      `json:"type"`      // "state_changed", "game_launched", "game_stopped", "volume_changed", etc.
	Timestamp int64       `json:"timestamp"` // Unix timestamp
	Data      interface{} `json:"data"`
}

type wsClient struct {
	hub  *WSHub
	conn *websocket.Conn
	send chan []byte
}

// NewWSHub creates a new WebSocket hub.
func NewWSHub() *WSHub {
	hub := &WSHub{
		clients:    make(map[*wsClient]bool),
		broadcast:  make(chan StateEvent, 64),
		register:   make(chan *wsClient),
		unregister: make(chan *wsClient),
		upgrader: websocket.Upgrader{
			ReadBufferSize:  1024,
			WriteBufferSize: 1024,
			CheckOrigin:     func(r *http.Request) bool { return true }, // Allow all origins
		},
	}
	go hub.run()
	return hub
}

// run processes hub events.
func (h *WSHub) run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			log.Printf("WebSocket: client connected (%d total)", len(h.clients))

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
			h.mu.Unlock()
			log.Printf("WebSocket: client disconnected (%d total)", len(h.clients))

		case event := <-h.broadcast:
			data, err := json.Marshal(event)
			if err != nil {
				log.Printf("WebSocket: failed to marshal event: %v", err)
				continue
			}

			h.mu.RLock()
			for client := range h.clients {
				select {
				case client.send <- data:
				default:
					// Client buffer full — disconnect
					h.mu.RUnlock()
					h.mu.Lock()
					delete(h.clients, client)
					close(client.send)
					h.mu.Unlock()
					h.mu.RLock()
				}
			}
			h.mu.RUnlock()
		}
	}
}

// Broadcast sends a state event to all connected clients.
func (h *WSHub) Broadcast(event StateEvent) {
	if event.Timestamp == 0 {
		event.Timestamp = time.Now().Unix()
	}
	select {
	case h.broadcast <- event:
	default:
		log.Println("WebSocket: broadcast channel full, dropping event")
	}
}

// ClientCount returns the number of connected WebSocket clients.
func (h *WSHub) ClientCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

// HandleWebSocket upgrades an HTTP connection to WebSocket.
func (h *WSHub) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := h.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket: upgrade failed: %v", err)
		return
	}

	client := &wsClient{
		hub:  h,
		conn: conn,
		send: make(chan []byte, 256),
	}

	h.register <- client

	// Writer goroutine
	go func() {
		defer func() {
			conn.Close()
			h.unregister <- client
		}()

		for msg := range client.send {
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		}
	}()

	// Reader goroutine (just reads to detect close)
	go func() {
		defer func() {
			h.unregister <- client
			conn.Close()
		}()

		conn.SetReadLimit(512)
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		conn.SetPongHandler(func(string) error {
			conn.SetReadDeadline(time.Now().Add(60 * time.Second))
			return nil
		})

		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				return
			}
		}
	}()
}
