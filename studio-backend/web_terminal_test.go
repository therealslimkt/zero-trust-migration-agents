package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const (
	webTerminalTestRun   = "mig_terminalrun001"
	webTerminalOtherRun  = "mig_terminalrun002"
	webTerminalTimestamp = "2026-08-27T12:00:00.000Z"
	webTerminalTestToken = "terminal-producer-token-test"
)

func webTerminalTestOwnership(runID, owner string) WebRunOwnershipRecord {
	return WebRunOwnershipRecord{
		RunID: runID, OwnerUID: owner, PortfolioName: "Terminal test",
		Owner:     WebIdentitySummary{Subject: owner, DisplayName: owner, Email: owner + "@example.test"},
		CreatedAt: webTerminalTimestamp,
	}
}

func webTerminalTestAdmission(runID string, sourceID WebSourceID, lane WebTerminalLane, line string) WebTerminalFrameAdmission {
	return WebTerminalFrameAdmission{
		RunID: runID, SourceID: sourceID, Timestamp: webTerminalTimestamp,
		Lane: lane, Stream: "stdout", Producer: "migration-worker", Tool: "jdbc-inspector",
		Line: line, Severity: "info", EvidenceReferences: []WebEvidenceReference{},
	}
}

func webTerminalTestStore(t *testing.T) (*WebStateStore, string) {
	t.Helper()
	statePath := filepath.Join(t.TempDir(), "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	for _, runID := range []string{webTerminalTestRun, webTerminalOtherRun} {
		if err := store.PutRunOwnership(webTerminalTestOwnership(runID, "owner")); err != nil {
			t.Fatal(err)
		}
	}
	return store, statePath
}

func TestWebTerminalAdmissionPersistsExactLinesAndSequences(t *testing.T) {
	store, statePath := webTerminalTestStore(t)
	line := `$ java -jar driver.jar --mode=inventory --limit=25`
	first, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "source", line))
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "maxdb", "source", "connected to SAP MaxDB"))
	if err != nil {
		t.Fatal(err)
	}
	third, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "read 25 rows"))
	if err != nil {
		t.Fatal(err)
	}
	fourth, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "compiler", "compiled 8 transforms"))
	if err != nil {
		t.Fatal(err)
	}
	if first.Line != line || first.GlobalSequence != 1 || first.LaneSequence != 1 ||
		second.GlobalSequence != 2 || second.LaneSequence != 1 || third.GlobalSequence != 3 || third.LaneSequence != 2 ||
		fourth.GlobalSequence != 4 || fourth.LaneSequence != 1 {
		t.Fatalf("unexpected exact frame sequences: %#v %#v %#v %#v", first, second, third, fourth)
	}

	replay, err := store.TerminalFramesAfter(webTerminalTestRun, "jde", first.FrameID, webMaxSSEReplay)
	if err != nil {
		t.Fatal(err)
	}
	if len(replay) != 2 || replay[0].FrameID != third.FrameID || replay[1].FrameID != fourth.FrameID {
		t.Fatalf("source replay = %#v", replay)
	}
	restarted, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	replay, err = restarted.TerminalFramesAfter(webTerminalTestRun, "jde", "", webMaxSSEReplay)
	if err != nil || len(replay) != 3 || replay[0].Line != line {
		t.Fatalf("restart replay = %#v, %v", replay, err)
	}
}

func TestWebTerminalAdmissionSuppressesCredentialsAndReasoningBeforePersistence(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	lines := []string{
		"Authorization: Bearer secret-value-1234567890",
		"MISSION_CONTROL_API_TOKEN=secret-value-1234567890",
		"private_key: -----BEGIN PRIVATE KEY-----",
		"internal reasoning: first inspect the hidden scratchpad",
		"<think>private deliberation</think>",
	}
	for _, line := range lines {
		_, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "compiler", line))
		if !errors.Is(err, ErrWebTerminalFrameSuppressed) || strings.Contains(err.Error(), "secret-value") {
			t.Fatalf("line was not safely suppressed: %q => %v", line, err)
		}
	}
	invalid := webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "two\nlines")
	if _, err := store.AdmitTerminalFrame(invalid); !errors.Is(err, ErrWebTerminalFrameRejected) {
		t.Fatalf("unsafe line error = %v", err)
	}
	frames, err := store.TerminalFramesAfter(webTerminalTestRun, "jde", "", webMaxSSEReplay)
	if err != nil || len(frames) != 0 {
		t.Fatalf("suppressed content reached persistence: %#v, %v", frames, err)
	}

	withoutEvidenceSlice := webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "inventory started")
	withoutEvidenceSlice.Stream = "system"
	withoutEvidenceSlice.EvidenceReferences = nil
	frame, err := store.AdmitTerminalFrame(withoutEvidenceSlice)
	if err != nil || frame.EvidenceReferences == nil {
		t.Fatalf("nil producer evidence was not normalized to a closed empty array: %#v, %v", frame, err)
	}
}

