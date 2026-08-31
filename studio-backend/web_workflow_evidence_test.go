package main

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

type webWorkflowEvidenceRuns struct { run *ControlPlaneRun }

func (r webWorkflowEvidenceRuns) CreateRunWithOwnership(*cpCreateRequest, func(*ControlPlaneRun) error) (*ControlPlaneRun, error) { return nil, errors.New("unused") }
func (r webWorkflowEvidenceRuns) WebRunSnapshot(runID string) (*ControlPlaneRun, []*ControlPlaneEvent, error) {
	if r.run == nil || runID != r.run.RunID { return nil, nil, errors.New("missing") }
	return r.run, nil, nil
}
func (r webWorkflowEvidenceRuns) Approval(string) (*ControlPlaneApproval, error) { return nil, errors.New("unused") }
func (r webWorkflowEvidenceRuns) Decide(string, *cpApprovalRequest) (*ControlPlaneApproval, error) { return nil, errors.New("unused") }

type webWorkflowEvidenceReader struct { projection WebWorkflowEvidenceProjection; err error }
func (r webWorkflowEvidenceReader) ReadPersistedWorkflowEvidence(context.Context, string) (WebWorkflowEvidenceProjection, error) { return r.projection, r.err }

func webWorkflowEvidenceHandler(t *testing.T, reader WebPersistedWorkflowEvidenceReader) http.Handler {
	t.Helper()
	store, err := OpenWebStateStore(t.TempDir()+"/web.json")
	if err != nil { t.Fatal(err) }
	runID := "mig_WorkflowEvidence01"
	stamp := "2026-08-30T12:00:00.000Z"
	run := &ControlPlaneRun{RunID: runID, PortfolioName: "internal", State: ControlPlaneStateCreated, CreatedAt: stamp, UpdatedAt: stamp}
	if err := store.PutRunOwnership(WebRunOwnershipRecord{RunID: runID, OwnerUID: "owner", PortfolioName: "Owned", Owner: WebIdentitySummary{Subject: "owner", DisplayName: "owner", Email: "owner@example.test"}, CreatedAt: stamp}); err != nil { t.Fatal(err) }
	handler, err := NewWebBFFHandler(WebBFFConfig{Verifier: webTestVerifier{}, Runs: webWorkflowEvidenceRuns{run: run}, Store: store, WorkflowEvidence: reader, AllowedOrigins: []string{"http://127.0.0.1:5173"}})
	if err != nil { t.Fatal(err) }
	return handler
}

func TestWorkflowEvidenceEndpointIsOwnedAndUsesOnlyValidPersistedProjection(t *testing.T) {
	modelCall := true
	projection := WebWorkflowEvidenceProjection{Status: "ready", ReplayCursor: "pgseq-2", Complete: true, Entries: []WebWorkflowEvidenceEntry{
		{Sequence: 1, EventID: "evt_WorkflowEvidence01", Persisted: true, State: "succeeded", EvidenceDigest: "sha256:" + strings.Repeat("a", 64), Kind: "node", WorkClass: "model_call", ModelCall: &modelCall, NodePath: "prisma.plan", AgentID: "prisma"},
		{Sequence: 2, EventID: "evt_WorkflowEvidence02", Persisted: true, State: "interrupted", EvidenceDigest: "sha256:" + strings.Repeat("b", 64), Kind: "approval_interrupt", ApprovalKind: "production_approval", InterruptID: "int_production_001", ResumeChannel: "approval_endpoint", SubjectDigest: "sha256:" + strings.Repeat("c", 64), Decision: "pending"},
	}}
	handler := webWorkflowEvidenceHandler(t, webWorkflowEvidenceReader{projection: projection})
	response := webRequest(t, handler, http.MethodGet, "/api/web/v1/runs/mig_WorkflowEvidence01/workflow-evidence", "owner", nil)
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"modelCall":true`) || !strings.Contains(response.Body.String(), `"resumeChannel":"approval_endpoint"`) { t.Fatalf("projection response = %d %s", response.Code, response.Body.String()) }
	foreign := webRequest(t, handler, http.MethodGet, "/api/web/v1/runs/mig_WorkflowEvidence01/workflow-evidence", "other", nil)
	if foreign.Code != http.StatusNotFound { t.Fatalf("foreign projection response = %d", foreign.Code) }
}

func TestWorkflowEvidenceEndpointWithholdsAbsentOrMalformedReaderOutput(t *testing.T) {
	for name, reader := range map[string]WebPersistedWorkflowEvidenceReader{
		"absent": webWorkflowEvidenceReader{err: errors.New("not found")},
		"malformed": webWorkflowEvidenceReader{projection: WebWorkflowEvidenceProjection{Status: "ready", ReplayCursor: "cursor", Entries: []WebWorkflowEvidenceEntry{{Sequence: 1}}}},
	} {
		t.Run(name, func(t *testing.T) {
			response := webRequest(t, webWorkflowEvidenceHandler(t, reader), http.MethodGet, "/api/web/v1/runs/mig_WorkflowEvidence01/workflow-evidence", "owner", nil)
			if response.Code != http.StatusNotFound && response.Code != http.StatusInternalServerError { t.Fatalf("withheld projection response = %d %s", response.Code, response.Body.String()) }
		})
	}
}
