package main

// Milestone 3 approval boundary. Cloud SQL/PostgreSQL is the production
// transactional authority. The memory repository is only a local/test
// reference; BigQuery is downstream analytics and is never read here.

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const m3MaxApprovalBody int64 = 4096

type M3ApprovalStage string

const (
	M3SimulationStage M3ApprovalStage = "simulation"
	M3ProductionStage M3ApprovalStage = "production"
)

type M3ApprovalDecision string

const (
	M3Approve M3ApprovalDecision = "approve"
	M3Reject  M3ApprovalDecision = "reject"
)

type M3Clock interface{ Now() time.Time }

type m3SystemClock struct{}

func (m3SystemClock) Now() time.Time { return time.Now().UTC() }

// M3Principal is created only by the injected authenticator. No request body
// field can select the actor.
type M3Principal struct {
	ActorID       string
	Authenticated bool
}

type M3Authenticator interface {
	AuthenticateM3Approval(*http.Request) (M3Principal, error)
}

// M3AuthorityView is the result of a server-side authority/transactional-state
// read. It deliberately repeats every security binding so disagreement with
// the pending request fails closed.
type M3AuthorityView struct {
	TenantID        string
	RunID           string
	Stage           M3ApprovalStage
	PlanDigest      string
	ReleaseDigest   string
	ArtifactDigest  string
	InterruptID     string
	CheckpointID    string
	Audience        string
	ApproverCount   int
	Authorized      bool
	ArtifactPresent bool
}

type M3ApprovalAuthority interface {
	ReadM3ApprovalAuthority(context.Context, M3Principal, string, M3ApprovalStage) (M3AuthorityView, error)
}

type M3PendingApproval struct {
	RequestID              string
	TenantID               string
	RunID                  string
	Stage                  M3ApprovalStage
	PlanDigest             string
	ReleaseDigest          string
	ArtifactDigest         string
	InterruptID            string
	CheckpointID           string
	NonceDigest            string
	IssuedAt               time.Time
	ExpiresAt              time.Time
	Audience               string
	RequiredApprovers      int
	SimulationRecordDigest string
	RequestDigest          string
}

type M3ApprovalRecord struct {
	RecordID               string             `json:"recordId"`
	RecordDigest           string             `json:"recordDigest"`
	RequestDigest          string             `json:"requestDigest"`
	TenantID               string             `json:"tenantId"`
	RunID                  string             `json:"runId"`
	Stage                  M3ApprovalStage    `json:"stage"`
	PlanDigest             string             `json:"planDigest"`
	ReleaseDigest          string             `json:"releaseDigest"`
	ArtifactDigest         string             `json:"artifactDigest"`
	SimulationRecordDigest string             `json:"simulationRecordDigest,omitempty"`
	ActorID                string             `json:"actorId"`
	Decision               M3ApprovalDecision `json:"decision"`
	RecordedAt             time.Time          `json:"recordedAt"`
}

type M3DeterminismMetadata struct {
	ModelCalls  int `json:"modelCalls"`
	Concurrency int `json:"concurrency"`
	GraphDepth  int `json:"graphDepth"`
}

type M3ApprovalResponse struct {
	Record      M3ApprovalRecord      `json:"record"`
	Trace       []string              `json:"trace"`
	Determinism M3DeterminismMetadata `json:"determinism"`
}

type M3ApprovalRepository interface {
	LoadM3Pending(context.Context, string) (M3PendingApproval, bool)
	CompareAndRecordM3(context.Context, M3PendingApproval, M3AuthorityView, M3Principal, string, M3ApprovalDecision, time.Time) (M3ApprovalRecord, bool)
}

