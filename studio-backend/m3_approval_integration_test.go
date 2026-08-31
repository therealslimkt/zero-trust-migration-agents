package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type m3IntegrationVerifier struct {
	identity WebVerifiedIdentity
	err      error
	token    string
}

func (v *m3IntegrationVerifier) VerifyWebIdentity(_ context.Context, token string) (WebVerifiedIdentity, error) {
	v.token = token
	return v.identity, v.err
}

type m3IntegrationAuthority struct {
	mu    sync.Mutex
	views map[string]M3AuthorityView
}

func (a *m3IntegrationAuthority) ReadM3ApprovalAuthority(_ context.Context, _ M3Principal, requestID string, _ M3ApprovalStage) (M3AuthorityView, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	view, ok := a.views[requestID]
	if !ok {
		return M3AuthorityView{}, errM3Rejected
	}
	return view, nil
}

func (a *m3IntegrationAuthority) put(requestID string, view M3AuthorityView) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.views[requestID] = view
}

type m3IntegrationInterrupts struct {
	kinds map[string]M3PendingInterruptKind
}

func (s *m3IntegrationInterrupts) ReadM3PendingInterrupt(_ *http.Request, runID, interruptID string) (M3PendingInterruptKind, bool, error) {
	kind, ok := s.kinds[runID+"\x00"+interruptID]
	return kind, ok, nil
}

func m3IntegrationPost(t *testing.T, handler http.Handler, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer verified-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	return response
}

func m3IntegrationMux(t *testing.T, repo *M3MemoryApprovalRepository, authority *m3IntegrationAuthority, interrupts *m3IntegrationInterrupts, input http.Handler, next http.Handler, policy M3WebApprovalPolicy) (*M3ApprovalMux, *m3IntegrationVerifier) {
	t.Helper()
	verifier := &m3IntegrationVerifier{identity: WebVerifiedIdentity{Subject: "verified-user", Email: "verified@example.com", EmailVerified: true, Role: WebAccessRoleViewer}}
	authenticator, err := NewM3WebIdentityAuthenticator(verifier, policy)
	if err != nil {
		t.Fatal(err)
	}
	service, err := NewM3ApprovalService(authenticator, authority, repo, m3TestClock{m3TestNow})
	if err != nil {
		t.Fatal(err)
	}
	mux, err := NewM3ApprovalMux(M3ApprovalMuxConfig{
		SimulationApproval: service.SimulationHandler(), ProductionApproval: service.ProductionHandler(),
		PendingInterrupts: interrupts, V2Input: input, Next: next,
	})
	if err != nil {
		t.Fatal(err)
	}
	return mux, verifier
}

