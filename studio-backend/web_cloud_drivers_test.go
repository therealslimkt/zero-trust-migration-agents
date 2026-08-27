package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type webTestVerifier struct{}

func (webTestVerifier) VerifyWebIdentity(_ context.Context, token string) (WebVerifiedIdentity, error) {
	if token != "owner" && token != "other" {
		return WebVerifiedIdentity{}, errors.New("rejected")
	}
	return WebVerifiedIdentity{Subject: token, DisplayName: token, Email: token + "@example.test"}, nil
}

type webTestRuns struct{}

func (webTestRuns) CreateRunWithOwnership(*cpCreateRequest, func(*ControlPlaneRun) error) (*ControlPlaneRun, error) {
	return nil, errors.New("unused")
}
func (webTestRuns) WebRunSnapshot(string) (*ControlPlaneRun, []*ControlPlaneEvent, error) {
	return nil, nil, errors.New("unused")
}
func (webTestRuns) Approval(string) (*ControlPlaneApproval, error) { return nil, errors.New("unused") }
func (webTestRuns) Decide(string, *cpApprovalRequest) (*ControlPlaneApproval, error) {
	return nil, errors.New("unused")
}

type webTestProber struct{ missing []string }

func (p webTestProber) ProbeCloudCapabilities(context.Context, string, string, string) ([]string, error) {
	return append([]string(nil), p.missing...), nil
}

type webBlockingProber struct {
	entered chan struct{}
	release chan struct{}
}

func (p webBlockingProber) ProbeCloudCapabilities(context.Context, string, string, string) ([]string, error) {
	close(p.entered)
	<-p.release
	return nil, nil
}

type webTestResearcher struct{ finding WebDriverResearchFinding }

func (p webTestResearcher) ResearchDrivers(context.Context, WebDriverResearchRequest) (WebDriverResearchFinding, error) {
	return p.finding, nil
}

func webTestHandler(t *testing.T, configure func(*WebBFFConfig)) http.Handler {
	t.Helper()
	store, err := OpenWebStateStore(t.TempDir() + "/web-state.json")
	if err != nil {
		t.Fatal(err)
	}
	cfg := WebBFFConfig{Verifier: webTestVerifier{}, Runs: webTestRuns{}, Store: store, AllowedOrigins: []string{"http://127.0.0.1:5173"}, Now: func() time.Time { return time.Date(2026, 8, 27, 12, 0, 0, 0, time.UTC) }, RunAsync: func(task func()) bool { task(); return true }}
	if configure != nil {
		configure(&cfg)
	}
	handler, err := NewWebBFFHandler(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

func webRequest(t *testing.T, handler http.Handler, method, path, token string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var payload bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&payload).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, path, &payload)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Origin", "http://127.0.0.1:5173")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, req)
	return recorder
}

func TestWebCloudSetupVerificationIsOwnerBoundAndOneTime(t *testing.T) {
	handler := webTestHandler(t, func(cfg *WebBFFConfig) { cfg.CloudProber = webTestProber{} })
	setup := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/setup", "owner", WebCloudSetupRequest{SchemaVersion: WebSchemaVersion, ProjectID: "owner-project1", Region: "us-central1", DatasetPrefix: "owner"})
	if setup.Code != http.StatusCreated {
		t.Fatalf("setup status %d: %s", setup.Code, setup.Body.String())
	}
	var response WebCloudSetupResponse
	if err := json.Unmarshal(setup.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(response.Command, "'")
	if len(parts) < 2 {
		t.Fatal("reviewed command does not carry its non-secret receipt")
	}
	receipt := parts[len(parts)-2]
	foreign := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "other", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: receipt})
	if foreign.Code != http.StatusNotFound {
		t.Fatalf("foreign verify status %d", foreign.Code)
	}
	wrong := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "owner", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: strings.Repeat("a", 64)})
	if wrong.Code != http.StatusConflict {
		t.Fatalf("wrong receipt status %d", wrong.Code)
	}
	verified := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "owner", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: receipt})
	if verified.Code != http.StatusOK {
		t.Fatalf("verify status %d: %s", verified.Code, verified.Body.String())
	}
	var result WebCloudVerifyResponse
	if err := json.Unmarshal(verified.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.Status != "verified" || result.VerifiedAt == "" {
		t.Fatalf("unexpected verification: %#v", result)
	}
	replay := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "owner", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: receipt})
	if replay.Code != http.StatusConflict {
		t.Fatalf("receipt replay status %d", replay.Code)
	}
}

func TestWebCloudReceiptConcurrentRedemptionHasOneWinner(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	handler := webTestHandler(t, func(cfg *WebBFFConfig) { cfg.CloudProber = webBlockingProber{entered: entered, release: release} })
	setup := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/setup", "owner", WebCloudSetupRequest{SchemaVersion: WebSchemaVersion, ProjectID: "owner-project1", Region: "us-central1", DatasetPrefix: "owner"})
	var response WebCloudSetupResponse
	if err := json.Unmarshal(setup.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(response.Command, "'")
	receipt := parts[len(parts)-2]
	firstDone := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		firstDone <- webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "owner", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: receipt})
	}()
	<-entered
	second := webRequest(t, handler, http.MethodPost, "/api/web/v1/cloud/connection/verify", "owner", WebCloudVerifyRequest{SchemaVersion: WebSchemaVersion, SetupID: response.SetupID, Receipt: receipt})
	close(release)
	first := <-firstDone
	if first.Code != http.StatusOK || second.Code != http.StatusConflict {
		t.Fatalf("concurrent statuses first=%d second=%d", first.Code, second.Code)
	}
}

