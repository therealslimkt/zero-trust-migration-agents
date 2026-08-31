package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	m3TestNow      = time.Date(2026, 8, 30, 12, 0, 0, 0, time.UTC)
	m3TestPlan     = "sha256:" + strings.Repeat("1", 64)
	m3TestRelease  = "sha256:" + strings.Repeat("2", 64)
	m3TestArtifact = "sha256:" + strings.Repeat("3", 64)
)

const (
	m3TestSimulationNonce = "simulation_nonce_1234567890"
	m3TestProductionNonce = "production_nonce_1234567890"
)

type m3TestClock struct{ now time.Time }

func (c m3TestClock) Now() time.Time { return c.now }

type m3TestAuth struct {
	principal M3Principal
	err       error
}

func (a m3TestAuth) AuthenticateM3Approval(*http.Request, M3ApprovalStage) (M3Principal, error) {
	return a.principal, a.err
}

type m3TestAuthority struct {
	view M3AuthorityView
	err  error
}

func (a *m3TestAuthority) ReadM3ApprovalAuthority(context.Context, M3Principal, string, M3ApprovalStage) (M3AuthorityView, error) {
	return a.view, a.err
}

func m3SimulationPending(t *testing.T) M3PendingApproval {
	t.Helper()
	p, err := M3NewPendingApproval(M3IssuePendingInput{
		RequestID: "req_simulation", TenantID: "tnt_testtenant01", RunID: "run_testrun000001", Stage: M3SimulationStage,
		PlanDigest: m3TestPlan, ReleaseDigest: m3TestRelease, ArtifactDigest: m3TestArtifact,
		CheckpointID: "ckpt_simulation", Nonce: m3TestSimulationNonce,
		IssuedAt: m3TestNow.Add(-time.Minute), ExpiresAt: m3TestNow.Add(5 * time.Minute),
		Audience: "release_operators", RequiredApprovers: 2,
	})
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func m3AuthorityFor(p M3PendingApproval) M3AuthorityView {
	return M3AuthorityView{TenantID: p.TenantID, RunID: p.RunID, Stage: p.Stage,
		PlanDigest: p.PlanDigest, ReleaseDigest: p.ReleaseDigest, ArtifactDigest: p.ArtifactDigest,
		InterruptID: p.InterruptID, CheckpointID: p.CheckpointID, Audience: p.Audience,
		ApproverCount: p.RequiredApprovers, Authorized: true, ArtifactPresent: true}
}

func m3Harness(t *testing.T, pending M3PendingApproval, view M3AuthorityView, now time.Time) (*M3MemoryApprovalRepository, *m3TestAuthority, *M3ApprovalService) {
	t.Helper()
	repo := NewM3MemoryApprovalRepository()
	if err := repo.IssueM3Pending(pending); err != nil {
		t.Fatal(err)
	}
	authority := &m3TestAuthority{view: view}
	service, err := NewM3ApprovalService(m3TestAuth{principal: M3Principal{ActorID: "actor_alice", Role: M3ApprovalAdmin, Authenticated: true}}, authority, repo, m3TestClock{now})
	if err != nil {
		t.Fatal(err)
	}
	return repo, authority, service
}

func m3Request(handler http.Handler, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/approval", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)
	return w
}

func m3SimulationJSON(nonce, decision string) string {
	payload, _ := json.Marshal(map[string]string{"requestId": "req_simulation", "nonce": nonce, "decision": decision})
	return string(payload)
}

func TestM3SimulationThenProductionProgression(t *testing.T) {
	p := m3SimulationPending(t)
	repo, authority, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation"))
	if w.Code != http.StatusCreated {
		t.Fatalf("simulation status=%d body=%s", w.Code, w.Body)
	}
	var simulation struct {
		Record      M3ApprovalRecord      `json:"record"`
		Trace       []string              `json:"trace"`
		Determinism M3DeterminismMetadata `json:"determinism"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &simulation); err != nil {
		t.Fatal(err)
	}
	wantTrace := []string{"request_observed", "authenticated_authority_read", "bindings_verified", "immutable_decision_recorded"}
	if strings.Join(simulation.Trace, ",") != strings.Join(wantTrace, ",") {
		t.Fatalf("trace=%v", simulation.Trace)
	}
	if simulation.Determinism.ModelCalls != 0 || simulation.Determinism.Concurrency != 1 || simulation.Determinism.GraphDepth != 0 {
		t.Fatalf("metadata=%+v", simulation)
	}

	production, err := M3NewPendingApproval(M3IssuePendingInput{
		RequestID: "req_production", TenantID: p.TenantID, RunID: p.RunID, Stage: M3ProductionStage,
		PlanDigest: p.PlanDigest, ReleaseDigest: p.ReleaseDigest, ArtifactDigest: p.ArtifactDigest,
		CheckpointID: "ckpt_production", Nonce: m3TestProductionNonce, IssuedAt: m3TestNow,
		ExpiresAt: m3TestNow.Add(5 * time.Minute), Audience: p.Audience, RequiredApprovers: 2,
		SimulationRecordDigest: simulation.Record.RecordDigest,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.IssueM3Pending(production); err != nil {
		t.Fatal(err)
	}
	authority.view = m3AuthorityFor(production)
	body := `{"requestId":"req_production","nonce":"` + m3TestProductionNonce + `","decision":"approve_production"}`
	w = m3Request(service.ProductionHandler(), body)
	if w.Code != http.StatusCreated {
		t.Fatalf("production status=%d body=%s", w.Code, w.Body)
	}
}

func TestM3ValidRejectRecordsAndBlocksProduction(t *testing.T) {
	p := m3SimulationPending(t)
	repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "reject_simulation"))
	if w.Code != http.StatusCreated {
		t.Fatalf("status=%d", w.Code)
	}
	var response struct {
		Record M3ApprovalRecord `json:"record"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &response)
	production, err := M3NewPendingApproval(M3IssuePendingInput{RequestID: "req_production", TenantID: p.TenantID, RunID: p.RunID,
		Stage: M3ProductionStage, PlanDigest: p.PlanDigest, ReleaseDigest: p.ReleaseDigest, ArtifactDigest: p.ArtifactDigest,
		CheckpointID: "ckpt_production", Nonce: m3TestProductionNonce, IssuedAt: m3TestNow, ExpiresAt: m3TestNow.Add(time.Minute),
		Audience: p.Audience, RequiredApprovers: 2, SimulationRecordDigest: response.Record.RecordDigest})
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.IssueM3Pending(production); err == nil {
		t.Fatal("production issued after rejection")
	}
}

func TestM3AuthorityAndDatabaseDisagreementsDoNotMutate(t *testing.T) {
	tests := map[string]func(*M3AuthorityView){
		"stale plan":         func(v *M3AuthorityView) { v.PlanDigest = "sha256:" + strings.Repeat("4", 64) },
		"release mismatch":   func(v *M3AuthorityView) { v.ReleaseDigest = "sha256:" + strings.Repeat("5", 64) },
		"cross tenant":       func(v *M3AuthorityView) { v.TenantID = "tnt_other000001" },
		"cross run":          func(v *M3AuthorityView) { v.RunID = "run_other0000001" },
		"wrong kind":         func(v *M3AuthorityView) { v.Stage = M3ProductionStage },
		"wrong interrupt":    func(v *M3AuthorityView) { v.InterruptID = "int_forged" },
		"wrong checkpoint":   func(v *M3AuthorityView) { v.CheckpointID = "ckpt_other" },
		"wrong audience":     func(v *M3AuthorityView) { v.Audience = "developers" },
		"approver shortfall": func(v *M3AuthorityView) { v.ApproverCount = 1 },
		"missing artifact":   func(v *M3AuthorityView) { v.ArtifactPresent = false },
		"unauthorized":       func(v *M3AuthorityView) { v.Authorized = false },
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			p := m3SimulationPending(t)
			view := m3AuthorityFor(p)
			mutate(&view)
			repo, _, service := m3Harness(t, p, view, m3TestNow)
			before := repo.M3MutationCount()
			w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation"))
			if w.Code != http.StatusForbidden || repo.M3MutationCount() != before {
				t.Fatalf("status=%d mutation=%d/%d", w.Code, repo.M3MutationCount(), before)
			}
			if !strings.Contains(w.Body.String(), "fail_closed_rejection") || strings.Contains(w.Body.String(), p.TenantID) {
				t.Fatalf("unsafe body=%s", w.Body)
			}
		})
	}
}