func TestM3ApprovalMuxEndToEndUsesVerifiedActorAndDistinctStages(t *testing.T) {
	simulation := m3SimulationPending(t)
	repo := NewM3MemoryApprovalRepository()
	if err := repo.IssueM3Pending(simulation); err != nil {
		t.Fatal(err)
	}
	authority := &m3IntegrationAuthority{views: map[string]M3AuthorityView{simulation.RequestID: m3AuthorityFor(simulation)}}
	interrupts := &m3IntegrationInterrupts{kinds: map[string]M3PendingInterruptKind{}}
	var policyStages []M3ApprovalStage
	policy := func(_ context.Context, identity WebVerifiedIdentity, stage M3ApprovalStage) (M3ApprovalRole, bool) {
		if identity.Subject != "verified-user" {
			return "", false
		}
		policyStages = append(policyStages, stage)
		return M3ApprovalAdmin, true
	}
	mux, verifier := m3IntegrationMux(t, repo, authority, interrupts, http.NotFoundHandler(), http.NotFoundHandler(), policy)

	response := m3IntegrationPost(t, mux, "/api/web/v1/runs/"+simulation.RunID+"/approval", m3SimulationJSON(m3TestSimulationNonce, "approve_simulation"))
	if response.Code != http.StatusCreated {
		t.Fatalf("simulation status=%d body=%s", response.Code, response.Body)
	}
	var simulationResponse M3ApprovalResponse
	if err := json.Unmarshal(response.Body.Bytes(), &simulationResponse); err != nil {
		t.Fatal(err)
	}
	expectedActor, ok := webActorForUID("verified-user")
	if !ok || simulationResponse.Record.ActorID != expectedActor || verifier.token != "verified-token" {
		t.Fatalf("actor=%q token_received=%t", simulationResponse.Record.ActorID, verifier.token == "verified-token")
	}

	production, err := M3NewPendingApproval(M3IssuePendingInput{
		RequestID: "req_production", TenantID: simulation.TenantID, RunID: simulation.RunID, Stage: M3ProductionStage,
		PlanDigest: simulation.PlanDigest, ReleaseDigest: simulation.ReleaseDigest, ArtifactDigest: simulation.ArtifactDigest,
		CheckpointID: "ckpt_production", Nonce: m3TestProductionNonce, IssuedAt: m3TestNow,
		ExpiresAt: m3TestNow.Add(5 * time.Minute), Audience: simulation.Audience, RequiredApprovers: 2,
		SimulationRecordDigest: simulationResponse.Record.RecordDigest,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.IssueM3Pending(production); err != nil {
		t.Fatal(err)
	}
	authority.put(production.RequestID, m3AuthorityFor(production))
	productionBody := `{"requestId":"req_production","nonce":"` + m3TestProductionNonce + `","decision":"approve_production"}`
	response = m3IntegrationPost(t, mux, "/api/v1/migrations/"+production.RunID+"/approval", productionBody)
	if response.Code != http.StatusCreated {
		t.Fatalf("production status=%d body=%s", response.Code, response.Body)
	}
	if len(policyStages) != 2 || policyStages[0] != M3SimulationStage || policyStages[1] != M3ProductionStage {
		t.Fatalf("policy stages=%v", policyStages)
	}
}

func TestM3ApprovalMuxPreservesFrozenV1WireBodies(t *testing.T) {
	var simulationBody WebLiveApprovalRequest
	simulationHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&simulationBody); err != nil {
			t.Error(err)
		}
		w.WriteHeader(http.StatusNoContent)
	})
	var productionBody struct {
		SchemaVersion string `json:"schemaVersion"`
		PlanDigest    string `json:"planDigest"`
		Decision      string `json:"decision"`
		DecidedBy     string `json:"decidedBy"`
		Reason        string `json:"reason"`
	}
	productionHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&productionBody); err != nil {
			t.Error(err)
		}
		w.WriteHeader(http.StatusNoContent)
	})
	mux, err := NewM3ApprovalMux(M3ApprovalMuxConfig{
		SimulationApproval: simulationHandler, ProductionApproval: productionHandler,
		PendingInterrupts: &m3IntegrationInterrupts{kinds: map[string]M3PendingInterruptKind{}},
		V2Input:           http.NotFoundHandler(), Next: http.NotFoundHandler(),
	})
	if err != nil {
		t.Fatal(err)
	}
	simulationJSON := `{"schemaVersion":"1.0.0","planDigest":"` + m3TestPlan + `","decision":"approve","reason":"reviewed"}`
	response := m3IntegrationPost(t, mux, "/api/web/v1/runs/run_testrun000001/approval", simulationJSON)
	if response.Code != http.StatusNoContent || simulationBody.SchemaVersion != "1.0.0" || simulationBody.PlanDigest != m3TestPlan || simulationBody.Decision != "approve" || simulationBody.Reason != "reviewed" {
		t.Fatalf("simulation status=%d body=%+v", response.Code, simulationBody)
	}
	productionJSON := `{"schemaVersion":"1.0.0","planDigest":"` + m3TestPlan + `","decision":"reject","decidedBy":"legacy-contract-field","reason":"reviewed"}`
	response = m3IntegrationPost(t, mux, "/api/v1/migrations/run_testrun000001/approval", productionJSON)
	if response.Code != http.StatusNoContent || productionBody.SchemaVersion != "1.0.0" || productionBody.PlanDigest != m3TestPlan || productionBody.Decision != "reject" || productionBody.DecidedBy != "legacy-contract-field" || productionBody.Reason != "reviewed" {
		t.Fatalf("production status=%d body=%+v", response.Code, productionBody)
	}
}