func TestWebTerminalRestartRejectsCredentialTampering(t *testing.T) {
	store, statePath := webTerminalTestStore(t)
	if _, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "safe line")); err != nil {
		t.Fatal(err)
	}
	store.mu.Lock()
	store.snap.TerminalFrames[0].Line = "password=hunter2"
	raw, err := json.Marshal(store.snap)
	store.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(statePath, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenWebStateStore(statePath); err == nil {
		t.Fatal("restart accepted credential-bearing terminal tampering")
	}
}

func TestWebTerminalConcurrentAdmissionMaintainsContiguousSequences(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	const count = 24
	errs := make(chan error, count)
	var group sync.WaitGroup
	for index := 0; index < count; index++ {
		group.Add(1)
		go func(index int) {
			defer group.Done()
			_, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "edge", fmt.Sprintf("processed batch %d", index)))
			errs <- err
		}(index)
	}
	group.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	frames, err := store.TerminalFramesAfter(webTerminalTestRun, "jde", "", webMaxSSEReplay)
	if err != nil || len(frames) != count {
		t.Fatalf("frames = %d, %v", len(frames), err)
	}
	seen := make(map[string]bool, count)
	for index, frame := range frames {
		want := int64(index + 1)
		if frame.GlobalSequence != want || frame.LaneSequence != want || seen[frame.FrameID] {
			t.Fatalf("non-contiguous or duplicate frame at %d: %#v", index, frame)
		}
		seen[frame.FrameID] = true
	}
}

type webTerminalRunBackend struct {
	runs map[string]*ControlPlaneRun
}

func (webTerminalRunBackend) CreateRunWithOwnership(*cpCreateRequest, func(*ControlPlaneRun) error) (*ControlPlaneRun, error) {
	return nil, errors.New("unused")
}
func (backend webTerminalRunBackend) WebRunSnapshot(runID string) (*ControlPlaneRun, []*ControlPlaneEvent, error) {
	run := backend.runs[runID]
	if run == nil {
		return nil, nil, errors.New("missing")
	}
	copy := *run
	copy.Sources = append([]ControlPlaneSource(nil), run.Sources...)
	return &copy, []*ControlPlaneEvent{}, nil
}
func (webTerminalRunBackend) Approval(string) (*ControlPlaneApproval, error) {
	return nil, errors.New("unused")
}
func (webTerminalRunBackend) Decide(string, *cpApprovalRequest) (*ControlPlaneApproval, error) {
	return nil, errors.New("unused")
}

func webTerminalTestHandler(t *testing.T, store *WebStateStore) http.Handler {
	t.Helper()
	run := &ControlPlaneRun{
		RunID: webTerminalTestRun, PortfolioName: "terminal", State: ControlPlaneStateCreated,
		CreatedAt: webTerminalTimestamp, UpdatedAt: webTerminalTimestamp,
		Sources: []ControlPlaneSource{
			{SourceID: "jde", Hostname: "legacy-jde-db", State: ControlPlaneStateCreated},
			{SourceID: "maxdb", Hostname: "legacy-maxdb", State: ControlPlaneStateCreated},
			{SourceID: "btrieve", Hostname: "legacy-btrieve-db", State: ControlPlaneStateCreated},
		},
	}
	handler, err := NewWebBFFHandler(WebBFFConfig{
		Verifier: webTestVerifier{}, Runs: webTerminalRunBackend{runs: map[string]*ControlPlaneRun{run.RunID: run}}, Store: store,
		TerminalProducerToken: webTerminalTestToken,
	})
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

func webTerminalRequest(handler http.Handler, token, sourceID, cursor string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(http.MethodGet, "/api/web/v1/runs/"+webTerminalTestRun+"/sources/"+sourceID+"/terminal", nil)
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	if cursor != "" {
		request.Header.Set("Last-Event-ID", cursor)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func TestWebTerminalSSEIsOwnerScopedTypedAndExactlyResumable(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	first, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "connected"))
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "edge", "redacted 4 fields"))
	if err != nil {
		t.Fatal(err)
	}
	foreignSource, err := store.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "maxdb", "source", "connected"))
	if err != nil {
		t.Fatal(err)
	}
	handler := webTerminalTestHandler(t, store)

	unauthenticated := webTerminalRequest(handler, "", "jde", "")
	foreignOwner := webTerminalRequest(handler, "other", "jde", "")
	if unauthenticated.Code != http.StatusUnauthorized || foreignOwner.Code != http.StatusNotFound {
		t.Fatalf("scope statuses unauth=%d foreign=%d", unauthenticated.Code, foreignOwner.Code)
	}
	full := webTerminalRequest(handler, "owner", "jde", "")
	if full.Code != http.StatusOK || !strings.HasPrefix(full.Header().Get("Content-Type"), "text/event-stream") ||
		strings.Count(full.Body.String(), "event: terminal.frame\n") != 2 || strings.Contains(full.Body.String(), foreignSource.FrameID) {
		t.Fatalf("full SSE = %d %s", full.Code, full.Body.String())
	}
	if !strings.Contains(full.Body.String(), `"frameId":"`+first.FrameID+`"`) || !strings.Contains(full.Body.String(), `"line":"connected"`) {
		t.Fatalf("typed frame missing: %s", full.Body.String())
	}
	resumed := webTerminalRequest(handler, "owner", "jde", first.FrameID)
	if resumed.Code != http.StatusOK || strings.Contains(resumed.Body.String(), first.FrameID) || !strings.Contains(resumed.Body.String(), second.FrameID) {
		t.Fatalf("resumed SSE = %d %s", resumed.Code, resumed.Body.String())
	}
	invalid := webTerminalRequest(handler, "owner", "jde", "evt_migrationcreated01")
	unknown := webTerminalRequest(handler, "owner", "jde", "frm_000000000000")
	crossSource := webTerminalRequest(handler, "owner", "jde", foreignSource.FrameID)
	if invalid.Code != http.StatusBadRequest || unknown.Code != http.StatusNotFound || crossSource.Code != http.StatusNotFound {
		t.Fatalf("cursor statuses invalid=%d unknown=%d cross=%d", invalid.Code, unknown.Code, crossSource.Code)
	}
}