func TestM3TimeBoundariesAndNonceReplay(t *testing.T) {
	for name, tc := range map[string]struct {
		issued, expires time.Time
		created         bool
	}{
		"issued boundary": {m3TestNow, m3TestNow.Add(time.Minute), true},
		"not yet issued":  {m3TestNow.Add(time.Second), m3TestNow.Add(time.Minute), false},
		"expiry boundary": {m3TestNow.Add(-time.Minute), m3TestNow, false},
	} {
		t.Run(name, func(t *testing.T) {
			p, err := M3NewPendingApproval(M3IssuePendingInput{RequestID: "req_simulation", TenantID: "tnt_testtenant01", RunID: "run_testrun000001", Stage: M3SimulationStage,
				PlanDigest: m3TestPlan, ReleaseDigest: m3TestRelease, ArtifactDigest: m3TestArtifact, CheckpointID: "ckpt_simulation", Nonce: m3TestSimulationNonce,
				IssuedAt: tc.issued, ExpiresAt: tc.expires, Audience: "release_operators", RequiredApprovers: 2})
			if err != nil {
				t.Fatal(err)
			}
			repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
			before := repo.M3MutationCount()
			w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation"))
			if (w.Code == http.StatusCreated) != tc.created {
				t.Fatalf("status=%d", w.Code)
			}
			if !tc.created && repo.M3MutationCount() != before {
				t.Fatal("failure mutated")
			}
		})
	}
	p := m3SimulationPending(t)
	repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	if w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation")); w.Code != http.StatusCreated {
		t.Fatal(w.Code)
	}
	after := repo.M3MutationCount()
	if w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation")); w.Code != http.StatusForbidden || repo.M3MutationCount() != after {
		t.Fatal("replay changed state")
	}
}

