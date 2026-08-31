package main

import (
	"encoding/json"
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
	t.Setenv("MISSION_CONTROL_LOCAL_DEMO", "")
	t.Setenv("MISSION_CONTROL_WEB_STATE_PATH", "")
	t.Setenv("MISSION_CONTROL_FIRESTORE_PROJECT_ID", "")
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

func TestConfiguredListenAddressHonorsCloudRunPortAndLoopbackDemo(t *testing.T) {
	t.Setenv("MISSION_CONTROL_LOCAL_DEMO", "")
	t.Setenv("PORT", "9090")
	address, err := configuredListenAddress()
	if err != nil || address != ":9090" {
		t.Fatalf("hosted address = %q, %v", address, err)
	}
	t.Setenv("PORT", "not-a-port")
	if _, err := configuredListenAddress(); err == nil {
		t.Fatal("invalid port unexpectedly accepted")
	}
	t.Setenv("MISSION_CONTROL_LOCAL_DEMO", "true")
	address, err = configuredListenAddress()
	if err != nil || address != "127.0.0.1:8080" {
		t.Fatalf("local demo address = %q, %v", address, err)
	}
}

func TestConfiguredLocalDemoBindsExplicitDurableRunsToLoopbackIdentity(t *testing.T) {
	directory := t.TempDir()
	controlPlane, err := NewControlPlaneHandler(filepath.Join(directory, "control.json"), "api-token")
	if err != nil {
		t.Fatal(err)
	}
	cpHandler := controlPlane.(*ControlPlaneHandler)
	run, err := cpHandler.store.CreateRunWithOwnership(webValidCreateRequest(), func(*ControlPlaneRun) error { return nil })
	if err != nil {
		t.Fatal(err)
	}

	t.Setenv("MISSION_CONTROL_LOCAL_DEMO", "true")
	t.Setenv("MISSION_CONTROL_WEB_STATE_PATH", filepath.Join(directory, "web.json"))
	t.Setenv("MISSION_CONTROL_FIREBASE_PROJECT_ID", "")
	t.Setenv("MISSION_CONTROL_LOCAL_DEMO_RUN_IDS", run.RunID)

	handler, err := configuredWebBFF(controlPlane)
	if err != nil {
		t.Fatalf("configuredWebBFF: %v", err)
	}
	request := httptest.NewRequest(http.MethodGet, "/api/web/v1/runs", nil)
	request.Header.Set("Authorization", "Bearer "+localDemoWebToken)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), run.RunID) {
		t.Fatalf("local demo run response = %d %s", response.Code, response.Body.String())
	}
}

func TestConfiguredLocalDemoSeedsExactlyOneTruthfulCreatedRunFromEmptyState(t *testing.T) {
	directory := t.TempDir()
	controlPlane, err := NewControlPlaneHandler(filepath.Join(directory, "control.json"), "api-token")
	if err != nil {
		t.Fatal(err)
	}
	cpHandler := controlPlane.(*ControlPlaneHandler)

	t.Setenv("MISSION_CONTROL_LOCAL_DEMO", "true")
	t.Setenv("MISSION_CONTROL_WEB_STATE_PATH", filepath.Join(directory, "web.json"))
	t.Setenv("MISSION_CONTROL_FIRESTORE_PROJECT_ID", "")
	t.Setenv("MISSION_CONTROL_FIREBASE_PROJECT_ID", "")
	t.Setenv("MISSION_CONTROL_LOCAL_DEMO_RUN_IDS", "")

	handler, err := configuredWebBFF(controlPlane)
	if err != nil {
		t.Fatalf("first configuredWebBFF: %v", err)
	}
	// A restart against both durable files must reuse the ownership binding,
	// not create another portfolio.
	handler, err = configuredWebBFF(controlPlane)
	if err != nil {
		t.Fatalf("second configuredWebBFF: %v", err)
	}

	cpHandler.store.mu.Lock()
	runCount := len(cpHandler.store.snap.Runs)
	eventCount := len(cpHandler.store.snap.Events)
	approvalCount := len(cpHandler.store.snap.Approvals)
	cpHandler.store.mu.Unlock()
	if runCount != 1 || eventCount != 1 || approvalCount != 0 {
		t.Fatalf("seeded durable state runs=%d events=%d approvals=%d", runCount, eventCount, approvalCount)
	}

	request := httptest.NewRequest(http.MethodGet, "/api/web/v1/runs", nil)
	request.Header.Set("Authorization", "Bearer "+localDemoWebToken)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("local demo list response = %d %s", response.Code, response.Body.String())
	}
	var body WebListLiveRunsResponse
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Runs) != 1 {
		t.Fatalf("local demo run count = %d", len(body.Runs))
	}
	run := body.Runs[0]
	if run.PortfolioName != "Local Demo Portfolio" || run.State != WebRunState(ControlPlaneStateCreated) ||
		run.PortfolioPlanDigest != "" || len(run.Sources) != len(cpCanonicalSources) {
		t.Fatalf("seeded run is not truthful initial state: %#v", run)
	}
	for index, source := range run.Sources {
		canonical := cpCanonicalSources[index]
		if string(source.SourceID) != canonical.SourceID || source.Hostname != canonical.Hostname ||
			source.State != WebRunState(ControlPlaneStateCreated) || source.RecordsRead != 0 ||
			source.RecordsWritten != 0 || source.RecordsRejected != 0 || source.PlanDigest != "" ||
			len(source.EvidenceReferences) != 0 {
			t.Fatalf("seeded source %d has fabricated progress: %#v", index, source)
		}
	}
}

func TestLocalDemoVerifierRejectsEveryOtherToken(t *testing.T) {
	verifier := localDemoWebIdentityVerifier{}
	identity, err := verifier.VerifyWebIdentity(t.Context(), localDemoWebToken)
	if err != nil || identity.Subject != "local-demo-operator" {
		t.Fatalf("local identity = %#v, %v", identity, err)
	}
	if _, err := verifier.VerifyWebIdentity(t.Context(), "wrong"); !errors.Is(err, errWebTokenRejected) {
		t.Fatalf("wrong token error = %v", err)
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
