package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const orchestratorTestToken = "test-orchestrator-token"

func orchestratorTestHandler(t *testing.T, target orchestratorTarget) http.Handler {
	t.Helper()
	h, err := newOrchestratorBridgeHandler(target, orchestratorTestToken)
	if err != nil {
		t.Fatalf("newOrchestratorBridgeHandler: %v", err)
	}
	return h
}

func orchestratorTestDo(t *testing.T, h http.Handler, body string) *httptest.ResponseRecorder {
	t.Helper()
	return orchestratorTestDoAs(t, h, body, "Bearer "+orchestratorTestToken, "127.0.0.1:41000")
}

func orchestratorTestDoAs(t *testing.T, h http.Handler, body, authorization, remoteAddr string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, orchestratorPath, strings.NewReader(body))
	req.RemoteAddr = remoteAddr
	req.Header.Set("Content-Type", "application/json")
	if authorization != "" {
		req.Header.Set("Authorization", authorization)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func orchestratorTestJSON(t *testing.T, fields map[string]any) string {
	t.Helper()
	body, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	return string(body)
}

func orchestratorBase(action, runID string) map[string]any {
	return map[string]any{
		"schemaVersion": cpSchemaVersion,
		"action":        action,
		"runId":         runID,
	}
}

func TestOrchestratorBridgeRouteIsAbsentWithoutSeparateToken(t *testing.T) {
	t.Setenv(orchestratorTokenEnv, "")
	controlPlane := cpTestNew(t)
	bridge, err := configuredOrchestratorBridge(controlPlane)
	if err != nil || bridge != nil {
		t.Fatalf("disabled bridge = (%T, %v), want (nil, nil)", bridge, err)
	}

	rec := orchestratorTestDo(t, newServerMuxWithOrchestrator(controlPlane, bridge), `{}`)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("absent bridge status = %d, want 404", rec.Code)
	}

	t.Setenv("MISSION_CONTROL_API_TOKEN", cpTestToken)
	t.Setenv(orchestratorTokenEnv, orchestratorTestToken)
	bridge, err = configuredOrchestratorBridge(controlPlane)
	if err != nil || bridge == nil {
		t.Fatalf("configured bridge = (%T, %v), want a handler", bridge, err)
	}
	run := cpTestCreate(t, controlPlane)
	body := orchestratorBase("advance_source", run.RunID)
	body["sourceId"] = "jde"
	body["state"] = "inventorying"
	rec = orchestratorTestDo(t, newServerMuxWithOrchestrator(controlPlane, bridge), orchestratorTestJSON(t, body))
	if rec.Code != http.StatusOK {
		t.Fatalf("configured bridge status = %d, want 200 (%s)", rec.Code, rec.Body.String())
	}

	t.Setenv(orchestratorTokenEnv, cpTestToken)
	if _, err := configuredOrchestratorBridge(controlPlane); !errors.Is(err, errOrchestratorConfiguration) {
		t.Fatalf("shared public/internal token error = %v", err)
	}

	t.Setenv(orchestratorTokenEnv, orchestratorTestToken)
	if _, err := configuredOrchestratorBridge(nil); !errors.Is(err, errOrchestratorConfiguration) {
		t.Fatalf("token without control plane error = %v", err)
	}
}

func TestOrchestratorBridgeRequiresItsExactSeparateBearer(t *testing.T) {
	controlPlane := cpTestNew(t)
	run := cpTestCreate(t, controlPlane)
	body := orchestratorBase("advance_source", run.RunID)
	body["sourceId"] = "jde"
	body["state"] = "inventorying"
	encoded := orchestratorTestJSON(t, body)
	h := orchestratorTestHandler(t, controlPlane)

	cases := []struct {
		name   string
		header string
	}{
		{"missing", ""},
		{"public api token", "Bearer " + cpTestToken},
		{"wrong token", "Bearer " + orchestratorTestToken + "x"},
		{"wrong scheme", "bearer " + orchestratorTestToken},
		{"trailing space", "Bearer " + orchestratorTestToken + " "},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := orchestratorTestDoAs(t, h, encoded, tc.header, "127.0.0.1:41000")
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("status = %d, want 401", rec.Code)
			}
			if rec.Header().Get("WWW-Authenticate") != "Bearer" {
				t.Errorf("WWW-Authenticate = %q", rec.Header().Get("WWW-Authenticate"))
			}
		})
	}

	// Multiple header values fail even when both values are individually exact.
	req := httptest.NewRequest(http.MethodPost, orchestratorPath, strings.NewReader(encoded))
	req.RemoteAddr = "127.0.0.1:41000"
	req.Header.Set("Content-Type", "application/json")
	req.Header.Add("Authorization", "Bearer "+orchestratorTestToken)
	req.Header.Add("Authorization", "Bearer "+orchestratorTestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("duplicate Authorization status = %d, want 401", rec.Code)
	}

	// None of the rejected calls may have moved the durable source state.
	stored, err := controlPlane.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stored.Sources[0].State != ControlPlaneStateCreated {
		t.Fatalf("rejected auth mutated state to %q", stored.Sources[0].State)
	}
}