func TestM3KindSwapWrongNonceAndUnauthenticatedFail(t *testing.T) {
	p := m3SimulationPending(t)
	repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	before := repo.M3MutationCount()
	if w := m3Request(service.ProductionHandler(), `{"requestId":"req_simulation","nonce":"`+m3TestSimulationNonce+`","decision":"approve_production"}`); w.Code != http.StatusForbidden {
		t.Fatal(w.Code)
	}
	if w := m3Request(service.SimulationHandler(), m3SimulationJSON("wrong_nonce_12345678901234", "approve_simulation")); w.Code != http.StatusForbidden {
		t.Fatal(w.Code)
	}
	service.Auth = m3TestAuth{principal: M3Principal{ActorID: "actor_alice"}, err: errors.New("no")}
	if w := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation")); w.Code != http.StatusForbidden {
		t.Fatal(w.Code)
	}
	if repo.M3MutationCount() != before {
		t.Fatal("rejection mutated")
	}
}

func TestM3WrongStageRoleFailsWithoutMutation(t *testing.T) {
	p := m3SimulationPending(t)
	repo := NewM3MemoryApprovalRepository()
	if err := repo.IssueM3Pending(p); err != nil {
		t.Fatal(err)
	}
	authority := &m3TestAuthority{view: m3AuthorityFor(p)}
	service, err := NewM3ApprovalService(
		m3TestAuth{principal: M3Principal{ActorID: "actor_alice", Role: M3ProductionApprover, Authenticated: true}},
		authority, repo, m3TestClock{m3TestNow},
	)
	if err != nil {
		t.Fatal(err)
	}
	before := repo.M3MutationCount()
	response := m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation"))
	if response.Code != http.StatusForbidden || repo.M3MutationCount() != before {
		t.Fatalf("status=%d mutations=%d/%d", response.Code, repo.M3MutationCount(), before)
	}
}

func TestM3ClosedJSONRejectsForgedResumeA2AActorAndTrailingData(t *testing.T) {
	p := m3SimulationPending(t)
	repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	before := repo.M3MutationCount()
	bodies := []string{
		`{"requestId":"req_simulation","nonce":"` + m3TestSimulationNonce + `","decision":"approve_simulation","actorId":"actor_admin"}`,
		`{"requestId":"req_simulation","nonce":"` + m3TestSimulationNonce + `","decision":"approve_simulation","authenticated":true}`,
		`{"requestId":"req_simulation","nonce":"` + m3TestSimulationNonce + `","decision":"approve_simulation","tenantId":"tnt_testtenant01"}`,
		`{"requestId":"req_simulation","nonce":"` + m3TestSimulationNonce + `","decision":"approve_simulation","resume":"approved"}`,
		`{"requestId":"req_simulation","nonce":"` + m3TestSimulationNonce + `","decision":"approve_simulation","a2a":{"approved":true}}`,
		m3SimulationJSON(m3TestSimulationNonce, "approve_simulation") + `{}`,
	}
	for _, body := range bodies {
		if w := m3Request(service.SimulationHandler(), body); w.Code != http.StatusBadRequest {
			t.Fatalf("status=%d body=%s", w.Code, body)
		}
	}
	if repo.M3MutationCount() != before {
		t.Fatal("malformed body mutated")
	}
}