func TestWebDriverResearchAsyncResultAndApprovalRemainOwnerBound(t *testing.T) {
	digest := "sha256:" + strings.Repeat("b", 64)
	finding := WebDriverResearchFinding{Model: "gemini-3.7-flash", EvidenceDigest: digest, Candidates: []WebDriverCandidate{{CandidateID: "drv_candidate01", Coordinates: "vendor:driver:1", Version: "1", OfficialSource: "https://vendor.example.test/driver", Compatibility: "Reported compatible by the research provider.", License: "Vendor", Redistribution: "restricted", Confidence: .8, Caveats: []string{"Vendor download is required."}}}}
	var store *WebStateStore
	handler := webTestHandler(t, func(cfg *WebBFFConfig) { store = cfg.Store; cfg.DriverResearcher = webTestResearcher{finding: finding} })
	now := "2026-08-27T12:00:00.000Z"
	if err := store.PutCloudSetup(WebCloudSetupRecord{SetupID: "setup_12345678", OwnerUID: "owner", ProjectID: "owner-project1", Region: "us-central1", DatasetPrefix: "owner", CommandDigest: "sha256:" + strings.Repeat("a", 64), ReceiptSHA256: strings.Repeat("c", 64), Status: webCloudSetupVerified, CreatedAt: now, ExpiresAt: "2026-08-27T13:00:00.000Z", VerifiedAt: now}); err != nil {
		t.Fatal(err)
	}
	request := WebDriverResearchRequest{SchemaVersion: WebSchemaVersion, ProjectID: "owner-project1", DatabaseFamily: "Btrieve", DatabaseVersion: "6.15", ApplicationLayer: "Sage", JavaRuntime: "17", ConnectivityMode: "tailscale"}
	created := webRequest(t, handler, http.MethodPost, "/api/web/v1/drivers/research", "owner", request)
	if created.Code != http.StatusAccepted {
		t.Fatalf("research status %d: %s", created.Code, created.Body.String())
	}
	var accepted WebDriverResearchAccepted
	if err := json.Unmarshal(created.Body.Bytes(), &accepted); err != nil {
		t.Fatal(err)
	}
	if created.Header().Get("Location") != accepted.StatusLocation {
		t.Fatalf("Location header %q does not match %q", created.Header().Get("Location"), accepted.StatusLocation)
	}
	status := webRequest(t, handler, http.MethodGet, accepted.StatusLocation, "owner", nil)
	if status.Code != http.StatusOK || !strings.Contains(status.Body.String(), `"status":"completed"`) {
		t.Fatalf("status response: %d %s", status.Code, status.Body.String())
	}
	foreign := webRequest(t, handler, http.MethodGet, accepted.StatusLocation, "other", nil)
	if foreign.Code != http.StatusNotFound {
		t.Fatalf("foreign status %d", foreign.Code)
	}
	approved := webRequest(t, handler, http.MethodPost, accepted.StatusLocation+"/approval", "owner", WebDriverApprovalRequest{SchemaVersion: WebSchemaVersion, ResearchID: accepted.ResearchID, CandidateID: finding.Candidates[0].CandidateID, EvidenceDigest: digest})
	if approved.Code != http.StatusOK || !strings.Contains(approved.Body.String(), `"retrievalMode":"manual_vendor_upload"`) || !strings.Contains(approved.Body.String(), `"status":"pending_upload"`) {
		t.Fatalf("approval response: %d %s", approved.Code, approved.Body.String())
	}
}

func TestWebStoreFailsInterruptedResearchOnRestart(t *testing.T) {
	path := t.TempDir() + "/web-state.json"
	store, err := OpenWebStateStore(path)
	if err != nil {
		t.Fatal(err)
	}
	now := "2026-08-27T12:00:00.000Z"
	record := WebDriverResearchRecord{ResearchID: "research_12345678", OwnerUID: "owner", Status: webResearchRunning, Request: WebDriverResearchRequest{SchemaVersion: WebSchemaVersion, ProjectID: "owner-project1", DatabaseFamily: "Btrieve", DatabaseVersion: "6.15", ApplicationLayer: "Sage", JavaRuntime: "17", ConnectivityMode: "tailscale"}, CreatedAt: now, UpdatedAt: now}
	if err := store.CreateDriverResearch(record); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenWebStateStore(path)
	if err != nil {
		t.Fatal(err)
	}
	recovered, ok := reopened.DriverResearch("owner", record.ResearchID)
	if !ok || recovered.Status != webResearchFailed || recovered.FailureCode != "DRIVER_RESEARCH_INTERRUPTED" {
		t.Fatalf("recovered research %#v, %v", recovered, ok)
	}
}