func TestWebTerminalSSEReplayIsBounded(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	store.mu.Lock()
	next, err := store.cloneLocked()
	if err != nil {
		store.mu.Unlock()
		t.Fatal(err)
	}
	for index := 1; index <= webMaxSSEReplay+1; index++ {
		next.TerminalFrames = append(next.TerminalFrames, &WebTerminalFrame{
			SchemaVersion: WebSchemaVersion, FrameID: fmt.Sprintf("frm_%012d", index), RunID: webTerminalTestRun, SourceID: "jde",
			GlobalSequence: int64(index), LaneSequence: int64(index), Timestamp: webTerminalTimestamp,
			Lane: "source", Stream: "stdout", Producer: "worker", Tool: "reader", Line: fmt.Sprintf("row %d", index),
			Severity: "info", EvidenceReferences: []WebEvidenceReference{},
		})
	}
	err = store.commitLocked(next)
	store.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	handler := webTerminalTestHandler(t, store)
	response := webTerminalRequest(handler, "owner", "jde", "")
	if response.Code != http.StatusOK || strings.Count(response.Body.String(), "event: terminal.frame\n") != webMaxSSEReplay ||
		strings.Contains(response.Body.String(), fmt.Sprintf("frm_%012d", webMaxSSEReplay+1)) {
		t.Fatalf("bounded replay status=%d frames=%d", response.Code, strings.Count(response.Body.String(), "event: terminal.frame\n"))
	}
}

func TestWebTerminalSSERejectsDuplicateCursorHeaders(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	handler := webTerminalTestHandler(t, store)
	request := httptest.NewRequest(http.MethodGet, "/api/web/v1/runs/"+webTerminalTestRun+"/sources/jde/terminal", nil)
	request.Header.Set("Authorization", "Bearer owner")
	request.Header.Add("Last-Event-ID", "frm_000000000001")
	request.Header.Add("Last-Event-ID", "frm_000000000002")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("duplicate cursor status = %d", response.Code)
	}
}

func TestWebTerminalAdmissionRejectsMalformedEvidence(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	input := webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "safe line")
	input.EvidenceReferences = []WebEvidenceReference{{ArtifactID: "bad", Kind: "audit_log", Digest: "sha256:" + strings.Repeat("a", 64)}}
	if _, err := store.AdmitTerminalFrame(input); !errors.Is(err, ErrWebTerminalFrameRejected) {
		t.Fatalf("malformed evidence error = %v", err)
	}
}

func TestWebTerminalTimestampMustBeMonotonicPerRun(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	first := webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "first")
	first.Timestamp = "2026-08-27T12:00:01.000Z"
	if _, err := store.AdmitTerminalFrame(first); err != nil {
		t.Fatal(err)
	}
	second := webTerminalTestAdmission(webTerminalTestRun, "maxdb", "source", "second")
	second.Timestamp = "2026-08-27T12:00:00.000Z"
	if _, err := store.AdmitTerminalFrame(second); !errors.Is(err, ErrWebTerminalFrameRejected) {
		t.Fatalf("backdated frame error = %v", err)
	}
}

