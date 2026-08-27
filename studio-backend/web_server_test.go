package main

import (
	"errors"
	"net/http"
	"net/http/httptest"
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