var (
	m3IDPattern     = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_.:-]{2,127}$`)
	m3DigestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	m3NoncePattern  = regexp.MustCompile(`^[A-Za-z0-9_-]{24,256}$`)
	errM3Rejected   = errors.New("approval rejected")
)

func m3CanonicalDigest(domain string, fields ...string) string {
	h := sha256.New()
	write := func(value string) {
		var size [4]byte
		binary.BigEndian.PutUint32(size[:], uint32(len(value)))
		_, _ = h.Write(size[:])
		_, _ = h.Write([]byte(value))
	}
	write("m3-approval-v1")
	write(domain)
	for _, field := range fields {
		write(field)
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil))
}

func m3NonceDigest(nonce string) string {
	return m3CanonicalDigest("approval.nonce", "nonce", nonce)
}

func m3InterruptID(p M3PendingApproval) string {
	simulation := p.SimulationRecordDigest
	if simulation == "" {
		simulation = "none"
	}
	subject := m3CanonicalDigest("approval.subject",
		"tenant", p.TenantID, "stage", string(p.Stage), "plan", p.PlanDigest,
		"release", p.ReleaseDigest, "artifact", p.ArtifactDigest, "simulation", simulation)
	digest := strings.TrimPrefix(m3CanonicalDigest("approval.interrupt", "tenant", p.TenantID, "subject", subject), "sha256:")
	return "int_" + digest[:40]
}

func m3PendingDigest(p M3PendingApproval) string {
	simulation := p.SimulationRecordDigest
	if simulation == "" {
		simulation = "none"
	}
	return m3CanonicalDigest("approval.request",
		"request", p.RequestID, "tenant", p.TenantID, "run", p.RunID,
		"stage", string(p.Stage), "plan", p.PlanDigest, "release", p.ReleaseDigest,
		"artifact", p.ArtifactDigest, "interrupt", p.InterruptID,
		"checkpoint", p.CheckpointID, "nonce", p.NonceDigest,
		"issued", p.IssuedAt.UTC().Format(time.RFC3339Nano),
		"expires", p.ExpiresAt.UTC().Format(time.RFC3339Nano), "audience", p.Audience,
		"quorum", strconv.Itoa(p.RequiredApprovers), "simulation", simulation)
}

type M3IssuePendingInput struct {
	RequestID, TenantID, RunID   string
	Stage                        M3ApprovalStage
	PlanDigest, ReleaseDigest    string
	ArtifactDigest, CheckpointID string
	Nonce                        string
	IssuedAt, ExpiresAt          time.Time
	Audience                     string
	RequiredApprovers            int
	SimulationRecordDigest       string
}

func M3NewPendingApproval(in M3IssuePendingInput) (M3PendingApproval, error) {
	p := M3PendingApproval{
		RequestID: in.RequestID, TenantID: in.TenantID, RunID: in.RunID, Stage: in.Stage,
		PlanDigest: in.PlanDigest, ReleaseDigest: in.ReleaseDigest, ArtifactDigest: in.ArtifactDigest,
		CheckpointID: in.CheckpointID, NonceDigest: m3NonceDigest(in.Nonce),
		IssuedAt: in.IssuedAt.UTC(), ExpiresAt: in.ExpiresAt.UTC(), Audience: in.Audience,
		RequiredApprovers: in.RequiredApprovers, SimulationRecordDigest: in.SimulationRecordDigest,
	}
	p.InterruptID = m3InterruptID(p)
	p.RequestDigest = m3PendingDigest(p)
	if !m3ValidPending(p) || !m3NoncePattern.MatchString(in.Nonce) {
		return M3PendingApproval{}, errM3Rejected
	}
	return p, nil
}

func m3ValidPending(p M3PendingApproval) bool {
	if !m3IDPattern.MatchString(p.RequestID) || !m3IDPattern.MatchString(p.TenantID) ||
		!m3IDPattern.MatchString(p.RunID) || !m3IDPattern.MatchString(p.InterruptID) ||
		!m3IDPattern.MatchString(p.CheckpointID) || !m3IDPattern.MatchString(p.Audience) ||
		!m3DigestPattern.MatchString(p.PlanDigest) || !m3DigestPattern.MatchString(p.ReleaseDigest) ||
		!m3DigestPattern.MatchString(p.ArtifactDigest) || !m3DigestPattern.MatchString(p.NonceDigest) ||
		p.RequiredApprovers < 1 || !p.IssuedAt.Before(p.ExpiresAt) {
		return false
	}
	if p.Stage == M3SimulationStage {
		if p.SimulationRecordDigest != "" {
			return false
		}
	} else if p.Stage == M3ProductionStage {
		if !m3DigestPattern.MatchString(p.SimulationRecordDigest) {
			return false
		}
	} else {
		return false
	}
	return m3Equal(p.InterruptID, m3InterruptID(p)) && m3Equal(p.RequestDigest, m3PendingDigest(p))
}

func m3Equal(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

type m3Evaluation struct {
	pending   M3PendingApproval
	authority M3AuthorityView
	principal M3Principal
	nonce     string
	now       time.Time
	prior     *M3ApprovalRecord
}

func m3EvaluateAdversarial(e m3Evaluation) bool {
	// The fixed optimizer normalizes the complete threat battery and repeats it.
	// No model, plugin, callback, or user-defined rule participates.
	var previous string
	for pass := 0; pass < 2; pass++ {
		progression := e.pending.Stage == M3SimulationStage
		if e.prior != nil {
			progression = e.prior.Stage == M3SimulationStage && e.prior.Decision == M3Approve &&
				m3Equal(e.prior.TenantID, e.pending.TenantID) && m3Equal(e.prior.RunID, e.pending.RunID) &&
				m3Equal(e.prior.PlanDigest, e.pending.PlanDigest) && m3Equal(e.prior.ReleaseDigest, e.pending.ReleaseDigest) &&
				m3Equal(e.prior.ArtifactDigest, e.pending.ArtifactDigest) &&
				m3Equal(e.prior.RecordDigest, e.pending.SimulationRecordDigest)
		}
		checks := []bool{
			e.principal.Authenticated, e.authority.Authorized,
			e.authority.Stage == e.pending.Stage,
			m3Equal(e.authority.TenantID, e.pending.TenantID), m3Equal(e.authority.RunID, e.pending.RunID),
			m3Equal(e.authority.PlanDigest, e.pending.PlanDigest), m3Equal(e.authority.ReleaseDigest, e.pending.ReleaseDigest),
			m3Equal(e.authority.ArtifactDigest, e.pending.ArtifactDigest), e.authority.ArtifactPresent,
			m3Equal(e.authority.InterruptID, e.pending.InterruptID), m3Equal(e.authority.CheckpointID, e.pending.CheckpointID),
			m3Equal(e.authority.Audience, e.pending.Audience), e.authority.ApproverCount >= e.pending.RequiredApprovers,
			m3NoncePattern.MatchString(e.nonce), m3Equal(m3NonceDigest(e.nonce), e.pending.NonceDigest),
			!e.now.Before(e.pending.IssuedAt), e.now.Before(e.pending.ExpiresAt), progression,
		}
		encoded := make([]byte, len(checks))
		all := true
		for i, check := range checks {
			if check {
				encoded[i] = 1
			} else {
				all = false
			}
		}
		verdict := hex.EncodeToString(encoded)
		if !all || (pass > 0 && !m3Equal(verdict, previous)) {
			return false
		}
		previous = verdict
	}
	return true
}

type M3MemoryApprovalRepository struct {
	mu         sync.Mutex
	pending    map[string]M3PendingApproval
	records    map[string]M3ApprovalRecord
	usedNonces map[string]struct{}
}

func NewM3MemoryApprovalRepository() *M3MemoryApprovalRepository {
	return &M3MemoryApprovalRepository{pending: map[string]M3PendingApproval{}, records: map[string]M3ApprovalRecord{}, usedNonces: map[string]struct{}{}}
}

func m3RecordKey(tenant, run string, stage M3ApprovalStage) string {
	return tenant + "\x00" + run + "\x00" + string(stage)
}

func (r *M3MemoryApprovalRepository) IssueM3Pending(p M3PendingApproval) error {
	if r == nil || !m3ValidPending(p) {
		return errM3Rejected
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.pending[p.RequestID]; exists {
		return errM3Rejected
	}
	for _, issued := range r.pending {
		if m3Equal(issued.NonceDigest, p.NonceDigest) {
			return errM3Rejected
		}
	}
	if p.Stage == M3ProductionStage {
		prior, ok := r.records[m3RecordKey(p.TenantID, p.RunID, M3SimulationStage)]
		if !ok || prior.Decision != M3Approve || !m3Equal(prior.RecordDigest, p.SimulationRecordDigest) ||
			!m3Equal(prior.PlanDigest, p.PlanDigest) || !m3Equal(prior.ReleaseDigest, p.ReleaseDigest) ||
			!m3Equal(prior.ArtifactDigest, p.ArtifactDigest) {
			return errM3Rejected
		}
	}
	r.pending[p.RequestID] = p
	return nil
}

func (r *M3MemoryApprovalRepository) LoadM3Pending(_ context.Context, requestID string) (M3PendingApproval, bool) {
	if r == nil {
		return M3PendingApproval{}, false
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	p, ok := r.pending[requestID]
	return p, ok
}

func (r *M3MemoryApprovalRepository) CompareAndRecordM3(_ context.Context, expected M3PendingApproval, authority M3AuthorityView, principal M3Principal, nonce string, decision M3ApprovalDecision, now time.Time) (M3ApprovalRecord, bool) {
	if r == nil {
		return M3ApprovalRecord{}, false
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	current, ok := r.pending[expected.RequestID]
	key := m3RecordKey(expected.TenantID, expected.RunID, expected.Stage)
	nonceKey := m3NonceDigest(nonce)
	_, nonceUsed := r.usedNonces[nonceKey]
	_, decided := r.records[key]
	var prior *M3ApprovalRecord
	if value, found := r.records[m3RecordKey(expected.TenantID, expected.RunID, M3SimulationStage)]; found {
		copy := value
		prior = &copy
	}
	if !ok || current != expected || nonceUsed || decided || (decision != M3Approve && decision != M3Reject) ||
		!m3EvaluateAdversarial(m3Evaluation{current, authority, principal, nonce, now.UTC(), prior}) {
		return M3ApprovalRecord{}, false
	}
	fields := []string{"request", current.RequestDigest, "tenant", current.TenantID, "run", current.RunID,
		"stage", string(current.Stage), "plan", current.PlanDigest, "release", current.ReleaseDigest,
		"artifact", current.ArtifactDigest, "simulation", current.SimulationRecordDigest,
		"actor", principal.ActorID, "decision", string(decision), "recorded", now.UTC().Format(time.RFC3339Nano)}
	digest := m3CanonicalDigest("approval.record", fields...)
	record := M3ApprovalRecord{RecordID: "apr_" + strings.TrimPrefix(digest, "sha256:")[:40], RecordDigest: digest,
		RequestDigest: current.RequestDigest, TenantID: current.TenantID, RunID: current.RunID, Stage: current.Stage,
		PlanDigest: current.PlanDigest, ReleaseDigest: current.ReleaseDigest, ArtifactDigest: current.ArtifactDigest,
		SimulationRecordDigest: current.SimulationRecordDigest, ActorID: principal.ActorID, Decision: decision, RecordedAt: now.UTC()}
	r.records[key] = record
	r.usedNonces[nonceKey] = struct{}{}
	return record, true
}

func (r *M3MemoryApprovalRepository) M3MutationCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.pending) + len(r.records) + len(r.usedNonces)
}

type M3ApprovalService struct {
	Auth       M3Authenticator
	Authority  M3ApprovalAuthority
	Repository M3ApprovalRepository
	Clock      M3Clock
}

func NewM3ApprovalService(auth M3Authenticator, authority M3ApprovalAuthority, repository M3ApprovalRepository, clock M3Clock) (*M3ApprovalService, error) {
	if auth == nil || authority == nil || repository == nil || clock == nil {
		return nil, errors.New("m3 approval dependencies required")
	}
	return &M3ApprovalService{auth, authority, repository, clock}, nil
}

type m3SimulationBody struct {
	RequestID string `json:"requestId"`
	Nonce     string `json:"nonce"`
	Decision  string `json:"decision"`
}
type m3ProductionBody struct {
	RequestID string `json:"requestId"`
	Nonce     string `json:"nonce"`
	Decision  string `json:"decision"`
}

func (s *M3ApprovalService) SimulationHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body m3SimulationBody
		if !m3DecodeApproval(w, r, &body) {
			return
		}
		decision, ok := m3StageDecision(M3SimulationStage, body.Decision)
		if !ok {
			m3WriteRejection(w, http.StatusForbidden)
			return
		}
		s.m3Handle(w, r, body.RequestID, body.Nonce, M3SimulationStage, decision)
	})
}
func (s *M3ApprovalService) ProductionHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body m3ProductionBody
		if !m3DecodeApproval(w, r, &body) {
			return
		}
		decision, ok := m3StageDecision(M3ProductionStage, body.Decision)
		if !ok {
			m3WriteRejection(w, http.StatusForbidden)
			return
		}
		s.m3Handle(w, r, body.RequestID, body.Nonce, M3ProductionStage, decision)
	})
}

func m3StageDecision(stage M3ApprovalStage, raw string) (M3ApprovalDecision, bool) {
	if stage == M3SimulationStage {
		if raw == "approve_simulation" {
			return M3Approve, true
		}
		if raw == "reject_simulation" {
			return M3Reject, true
		}
	}
	if stage == M3ProductionStage {
		if raw == "approve_production" {
			return M3Approve, true
		}
		if raw == "reject_production" {
			return M3Reject, true
		}
	}
	return "", false
}

func (s *M3ApprovalService) m3Handle(w http.ResponseWriter, r *http.Request, requestID, nonce string, stage M3ApprovalStage, decision M3ApprovalDecision) {
	if !m3IDPattern.MatchString(requestID) || !m3NoncePattern.MatchString(nonce) {
		m3WriteRejection(w, http.StatusForbidden)
		return
	}
	principal, err := s.Auth.AuthenticateM3Approval(r)
	if err != nil || !principal.Authenticated || !m3IDPattern.MatchString(principal.ActorID) {
		m3WriteRejection(w, http.StatusForbidden)
		return
	}
	pending, ok := s.Repository.LoadM3Pending(r.Context(), requestID)
	if !ok || pending.Stage != stage {
		m3WriteRejection(w, http.StatusForbidden)
		return
	}
	authority, err := s.Authority.ReadM3ApprovalAuthority(r.Context(), principal, requestID, stage)
	if err != nil {
		m3WriteRejection(w, http.StatusForbidden)
		return
	}
	record, ok := s.Repository.CompareAndRecordM3(r.Context(), pending, authority, principal, nonce, decision, s.Clock.Now())
	if !ok {
		m3WriteRejection(w, http.StatusForbidden)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(M3ApprovalResponse{
		Record: record,
		Trace:  []string{"request_observed", "authenticated_authority_read", "bindings_verified", "immutable_decision_recorded"},
		Determinism: M3DeterminismMetadata{
			ModelCalls: 0, Concurrency: 1, GraphDepth: 0,
		},
	})
}

func m3DecodeApproval(w http.ResponseWriter, r *http.Request, target any) bool {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		m3WriteRejection(w, http.StatusMethodNotAllowed)
		return false
	}
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		m3WriteRejection(w, http.StatusUnsupportedMediaType)
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, m3MaxApprovalBody)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil {
		m3WriteRejection(w, http.StatusBadRequest)
		return false
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		m3WriteRejection(w, http.StatusBadRequest)
		return false
	}
	return true
}

func m3WriteRejection(w http.ResponseWriter, status int) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"type": "about:blank", "title": "Approval rejected", "status": status, "code": "approval_rejected", "trace": []string{"fail_closed_rejection"}})
}