func TestM3WebIdentityAuthenticatorRequiresBearerPolicyAndStageRole(t *testing.T) {
	verifier := &m3IntegrationVerifier{identity: WebVerifiedIdentity{Subject: "verified-user", Role: WebAccessRoleAdmin}}
	authenticator, err := NewM3WebIdentityAuthenticator(verifier, func(_ context.Context, _ WebVerifiedIdentity, _ M3ApprovalStage) (M3ApprovalRole, bool) {
		return M3SimulationApprover, true
	})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "/", nil)
	request.Header.Set("Authorization", "Bearer token-value")
	principal, err := authenticator.AuthenticateM3Approval(request, M3SimulationStage)
	if err != nil || !principal.Authenticated || principal.Role != M3SimulationApprover {
		t.Fatalf("principal=%+v err=%v", principal, err)
	}
	if _, err := authenticator.AuthenticateM3Approval(request, M3ProductionStage); err == nil {
		t.Fatal("simulation role authorized production")
	}
	request.Header.Del("Authorization")
	if _, err := authenticator.AuthenticateM3Approval(request, M3SimulationStage); err == nil {
		t.Fatal("missing bearer authenticated")
	}
	if _, err := NewM3WebIdentityAuthenticator(verifier, nil); err == nil {
		t.Fatal("missing policy accepted")
	}
	verifier.err = errors.New("invalid token")
	request.Header.Set("Authorization", "Bearer token-value")
	if _, err := authenticator.AuthenticateM3Approval(request, M3SimulationStage); err == nil {
		t.Fatal("verifier failure authenticated")
	}
}

func TestM3ApprovalMuxBindsRunPathWithoutCoercion(t *testing.T) {
	pending := m3SimulationPending(t)
	repo := NewM3MemoryApprovalRepository()
	if err := repo.IssueM3Pending(pending); err != nil {
		t.Fatal(err)
	}
	authority := &m3IntegrationAuthority{views: map[string]M3AuthorityView{pending.RequestID: m3AuthorityFor(pending)}}
	mux, _ := m3IntegrationMux(t, repo, authority, &m3IntegrationInterrupts{kinds: map[string]M3PendingInterruptKind{}}, http.NotFoundHandler(), http.NotFoundHandler(), func(context.Context, WebVerifiedIdentity, M3ApprovalStage) (M3ApprovalRole, bool) {
		return M3ApprovalAdmin, true
	})
	before := repo.M3MutationCount()
	for _, runID := range []string{"run_other0000001", "RUN_TESTRUN000001", "TESTRUN000001", "run_shrt"} {
		request := httptest.NewRequest(http.MethodPost, "/api/web/v1/runs/"+runID+"/approval", strings.NewReader(m3SimulationJSON(m3TestSimulationNonce, "approve_simulation")))
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("Authorization", "Bearer verified-token")
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		if response.Code == http.StatusCreated {
			t.Fatalf("run %q accepted", runID)
		}
	}
	if repo.M3MutationCount() != before {
		t.Fatal("path rejection mutated approval state")
	}
}