func TestM3MethodContentTypeSizeAndStageDecisionAreStrict(t *testing.T) {
	p := m3SimulationPending(t)
	repo, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	before := repo.M3MutationCount()
	req := httptest.NewRequest(http.MethodGet, "/approval", nil)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	service.SimulationHandler().ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Fatal(w.Code)
	}
	req = httptest.NewRequest(http.MethodPost, "/approval", strings.NewReader("{}"))
	req.Header.Set("Content-Type", "text/plain")
	w = httptest.NewRecorder()
	service.SimulationHandler().ServeHTTP(w, req)
	if w.Code != http.StatusUnsupportedMediaType {
		t.Fatal(w.Code)
	}
	if w = m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_production")); w.Code != http.StatusForbidden {
		t.Fatal(w.Code)
	}
	large := `{"requestId":"req_simulation","nonce":"` + strings.Repeat("a", 5000) + `","decision":"approve_simulation"}`
	if w = m3Request(service.SimulationHandler(), large); w.Code != http.StatusBadRequest {
		t.Fatal(w.Code)
	}
	if repo.M3MutationCount() != before {
		t.Fatal("transport rejection mutated")
	}
}

func TestM3ForgedDigestInterruptAndProductionBindingCannotIssue(t *testing.T) {
	repo := NewM3MemoryApprovalRepository()
	p := m3SimulationPending(t)
	if err := repo.IssueM3Pending(p); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*M3PendingApproval){
		"digest":    func(v *M3PendingApproval) { v.RequestDigest = "sha256:" + strings.Repeat("9", 64) },
		"interrupt": func(v *M3PendingApproval) { v.InterruptID = "int_forged" },
	} {
		t.Run(name, func(t *testing.T) {
			forged := p
			forged.RequestID = "req_forged_" + strings.ReplaceAll(name, " ", "_")
			mutate(&forged)
			if repo.IssueM3Pending(forged) == nil {
				t.Fatal("forgery issued")
			}
		})
	}
	production, err := M3NewPendingApproval(M3IssuePendingInput{RequestID: "req_production", TenantID: p.TenantID, RunID: p.RunID, Stage: M3ProductionStage,
		PlanDigest: p.PlanDigest, ReleaseDigest: p.ReleaseDigest, ArtifactDigest: p.ArtifactDigest, CheckpointID: "ckpt_production", Nonce: m3TestProductionNonce,
		IssuedAt: m3TestNow, ExpiresAt: m3TestNow.Add(time.Minute), Audience: p.Audience, RequiredApprovers: 2,
		SimulationRecordDigest: "sha256:" + strings.Repeat("8", 64)})
	if err != nil {
		t.Fatal(err)
	}
	if repo.IssueM3Pending(production) == nil {
		t.Fatal("production issued without simulation")
	}
	reused, err := M3NewPendingApproval(M3IssuePendingInput{RequestID: "req_OTHER000001", TenantID: "tnt_other000001", RunID: "run_other0000001", Stage: M3SimulationStage,
		PlanDigest: m3TestPlan, ReleaseDigest: m3TestRelease, ArtifactDigest: m3TestArtifact, CheckpointID: "ckpt_OTHER000001", Nonce: m3TestSimulationNonce,
		IssuedAt: m3TestNow, ExpiresAt: m3TestNow.Add(time.Minute), Audience: "release_operators", RequiredApprovers: 2})
	if err != nil {
		t.Fatal(err)
	}
	before := repo.M3MutationCount()
	if repo.IssueM3Pending(reused) == nil || repo.M3MutationCount() != before {
		t.Fatal("cross-tenant nonce was reusable")
	}
}

func TestM3ConcurrentApprovalHasExactlyOneWinner(t *testing.T) {
	p := m3SimulationPending(t)
	_, _, service := m3Harness(t, p, m3AuthorityFor(p), m3TestNow)
	const workers = 12
	start := make(chan struct{})
	var wg sync.WaitGroup
	statuses := make(chan int, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			statuses <- m3Request(service.SimulationHandler(), m3SimulationJSON(m3TestSimulationNonce, "approve_simulation")).Code
		}()
	}
	close(start)
	wg.Wait()
	close(statuses)
	created := 0
	for status := range statuses {
		if status == http.StatusCreated {
			created++
		} else if status != http.StatusForbidden {
			t.Fatalf("status=%d", status)
		}
	}
	if created != 1 {
		t.Fatalf("created=%d", created)
	}
}
