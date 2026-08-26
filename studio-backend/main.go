package main

import (
	"encoding/json"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"

	"github.com/gorilla/websocket"
)

// defaultAllowedOrigins is used whenever MISSION_CONTROL_ALLOWED_ORIGINS is
// not set. It restricts browser access to local development origins only.
var defaultAllowedOrigins = []string{
	"http://localhost:3000",
	"http://localhost:5173",
	"http://127.0.0.1:3000",
	"http://127.0.0.1:5173",
}

// allowedOrigins returns the configured origin allowlist, falling back to
// defaultAllowedOrigins when MISSION_CONTROL_ALLOWED_ORIGINS is unset or
// empty after trimming.
func allowedOrigins() []string {
	raw := os.Getenv("MISSION_CONTROL_ALLOWED_ORIGINS")
	if raw == "" {
		return defaultAllowedOrigins
	}
	var origins []string
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			origins = append(origins, part)
		}
	}
	if len(origins) == 0 {
		return defaultAllowedOrigins
	}
	return origins
}

// isOriginAllowed fails closed: an origin is permitted only if it exactly
// (case-insensitively) matches an entry in the configured allowlist. A
// missing or unlisted origin is denied.
func isOriginAllowed(origin string, allowed []string) bool {
	if origin == "" {
		return false
	}
	for _, o := range allowed {
		if strings.EqualFold(o, origin) {
			return true
		}
	}
	return false
}

// isLoopbackRemoteAddr reports whether r.RemoteAddr (a "host:port" pair, as
// set by net/http from the underlying TCP connection and not attacker
// controlled) resolves to a loopback address. Used only to permit
// machine-to-machine calls made from the same host with no Origin header;
// it is never used to authorize a request that presents an Origin.
func isLoopbackRemoteAddr(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return isOriginAllowed(r.Header.Get("Origin"), allowedOrigins())
	},
}

type Message struct {
	Agent   string `json:"agent"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

var (
	clients   = make(map[*websocket.Conn]bool)
	clientsMu sync.Mutex
	broadcast = make(chan Message)
)

var errControlPlaneConfiguration = errors.New("control plane configuration is incomplete")

func configuredControlPlane() (http.Handler, error) {
	statePath := strings.TrimSpace(os.Getenv("MISSION_CONTROL_STATE_PATH"))
	bearerToken := os.Getenv("MISSION_CONTROL_API_TOKEN")
	if statePath == "" && bearerToken == "" {
		return nil, nil
	}
	if statePath == "" || bearerToken == "" {
		return nil, errControlPlaneConfiguration
	}
	return NewControlPlaneHandler(statePath, bearerToken)
}

func newServerMux(controlPlane http.Handler) *http.ServeMux {
	mux := http.NewServeMux()
	if controlPlane != nil {
		mux.Handle("/api/v1/", controlPlane)
	}
	return mux
}

func main() {
	controlPlane, err := configuredControlPlane()
	if err != nil {
		log.Fatal("Mission Control control-plane configuration is invalid")
	}
	mux := newServerMux(controlPlane)

	log.Println("Mission Control Backend started on :8080")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatal("ListenAndServe: ", err)
	}
}

func handleStatusPost(w http.ResponseWriter, r *http.Request) {
	origin := r.Header.Get("Origin")

	if origin == "" {
		// Browsers always send Origin on cross-origin fetch/XHR POSTs, so an
		// absent Origin here means a non-browser, machine-to-machine caller.
		// Allow it only when the call originates from this same host
		// (loopback) — e.g. a sidecar or local health/status poster — since
		// there is no cross-site request forgery risk from a process
		// running on localhost. Every other absent-Origin request is denied,
		// and the WebSocket upgrader never grants this exception.
		if !isLoopbackRemoteAddr(r.RemoteAddr) {
			http.Error(w, "origin not allowed", http.StatusForbidden)
			return
		}
	} else if !isOriginAllowed(origin, allowedOrigins()) {
		http.Error(w, "origin not allowed", http.StatusForbidden)
		return
	} else {
		// CORS for the REST endpoint, scoped to the configured allowlist.
		// This never reflects an arbitrary caller-supplied origin.
		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Vary", "Origin")
	}

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var msg Message
	if err := json.NewDecoder(r.Body).Decode(&msg); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// Send to broadcast channel
	broadcast <- msg
	w.WriteHeader(http.StatusOK)
}

func handleConnections(w http.ResponseWriter, r *http.Request) {
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Println("Upgrade error:", err)
		return
	}
	defer ws.Close()

	clientsMu.Lock()
	clients[ws] = true
	clientsMu.Unlock()

	log.Println("New WebSocket client connected")

	// Keep connection alive
	for {
		_, _, err := ws.ReadMessage()
		if err != nil {
			clientsMu.Lock()
			delete(clients, ws)
			clientsMu.Unlock()
			log.Println("Client disconnected")
			break
		}
	}
}

func handleMessages() {
	for {
		msg := <-broadcast

		clientsMu.Lock()
		for client := range clients {
			err := client.WriteJSON(msg)
			if err != nil {
				log.Printf("error: %v", err)
				client.Close()
				delete(clients, client)
			}
		}
		clientsMu.Unlock()
	}
}
