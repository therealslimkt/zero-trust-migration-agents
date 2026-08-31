package main

// Approval HTTP integration is intentionally composable and is not wired by
// main.go in this milestone. The staged PostgreSQL adapter must be supplied by
// the persistence lane after that implementation is joined; the memory store
// remains a local/test reference only.

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
)

// M3WebApprovalPolicy is a mandatory server-side authorization callback. The
// verified identity is input to policy; neither the approval body nor headers
// other than the verified bearer token can choose a role.
type M3WebApprovalPolicy func(context.Context, WebVerifiedIdentity, M3ApprovalStage) (M3ApprovalRole, bool)

type M3WebIdentityAuthenticator struct {
	verifier WebIdentityVerifier
	policy   M3WebApprovalPolicy
}

func NewM3WebIdentityAuthenticator(verifier WebIdentityVerifier, policy M3WebApprovalPolicy) (*M3WebIdentityAuthenticator, error) {
	if verifier == nil || policy == nil {
		return nil, errors.New("m3 approval verifier and authorization policy are required")
	}
	return &M3WebIdentityAuthenticator{verifier: verifier, policy: policy}, nil
}

func (a *M3WebIdentityAuthenticator) AuthenticateM3Approval(r *http.Request, stage M3ApprovalStage) (M3Principal, error) {
	if a == nil || a.verifier == nil || a.policy == nil || !m3RolePermits(M3ApprovalAdmin, stage) {
		return M3Principal{}, errM3Rejected
	}
	token, ok := webBearerToken(r)
	if !ok {
		return M3Principal{}, errM3Rejected
	}
	identity, err := a.verifier.VerifyWebIdentity(r.Context(), token)
	if err != nil || !webValidSubject(identity.Subject) {
		return M3Principal{}, errM3Rejected
	}
	role, allowed := a.policy(r.Context(), identity, stage)
	if !allowed || !m3RolePermits(role, stage) {
		return M3Principal{}, errM3Rejected
	}
	actorID, ok := webActorForUID(identity.Subject)
	if !ok || !m3ActorIDPattern.MatchString(actorID) {
		return M3Principal{}, errM3Rejected
	}
	return M3Principal{ActorID: actorID, Role: role, Authenticated: true}, nil
}

type M3PendingInterruptKind string

const (
	M3ClarificationInterrupt      M3PendingInterruptKind = "clarification"
	M3TaskInputInterrupt          M3PendingInterruptKind = "task_input"
	M3SimulationApprovalInterrupt M3PendingInterruptKind = "simulation_approval"
	M3ProductionApprovalInterrupt M3PendingInterruptKind = "production_approval"
)

type M3PendingInterruptSource interface {
	// Implementations read authenticated server-side pending state. They must
	// not infer kind from the resume body, A2A content, or caller headers.
	ReadM3PendingInterrupt(*http.Request, string, string) (M3PendingInterruptKind, bool, error)
}

type M3ApprovalMuxConfig struct {
	SimulationApproval http.Handler
	ProductionApproval http.Handler
	PendingInterrupts  M3PendingInterruptSource
	V2Input            http.Handler
	Next               http.Handler
}

// M3ApprovalMux dispatches only the two frozen v1 approval paths documented by
// the existing contracts and the existing v2 input path's approval guard. It
// does not decode or reshape v1 bodies; callers inject the contract-preserving
// v1 handlers. It adds no approval route to the exactly-three-path v2 API.
type M3ApprovalMux struct {
	simulationApproval http.Handler
	productionApproval http.Handler
	pendingInterrupts  M3PendingInterruptSource
	v2Input            http.Handler
	next               http.Handler
}

func NewM3ApprovalMux(config M3ApprovalMuxConfig) (*M3ApprovalMux, error) {
	if config.SimulationApproval == nil || config.ProductionApproval == nil || config.PendingInterrupts == nil || config.V2Input == nil {
		return nil, errors.New("m3 approval mux dependencies are required")
	}
	next := config.Next
	if next == nil {
		next = http.NotFoundHandler()
	}
	return &M3ApprovalMux{
		simulationApproval: config.SimulationApproval, productionApproval: config.ProductionApproval,
		pendingInterrupts: config.PendingInterrupts,
		v2Input:           config.V2Input, next: next,
	}, nil
}

