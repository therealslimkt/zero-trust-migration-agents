package main

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func webValidCreateRequest() *cpCreateRequest {
	sources := make([]cpSourceDescriptor, 0, len(cpCanonicalSources))
	for _, source := range cpCanonicalSources {
		sources = append(sources, cpSourceDescriptor{SourceID: source.SourceID, Hostname: source.Hostname})
	}
	return &cpCreateRequest{SchemaVersion: cpSchemaVersion, PortfolioName: "webatomicportfolio", Sources: sources, RequestedBy: "web_testactor"}
}

func TestWebRunOwnershipPrecommitFailureLeavesNoControlPlaneRun(t *testing.T) {
	store, err := cpOpenStore(t.TempDir() + "/control-plane.json")
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.CreateRunWithOwnership(webValidCreateRequest(), func(*ControlPlaneRun) error { return errors.New("binding failed") })
	if err == nil {
		t.Fatal("expected binding failure")
	}
	store.mu.Lock()
	count := len(store.snap.Runs)
	events := len(store.snap.Events)
	store.mu.Unlock()
	if count != 0 || events != 0 {
		t.Fatalf("failed precommit left %d runs and %d events", count, events)
	}
}

func TestServerMuxMountsWebBFFOnlyUnderWebPrefix(t *testing.T) {
	web := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/web/v1/demos" {
			t.Fatalf("unexpected path %q", r.URL.Path)
		}
		w.WriteHeader(http.StatusNoContent)
	})
	mux := newServerMuxWithWeb(nil, nil, web)
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/web/v1/demos", nil))
	if recorder.Code != http.StatusNoContent {
		t.Fatalf("web status %d", recorder.Code)
	}
	recorder = httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/runs", nil))
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("frozen API unexpectedly mounted: %d", recorder.Code)
	}
}

func TestConfiguredWebBFFRequiresCompleteConfiguration(t *testing.T) {
	t.Setenv("MISSION_CONTROL_WEB_STATE_PATH", "")
	t.Setenv("MISSION_CONTROL_FIREBASE_PROJECT_ID", "")
	handler, err := configuredWebBFF(nil)
	if err != nil || handler != nil {
		t.Fatalf("disabled web BFF = %#v, %v", handler, err)
	}
	t.Setenv("MISSION_CONTROL_WEB_STATE_PATH", t.TempDir()+"/state.json")
	if _, err := configuredWebBFF(nil); err != errWebBFFConfiguration {
		t.Fatalf("partial config error = %v", err)
	}
}

func TestWebSPAServesHistoryFallbackWithoutCapturingAPIs(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "assets"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "index.html"), []byte("<main>studio</main>"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "assets", "app-hash.js"), []byte("export{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	site, err := newWebSPAHandler(root)
	if err != nil {
		t.Fatal(err)
	}
	api := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
	mux := newServerMuxWithSite(api, nil, nil, site)
	for _, path := range []string{"/", "/demo/demo_12345678", "/dashboard"} {
		recorder := httptest.NewRecorder()
		mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != http.StatusOK || recorder.Body.String() != "<main>studio</main>" {
			t.Fatalf("%s => %d %q", path, recorder.Code, recorder.Body.String())
		}
	}
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/assets/app-hash.js", nil))
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Header().Get("Cache-Control"), "immutable") {
		t.Fatalf("asset response %d %q", recorder.Code, recorder.Header().Get("Cache-Control"))
	}
	recorder = httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/runs", nil))
	if recorder.Code != http.StatusNoContent {
		t.Fatalf("API captured by SPA: %d", recorder.Code)
	}
}