func webTerminalAdmissionHTTP(t *testing.T, handler http.Handler, token, remoteAddr, origin, line string) *httptest.ResponseRecorder {
	t.Helper()
	body, err := json.Marshal(webTerminalAdmissionRequest{
		SchemaVersion: WebSchemaVersion, RunID: webTerminalTestRun, SourceID: "jde",
		Timestamp: webTerminalTimestamp, Lane: "source", Stream: "stdout",
		Producer: "migration-worker", Tool: "jdbc-inspector", Line: line,
		Severity: "info", EvidenceReferences: []WebEvidenceReference{},
	})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, webTerminalProducerPath, strings.NewReader(string(body)))
	request.RemoteAddr = remoteAddr
	request.Header.Set("Content-Type", "application/json")
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	if origin != "" {
		request.Header.Set("Origin", origin)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func TestWebTerminalProducerAdmissionRequiresSeparateAuthAndLoopback(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	handler := webTerminalTestHandler(t, store)

	unauthenticated := webTerminalAdmissionHTTP(t, handler, "", "127.0.0.1:44000", "", "safe")
	wrongToken := webTerminalAdmissionHTTP(t, handler, "wrong-token", "127.0.0.1:44000", "", "safe")
	remote := webTerminalAdmissionHTTP(t, handler, webTerminalTestToken, "203.0.113.8:44000", "", "safe")
	browser := webTerminalAdmissionHTTP(t, handler, webTerminalTestToken, "127.0.0.1:44000", "https://example.test", "safe")
	if unauthenticated.Code != http.StatusUnauthorized || wrongToken.Code != http.StatusUnauthorized ||
		remote.Code != http.StatusForbidden || browser.Code != http.StatusForbidden {
		t.Fatalf("producer gates unauth=%d wrong=%d remote=%d browser=%d", unauthenticated.Code, wrongToken.Code, remote.Code, browser.Code)
	}
	if browser.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("internal producer route exposed browser CORS: %q", browser.Header().Get("Access-Control-Allow-Origin"))
	}
	frames, err := store.TerminalFramesAfter(webTerminalTestRun, "jde", "", webMaxSSEReplay)
	if err != nil || len(frames) != 0 {
		t.Fatalf("rejected producers persisted frames: %#v, %v", frames, err)
	}
}

func TestWebTerminalProducerPersistsExactFrameAndSuppressesSecret(t *testing.T) {
	store, _ := webTerminalTestStore(t)
	handler := webTerminalTestHandler(t, store)
	line := `$ java -jar migration.jar --source jde`
	created := webTerminalAdmissionHTTP(t, handler, webTerminalTestToken, "[::1]:44000", "", line)
	if created.Code != http.StatusCreated || !strings.HasPrefix(created.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("created response = %d %s", created.Code, created.Body.String())
	}
	var frame WebTerminalFrame
	if err := json.Unmarshal(created.Body.Bytes(), &frame); err != nil || frame.Line != line || frame.GlobalSequence != 1 {
		t.Fatalf("created frame = %#v, %v", frame, err)
	}
	suppressed := webTerminalAdmissionHTTP(t, handler, webTerminalTestToken, "127.0.0.1:44000", "", "MISSION_CONTROL_API_TOKEN=secret-value")
	if suppressed.Code != http.StatusNoContent || suppressed.Body.Len() != 0 {
		t.Fatalf("suppressed response = %d %q", suppressed.Code, suppressed.Body.String())
	}
	frames, err := store.TerminalFramesAfter(webTerminalTestRun, "jde", "", webMaxSSEReplay)
	if err != nil || len(frames) != 1 || frames[0].Line != line {
		t.Fatalf("producer persistence = %#v, %v", frames, err)
	}
}

func TestWebTerminalLegacyV3SnapshotWithoutFramesRestarts(t *testing.T) {
	store, statePath := webTerminalTestStore(t)
	store.mu.Lock()
	raw, err := json.Marshal(store.snap)
	store.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	var legacy map[string]json.RawMessage
	if err := json.Unmarshal(raw, &legacy); err != nil {
		t.Fatal(err)
	}
	delete(legacy, "terminalFrames")
	raw, err = json.Marshal(legacy)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(statePath, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	restarted, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatalf("additive v3 restart failed: %v", err)
	}
	if len(restarted.snap.TerminalFrames) != 0 {
		t.Fatalf("legacy frames were not normalized: %#v", restarted.snap.TerminalFrames)
	}
	if _, err := restarted.AdmitTerminalFrame(webTerminalTestAdmission(webTerminalTestRun, "jde", "source", "restart accepted")); err != nil {
		t.Fatalf("legacy snapshot cannot accept terminal frames: %v", err)
	}
}