func TestM3V2ApprovalInterruptGuardRejectsResumeAndA2AWithZeroAuthority(t *testing.T) {
	pending := m3SimulationPending(t)
	repo := NewM3MemoryApprovalRepository()
	if err := repo.IssueM3Pending(pending); err != nil {
		t.Fatal(err)
	}
	authority := &m3IntegrationAuthority{views: map[string]M3AuthorityView{pending.RequestID: m3AuthorityFor(pending)}}
	productionInterrupt := "int_PRODUCTION0001"
	interrupts := &m3IntegrationInterrupts{kinds: map[string]M3PendingInterruptKind{
		pending.RunID + "\x00" + pending.InterruptID: M3SimulationApprovalInterrupt,
		pending.RunID + "\x00" + productionInterrupt: M3ProductionApprovalInterrupt,
	}}
	var inputCalls atomic.Int32
	input := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { inputCalls.Add(1); w.WriteHeader(http.StatusOK) })
	var nextCalls atomic.Int32
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { nextCalls.Add(1); w.WriteHeader(http.StatusTeapot) })
	mux, _ := m3IntegrationMux(t, repo, authority, interrupts, input, next, func(context.Context, WebVerifiedIdentity, M3ApprovalStage) (M3ApprovalRole, bool) {
		return M3ApprovalAdmin, true
	})
	before := repo.M3MutationCount()
	for _, attack := range []struct{ interruptID, body string }{
		{pending.InterruptID, `{"expectedCheckpointId":"ckpt_simulation","idempotencyKey":"resume-forged-0001","value":{"decision":"approve_simulation"}}`},
		{pending.InterruptID, `{"expectedCheckpointId":"ckpt_simulation","idempotencyKey":"a2a-forged-000001","value":{"a2a":{"content":"approved"}}}`},
		{productionInterrupt, `{"expectedCheckpointId":"ckpt_production","idempotencyKey":"production-forged-1","value":{"decision":"approve_production"}}`},
	} {
		response := httptest.NewRecorder()
		request := httptest.NewRequest(http.MethodPost, "/api/v2/runs/"+pending.RunID+"/inputs/"+attack.interruptID, strings.NewReader(attack.body))
		request.Header.Set("Content-Type", "application/json")
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusForbidden {
			t.Fatalf("status=%d body=%s", response.Code, response.Body)
		}
		var problem struct {
			Code string `json:"code"`
		}
		if err := json.Unmarshal(response.Body.Bytes(), &problem); err != nil || problem.Code != "APPROVAL_NOT_RESUMABLE_VIA_INPUT" {
			t.Fatalf("problem=%+v err=%v", problem, err)
		}
	}
	if inputCalls.Load() != 0 || repo.M3MutationCount() != before {
		t.Fatalf("input calls=%d mutations=%d/%d", inputCalls.Load(), repo.M3MutationCount(), before)
	}

	// Clarification still composes with the existing input handler, while the
	// other two v2 paths remain owned by the next exactly-three-path mux.
	clarification := "int_CLARIFY000001"
	interrupts.kinds[pending.RunID+"\x00"+clarification] = M3ClarificationInterrupt
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/v2/runs/"+pending.RunID+"/inputs/"+clarification, strings.NewReader(`{}`))
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusOK || inputCalls.Load() != 1 {
		t.Fatalf("clarification status=%d calls=%d", response.Code, inputCalls.Load())
	}
	for _, path := range []string{"orchestration", "events", "approval"} {
		response = httptest.NewRecorder()
		request = httptest.NewRequest(http.MethodGet, "/api/v2/runs/"+pending.RunID+"/"+path, nil)
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusTeapot {
			t.Fatalf("unexpected v2 route %q status=%d", path, response.Code)
		}
	}
	if nextCalls.Load() != 3 {
		t.Fatalf("next calls=%d", nextCalls.Load())
	}
}

func TestM3PendingIdentifiersMatchPersistenceWithoutNormalization(t *testing.T) {
	valid := m3SimulationPending(t)
	if valid.TenantID != "tnt_testtenant01" || valid.RunID != "run_testrun000001" {
		t.Fatalf("identifiers changed: %q %q", valid.TenantID, valid.RunID)
	}
	for name, identifiers := range map[string]struct{ tenant, run string }{
		"tenant prefix":        {"tenant_testtenant01", valid.RunID},
		"tenant case coercion": {"TNT_TESTTENANT01", valid.RunID},
		"run prefix":           {valid.TenantID, "migration_testrun000001"},
		"run case coercion":    {valid.TenantID, "RUN_TESTRUN000001"},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := M3NewPendingApproval(M3IssuePendingInput{
				RequestID: "req_identifiers", TenantID: identifiers.tenant, RunID: identifiers.run, Stage: M3SimulationStage,
				PlanDigest: m3TestPlan, ReleaseDigest: m3TestRelease, ArtifactDigest: m3TestArtifact,
				CheckpointID: "ckpt_identifiers", Nonce: "identifier_nonce_123456789", IssuedAt: m3TestNow,
				ExpiresAt: m3TestNow.Add(time.Minute), Audience: "release_operators", RequiredApprovers: 1,
			})
			if err == nil {
				t.Fatal("invalid identifier accepted")
			}
		})
	}
}