func (m *M3ApprovalMux) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if m == nil || r == nil || r.URL == nil {
		m3WriteProblemCode(w, http.StatusNotFound, "M3_ROUTE_NOT_FOUND")
		return
	}
	// RawPath means an identifier was percent-encoded. Reject rather than
	// accepting a transformed spelling of a security binding.
	if r.URL.RawPath != "" {
		m3WriteProblemCode(w, http.StatusBadRequest, "M3_INVALID_PATH")
		return
	}
	segments := strings.Split(strings.TrimPrefix(r.URL.Path, "/"), "/")
	if runID, ok := m3SimulationApprovalPath(segments); ok {
		if !m3RunRE.MatchString(runID) {
			m3WriteProblemCode(w, http.StatusBadRequest, "M3_INVALID_RUN_ID")
			return
		}
		m.simulationApproval.ServeHTTP(w, m3WithExpectedApprovalRun(r, runID))
		return
	}
	if runID, ok := m3ProductionApprovalPath(segments); ok {
		if !m3RunRE.MatchString(runID) {
			m3WriteProblemCode(w, http.StatusBadRequest, "M3_INVALID_RUN_ID")
			return
		}
		m.productionApproval.ServeHTTP(w, m3WithExpectedApprovalRun(r, runID))
		return
	}
	if runID, interruptID, ok := m3V2InputPath(segments); ok {
		m.serveV2Input(w, r, runID, interruptID)
		return
	}
	m.next.ServeHTTP(w, r)
}

func m3SimulationApprovalPath(parts []string) (string, bool) {
	return m3PathRun(parts, []string{"api", "web", "v1", "runs"}, "approval")
}

func m3ProductionApprovalPath(parts []string) (string, bool) {
	return m3PathRun(parts, []string{"api", "v1", "migrations"}, "approval")
}

func m3PathRun(parts, prefix []string, final string) (string, bool) {
	if len(parts) != len(prefix)+2 || parts[len(parts)-1] != final {
		return "", false
	}
	for index := range prefix {
		if parts[index] != prefix[index] {
			return "", false
		}
	}
	return parts[len(prefix)], true
}

func m3V2InputPath(parts []string) (string, string, bool) {
	if len(parts) != 6 || parts[0] != "api" || parts[1] != "v2" || parts[2] != "runs" || parts[4] != "inputs" {
		return "", "", false
	}
	return parts[3], parts[5], true
}

func (m *M3ApprovalMux) serveV2Input(w http.ResponseWriter, r *http.Request, runID, interruptID string) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		m3WriteProblemCode(w, http.StatusMethodNotAllowed, "M3_METHOD_NOT_ALLOWED")
		return
	}
	if !m3RunRE.MatchString(runID) || !m3InterruptPattern.MatchString(interruptID) {
		m3WriteProblemCode(w, http.StatusBadRequest, "M3_INVALID_INPUT_PATH")
		return
	}
	kind, found, err := m.pendingInterrupts.ReadM3PendingInterrupt(r, runID, interruptID)
	if err != nil || !found {
		m3WriteProblemCode(w, http.StatusNotFound, "M3_PENDING_INTERRUPT_NOT_FOUND")
		return
	}
	if kind == M3SimulationApprovalInterrupt || kind == M3ProductionApprovalInterrupt {
		m3WriteProblemCode(w, http.StatusForbidden, "APPROVAL_NOT_RESUMABLE_VIA_INPUT")
		return
	}
	if kind != M3ClarificationInterrupt && kind != M3TaskInputInterrupt {
		m3WriteProblemCode(w, http.StatusForbidden, "M3_INPUT_NOT_RESUMABLE")
		return
	}
	m.v2Input.ServeHTTP(w, r)
}

func m3WriteProblemCode(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(struct {
		Type   string `json:"type"`
		Title  string `json:"title"`
		Status int    `json:"status"`
		Code   string `json:"code"`
	}{Type: "about:blank", Title: "Request rejected", Status: status, Code: code})
}
