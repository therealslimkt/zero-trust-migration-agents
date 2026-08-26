package main

import (
	"bytes"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestIsOriginAllowed_DefaultLocalhostOrigins(t *testing.T) {
	allowed := defaultAllowedOrigins

	cases := []struct {
		name   string
		origin string
		want   bool
	}{
		{"localhost 3000 allowed", "http://localhost:3000", true},
		{"localhost 5173 allowed", "http://localhost:5173", true},
		{"127.0.0.1 3000 allowed", "http://127.0.0.1:3000", true},
		{"127.0.0.1 5173 allowed", "http://127.0.0.1:5173", true},
		{"unlisted https origin denied", "https://evil.example.com", false},
		{"unlisted localhost port denied", "http://localhost:9999", false},
		{"missing origin denied", "", false},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := isOriginAllowed(c.origin, allowed)
			if got != c.want {
				t.Errorf("isOriginAllowed(%q) = %v, want %v", c.origin, got, c.want)
			}
		})
	}
}

func TestAllowedOrigins_DefaultsWhenEnvUnset(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	got := allowedOrigins()
	if len(got) != len(defaultAllowedOrigins) {
		t.Fatalf("expected %d default origins, got %v", len(defaultAllowedOrigins), got)
	}
	for i, o := range defaultAllowedOrigins {
		if got[i] != o {
			t.Errorf("allowedOrigins()[%d] = %q, want %q", i, got[i], o)
		}
	}
}

func TestAllowedOrigins_ConfiguredOverrideReplacesDefaults(t *testing.T) {
	t.Setenv("MISSION_CONTROL_ALLOWED_ORIGINS", "https://app.example.com, https://admin.example.com")

	got := allowedOrigins()

	if !isOriginAllowed("https://app.example.com", got) {
		t.Errorf("expected configured origin https://app.example.com to be allowed")
	}
	if !isOriginAllowed("https://admin.example.com", got) {
		t.Errorf("expected configured origin https://admin.example.com to be allowed")
	}
	if isOriginAllowed("http://localhost:3000", got) {
		t.Errorf("expected default localhost origin to be excluded once explicit config is set")
	}
}

func TestWebSocketUpgraderCheckOrigin_DeniesUnlistedOrigin(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	req := httptest.NewRequest("GET", "/ws", nil)
	req.Header.Set("Origin", "https://evil.example.com")

	if upgrader.CheckOrigin(req) {
		t.Errorf("expected disallowed origin to be rejected by the websocket upgrader")
	}
}

func TestWebSocketUpgraderCheckOrigin_AllowsDefaultLocalhost(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	req := httptest.NewRequest("GET", "/ws", nil)
	req.Header.Set("Origin", "http://localhost:5173")

	if !upgrader.CheckOrigin(req) {
		t.Errorf("expected default localhost origin to be allowed by the websocket upgrader")
	}
}

func TestWebSocketUpgraderCheckOrigin_DeniesMissingOrigin(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	req := httptest.NewRequest("GET", "/ws", nil)

	if upgrader.CheckOrigin(req) {
		t.Errorf("expected a request with no Origin header to be denied")
	}
}

func TestIsLoopbackRemoteAddr(t *testing.T) {
	cases := []struct {
		name       string
		remoteAddr string
		want       bool
	}{
		{"ipv4 loopback with port", "127.0.0.1:54321", true},
		{"ipv6 loopback with port", "[::1]:54321", true},
		{"ipv4 loopback without port", "127.0.0.1", true},
		{"non-loopback with port", "10.0.0.5:54321", false},
		{"non-loopback without port", "203.0.113.9", false},
		{"empty", "", false},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := isLoopbackRemoteAddr(c.remoteAddr)
			if got != c.want {
				t.Errorf("isLoopbackRemoteAddr(%q) = %v, want %v", c.remoteAddr, got, c.want)
			}
		})
	}
}

func TestHandleStatusPost_AllowsAbsentOriginFromLoopback(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	body := []byte(`{"agent":"m2m","status":"ok","message":"health"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/status", bytes.NewReader(body))
	req.RemoteAddr = "127.0.0.1:54321"
	rec := httptest.NewRecorder()

	go func() {
		<-broadcast
	}()

	handleStatusPost(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected loopback machine-to-machine POST with no Origin to be allowed, got status %d", rec.Code)
	}
}

func TestHandleStatusPost_DeniesAbsentOriginFromNonLoopback(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	body := []byte(`{"agent":"m2m","status":"ok","message":"health"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/status", bytes.NewReader(body))
	req.RemoteAddr = "10.0.0.5:54321"
	rec := httptest.NewRecorder()

	handleStatusPost(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("expected non-loopback POST with no Origin to be denied, got status %d", rec.Code)
	}
}

func TestHandleStatusPost_DeniesUnlistedOriginRegardlessOfRemoteAddr(t *testing.T) {
	os.Unsetenv("MISSION_CONTROL_ALLOWED_ORIGINS")

	body := []byte(`{"agent":"browser","status":"ok","message":"health"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/status", bytes.NewReader(body))
	req.RemoteAddr = "127.0.0.1:54321"
	req.Header.Set("Origin", "https://evil.example.com")
	rec := httptest.NewRecorder()

	handleStatusPost(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("expected unlisted Origin to be denied even from loopback, got status %d", rec.Code)
	}
}

func TestConfiguredControlPlaneIsDisabledOrFailsClosed(t *testing.T) {
	t.Setenv("MISSION_CONTROL_STATE_PATH", "")
	t.Setenv("MISSION_CONTROL_API_TOKEN", "")
	handler, err := configuredControlPlane()
	if err != nil || handler != nil {
		t.Fatalf("empty configuration = (%v, %v), want disabled", handler, err)
	}

	t.Setenv("MISSION_CONTROL_STATE_PATH", filepath.Join(t.TempDir(), "state.json"))
	if _, err := configuredControlPlane(); !errors.Is(err, errControlPlaneConfiguration) {
		t.Fatalf("partial state-only configuration error = %v", err)
	}

	t.Setenv("MISSION_CONTROL_STATE_PATH", "")
	t.Setenv("MISSION_CONTROL_API_TOKEN", "token")
	if _, err := configuredControlPlane(); !errors.Is(err, errControlPlaneConfiguration) {
		t.Fatalf("partial token-only configuration error = %v", err)
	}
}

func TestServerMuxMountsAuthenticatedControlPlaneOnlyWhenConfigured(t *testing.T) {
	disabled := httptest.NewRecorder()
	newServerMux(nil).ServeHTTP(
		disabled,
		httptest.NewRequest(http.MethodGet, "/api/v1/migrations/mig_123456789012", nil),
	)
	if disabled.Code != http.StatusNotFound {
		t.Fatalf("disabled API status = %d, want 404", disabled.Code)
	}

	t.Setenv("MISSION_CONTROL_STATE_PATH", filepath.Join(t.TempDir(), "state.json"))
	t.Setenv("MISSION_CONTROL_API_TOKEN", "test-token")
	controlPlane, err := configuredControlPlane()
	if err != nil {
		t.Fatalf("configuredControlPlane: %v", err)
	}
	unauthorized := httptest.NewRecorder()
	newServerMux(controlPlane).ServeHTTP(
		unauthorized,
		httptest.NewRequest(http.MethodGet, "/api/v1/migrations/mig_123456789012", nil),
	)
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("configured API status = %d, want 401", unauthorized.Code)
	}
}