func TestOrchestratorBridgeRequiresTransportLoopbackAndIgnoresForwardingHeaders(t *testing.T) {
	controlPlane := cpTestNew(t)
	run := cpTestCreate(t, controlPlane)
	body := orchestratorBase("advance_source", run.RunID)
	body["sourceId"] = "jde"
	body["state"] = "inventorying"
	encoded := orchestratorTestJSON(t, body)
	h := orchestratorTestHandler(t, controlPlane)

	req := httptest.NewRequest(http.MethodPost, orchestratorPath, strings.NewReader(encoded))
	req.RemoteAddr = "10.0.0.8:41000"
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+orchestratorTestToken)
	req.Header.Set("X-Forwarded-For", "127.0.0.1")
	req.Header.Set("Forwarded", "for=127.0.0.1")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("non-loopback status = %d, want 403", rec.Code)
	}

	stored, err := controlPlane.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stored.Sources[0].State != ControlPlaneStateCreated {
		t.Fatalf("non-loopback call mutated state to %q", stored.Sources[0].State)
	}
}

func TestOrchestratorBridgeRejectsUnknownDuplicateAndActionInvalidFields(t *testing.T) {
	controlPlane := cpTestNew(t)
	run := cpTestCreate(t, controlPlane)
	h := orchestratorTestHandler(t, controlPlane)
	base := fmt.Sprintf(`{"schemaVersion":"%s","action":"advance_source","runId":%q,"sourceId":"jde","state":"inventorying"`, cpSchemaVersion, run.RunID)

	cases := []struct {
		name string
		body string
	}{
		{"unknown action", fmt.Sprintf(`{"schemaVersion":"%s","action":"append_event","runId":%q}`, cpSchemaVersion, run.RunID)},
		{"unknown field", base + `,"summary":"caller text"}`},
		{"duplicate action", fmt.Sprintf(`{"schemaVersion":"%s","action":"advance_source","action":"fail_source","runId":%q,"sourceId":"jde","state":"inventorying"}`, cpSchemaVersion, run.RunID)},
		{"trailing document", base + `}{}`},
		{"irrelevant known field", base + `,"failureCode":null}`},
		{"unknown state", fmt.Sprintf(`{"schemaVersion":"%s","action":"advance_source","runId":%q,"sourceId":"jde","state":"awaiting_approval"}`, cpSchemaVersion, run.RunID)},
		{"missing evidence", fmt.Sprintf(`{"schemaVersion":"%s","action":"advance_source","runId":%q,"sourceId":"jde","state":"redacting"}`, cpSchemaVersion, run.RunID)},
		{"nullable counter", base + `,"recordsRead":null}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := orchestratorTestDo(t, h, tc.body)
			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400 (body %s)", rec.Code, rec.Body.String())
			}
		})
	}

	stored, err := controlPlane.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stored.Sources[0].State != ControlPlaneStateCreated {
		t.Fatalf("invalid requests mutated state to %q", stored.Sources[0].State)
	}
}

func TestOrchestratorBridgeEnforcesMethodMediaTypePathAndBodyLimit(t *testing.T) {
	controlPlane := cpTestNew(t)
	h := orchestratorTestHandler(t, controlPlane)

	methodReq := httptest.NewRequest(http.MethodGet, orchestratorPath, nil)
	methodReq.RemoteAddr = "[::1]:41000"
	methodReq.Header.Set("Authorization", "Bearer "+orchestratorTestToken)
	methodRec := httptest.NewRecorder()
	h.ServeHTTP(methodRec, methodReq)
	if methodRec.Code != http.StatusMethodNotAllowed || methodRec.Header().Get("Allow") != http.MethodPost {
		t.Fatalf("GET = %d Allow %q", methodRec.Code, methodRec.Header().Get("Allow"))
	}

	mediaReq := httptest.NewRequest(http.MethodPost, orchestratorPath, strings.NewReader(`{}`))
	mediaReq.RemoteAddr = "127.0.0.1:41000"
	mediaReq.Header.Set("Authorization", "Bearer "+orchestratorTestToken)
	mediaReq.Header.Set("Content-Type", "text/plain")
	mediaRec := httptest.NewRecorder()
	h.ServeHTTP(mediaRec, mediaReq)
	if mediaRec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("text body = %d, want 415", mediaRec.Code)
	}

	pathReq := httptest.NewRequest(http.MethodPost, "/internal/v1/other", strings.NewReader(`{}`))
	pathReq.RemoteAddr = "127.0.0.1:41000"
	pathReq.Header.Set("Authorization", "Bearer "+orchestratorTestToken)
	pathReq.Header.Set("Content-Type", "application/json")
	pathRec := httptest.NewRecorder()
	h.ServeHTTP(pathRec, pathReq)
	if pathRec.Code != http.StatusNotFound {
		t.Fatalf("unknown internal path = %d, want 404", pathRec.Code)
	}

	oversized := `{"schemaVersion":"1.0.0","action":"fail_source","runId":"mig_123456789012","sourceId":"jde","failureCode":"` + strings.Repeat("X", orchestratorMaxBody) + `"}`
	limitRec := orchestratorTestDo(t, h, oversized)
	if limitRec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized body = %d, want 413", limitRec.Code)
	}
}

func TestOrchestratorBridgeDrivesValidPortfolioToApprovalGate(t *testing.T) {
	controlPlane := cpTestNew(t)
	run := cpTestCreate(t, controlPlane)
	h := orchestratorTestHandler(t, controlPlane)

	advance := func(source string, state ControlPlaneState, artifactID, digest string, read *int64) {
		t.Helper()
		body := orchestratorBase("advance_source", run.RunID)
		body["sourceId"] = source
		body["state"] = state
		if artifactID != "" {
			body["artifactId"] = artifactID
			body["digest"] = digest
		}
		if read != nil {
			body["recordsRead"] = *read
		}
		rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, body))
		if rec.Code != http.StatusOK {
			t.Fatalf("%s -> %s status = %d (%s)", source, state, rec.Code, rec.Body.String())
		}
	}

	for _, source := range []string{"jde", "maxdb", "btrieve"} {
		read := int64(100)
		advance(source, ControlPlaneStateInventorying, "", "", nil)
		advance(source, ControlPlaneStateRedacting, "art_"+source+"-manifest", cpTestPlanDigests[source], &read)
		advance(source, ControlPlaneStatePlanning, "art_"+source+"-redaction", cpTestPlanDigests[source], nil)

		plan := orchestratorBase("attach_source_plan", run.RunID)
		plan["sourceId"] = source
		plan["artifactId"] = "art_" + source + "-plan-001"
		plan["digest"] = cpTestPlanDigests[source]
		rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, plan))
		if rec.Code != http.StatusOK {
			t.Fatalf("attach %s plan = %d (%s)", source, rec.Code, rec.Body.String())
		}
	}

	gate := orchestratorBase("enter_awaiting_approval", run.RunID)
	rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, gate))
	if rec.Code != http.StatusOK {
		t.Fatalf("enter approval gate = %d (%s)", rec.Code, rec.Body.String())
	}
	var response cpRunBody
	if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if response.State != ControlPlaneStateAwaitingApproval || response.PortfolioPlanDigest == "" {
		t.Fatalf("response state/digest = %q/%q", response.State, response.PortfolioPlanDigest)
	}
	for _, source := range response.Sources {
		if source.State != ControlPlaneStateAwaitingApproval || source.PlanDigest == "" {
			t.Errorf("source %s = %q digest %q", source.SourceID, source.State, source.PlanDigest)
		}
	}

	events, err := controlPlane.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events: %v", err)
	}
	if got, want := len(events), 14; got != want {
		t.Fatalf("events = %d, want %d", got, want)
	}
	if events[len(events)-1].EventType != "portfolio.awaiting_approval" {
		t.Fatalf("last event = %q", events[len(events)-1].EventType)
	}

	approvalRequest := fmt.Sprintf(
		`{"schemaVersion":"%s","planDigest":"%s","decision":"approve","decidedBy":"portfolio-reviewer","reason":"approved cloud migration"}`,
		cpSchemaVersion,
		response.PortfolioPlanDigest,
	)
	decision := cpTestDo(
		t,
		controlPlane,
		http.MethodPost,
		"/api/v1/migrations/"+run.RunID+"/approval",
		approvalRequest,
	)
	if decision.Code != http.StatusOK {
		t.Fatalf("approve status = %d (%s)", decision.Code, decision.Body.String())
	}
	approvalRead := httptest.NewRequest(
		http.MethodGet,
		orchestratorApprovalPath+run.RunID,
		nil,
	)
	approvalRead.RemoteAddr = "127.0.0.1:41000"
	approvalRead.Header.Set("Authorization", "Bearer "+orchestratorTestToken)
	approvalRecord := httptest.NewRecorder()
	h.ServeHTTP(approvalRecord, approvalRead)
	if approvalRecord.Code != http.StatusOK {
		t.Fatalf("approval read status = %d (%s)", approvalRecord.Code, approvalRecord.Body.String())
	}
	var approval cpApprovalBody
	if err := json.Unmarshal(approvalRecord.Body.Bytes(), &approval); err != nil {
		t.Fatalf("decode approval: %v", err)
	}
	if approval.RunID != run.RunID || approval.PlanDigest != response.PortfolioPlanDigest ||
		approval.Decision != "approve" || approval.ResultingState != ControlPlaneStateApproved ||
		approval.DecidedBy != "portfolio-reviewer" || approval.DecidedAt == "" {
		t.Fatalf("approval read returned wrong binding: %+v", approval)
	}

	executing := orchestratorBase("advance_source", run.RunID)
	executing["sourceId"] = "jde"
	executing["state"] = "executing"
	if rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, executing)); rec.Code != http.StatusOK {
		t.Fatalf("execute JDE = %d (%s)", rec.Code, rec.Body.String())
	}
	verifying := orchestratorBase("advance_source", run.RunID)
	verifying["sourceId"] = "jde"
	verifying["state"] = "verifying"
	verifying["artifactId"] = "art_jde-dataflow-proof"
	verifying["digest"] = cpTestPlanDigests["jde"]
	verifying["secondaryArtifactId"] = "art_jde-bigquery-proof"
	verifying["secondaryDigest"] = cpTestPlanDigests["maxdb"]
	if rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, verifying)); rec.Code != http.StatusOK {
		t.Fatalf("verify JDE = %d (%s)", rec.Code, rec.Body.String())
	}
	completed := orchestratorBase("advance_source", run.RunID)
	completed["sourceId"] = "jde"
	completed["state"] = "completed"
	completed["artifactId"] = "art_jde-reconciliation-proof"
	completed["digest"] = cpTestPlanDigests["jde"]
	completed["secondaryArtifactId"] = "art_jde-audit-proof"
	completed["secondaryDigest"] = cpTestPlanDigests["btrieve"]
	if rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, completed)); rec.Code != http.StatusOK {
		t.Fatalf("complete JDE = %d (%s)", rec.Code, rec.Body.String())
	}
	events, err = controlPlane.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events after cloud evidence: %v", err)
	}
	if got := events[len(events)-2].EvidenceReferences; len(got) != 2 ||
		got[0].Kind != "dataflow_job" || got[1].Kind != "bigquery_table" {
		t.Fatalf("verifying evidence = %+v", got)
	}
	if got := events[len(events)-1].EvidenceReferences; len(got) != 2 ||
		got[0].Kind != "reconciliation" || got[1].Kind != "audit_log" {
		t.Fatalf("completion evidence = %+v", got)
	}
}

func TestOrchestratorBridgeCanRecordOnlyClosedFailureCode(t *testing.T) {
	controlPlane := cpTestNew(t)
	run := cpTestCreate(t, controlPlane)
	h := orchestratorTestHandler(t, controlPlane)

	fail := orchestratorBase("fail_source", run.RunID)
	fail["sourceId"] = "maxdb"
	fail["failureCode"] = "SOURCE_UNREACHABLE"
	rec := orchestratorTestDo(t, h, orchestratorTestJSON(t, fail))
	if rec.Code != http.StatusOK {
		t.Fatalf("fail source = %d (%s)", rec.Code, rec.Body.String())
	}
	stored, err := controlPlane.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stored.State != ControlPlaneStateFailed || stored.FailureCode != "SOURCE_UNREACHABLE" {
		t.Fatalf("stored run = %q/%q", stored.State, stored.FailureCode)
	}
}
