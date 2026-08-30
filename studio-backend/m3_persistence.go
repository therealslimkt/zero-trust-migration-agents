package main

// m3_persistence.go is the PostgreSQL/Cloud SQL authority for v2 workflow
// lifecycle. Every command uses an explicit transaction. Authoritative state
// and its sanitized event are committed together; callers never publish an
// event before the transaction commits.

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

var (
	ErrM3Invalid          = errors.New("m3 persistence: invalid command")
	ErrM3NotFound         = errors.New("m3 persistence: not found")
	ErrM3Conflict         = errors.New("m3 persistence: conflict")
	ErrM3RevisionConflict = errors.New("m3 persistence: revision conflict")
	ErrM3IdempotencyReuse = errors.New("m3 persistence: idempotency key reused")
	ErrM3StaleLease       = errors.New("m3 persistence: stale lease")
	ErrM3LeaseUnavailable = errors.New("m3 persistence: lease unavailable")
	ErrM3DeadLettered     = errors.New("m3 persistence: dead lettered")
)

type M3RunState string

const (
	M3RunCreated          M3RunState = "created"
	M3RunRunning          M3RunState = "running"
	M3RunAwaitingInput    M3RunState = "awaiting_input"
	M3RunAwaitingApproval M3RunState = "awaiting_approval"
	M3RunApproved         M3RunState = "approved"
	M3RunRejected         M3RunState = "rejected"
	M3RunSucceeded        M3RunState = "succeeded"
	M3RunFailed           M3RunState = "failed"
	M3RunCancelled        M3RunState = "cancelled"
	M3RunBudgetExhausted  M3RunState = "budget_exhausted"
	M3RunDeadLettered     M3RunState = "dead_lettered"
)

type M3CommandResult struct {
	TenantID      string     `json:"tenantId"`
	RunID         string     `json:"runId"`
	Revision      int64      `json:"revision"`
	State         M3RunState `json:"state"`
	EventSequence int64      `json:"eventSequence"`
	ApprovalID    string     `json:"approvalId,omitempty"`
	ReleaseID     string     `json:"releaseId,omitempty"`
	Replayed      bool       `json:"-"`
}

type M3Run struct {
	TenantID   string
	RunID      string
	State      M3RunState
	Revision   int64
	PlanDigest string
	ApprovalID string
	ReleaseID  string
	CreatedAt  time.Time
	UpdatedAt  time.Time
}

// M3Event contains a fixed, sanitized projection. It deliberately has no
// payload, prompt, row, free-text summary, actor, credential, or error detail.
type M3Event struct {
	TenantID     string
	RunID        string
	Sequence     int64
	EventID      string
	EventType    string
	RunRevision  int64
	RunState     M3RunState
	TaskID       string
	AttemptID    string
	ApprovalID   string
	ReleaseID    string
	Code         string
	EvidenceRefs []string
	OccurredAt   time.Time
}

type M3Lease struct {
	TenantID       string
	RunID          string
	TaskID         string
	AttemptID      string
	AttemptNumber  int
	Owner          string
	Token          string
	Generation     int64
	ExpiresAt      time.Time
	RecoveredLease bool
}

type M3Attempt struct {
	TenantID        string
	RunID           string
	TaskID          string
	AttemptID       string
	AttemptNumber   int
	LeaseGeneration int64
	WorkerID        string
	Status          string
	StartedAt       time.Time
	LastHeartbeatAt time.Time
	CompletedAt     *time.Time
	OutputDigest    string
	FailureCode     string
}

type M3OutboxDelivery struct {
	Event              M3Event
	DeliveryOwner      string
	DeliveryToken      string
	DeliveryGeneration int64
	DeliveryAttempts   int
	DeliveryExpiresAt  time.Time
}

type M3PostgresRepository struct {
	db    *sql.DB
	newID func(string) (string, error)
}

func NewM3PostgresRepository(db *sql.DB) (*M3PostgresRepository, error) {
	if db == nil {
		return nil, fmt.Errorf("%w: nil database", ErrM3Invalid)
	}
	return &M3PostgresRepository{db: db, newID: m3RandomID}, nil
}

var (
	m3TenantRE       = regexp.MustCompile(`^tnt_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3RunRE          = regexp.MustCompile(`^run_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3TaskRE         = regexp.MustCompile(`^tsk_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3ApprovalRE     = regexp.MustCompile(`^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3ReleaseRE      = regexp.MustCompile(`^rel_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3AttemptRE      = regexp.MustCompile(`^att_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3DigestRE       = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	m3IdempotencyRE  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$`)
	m3CodeRE         = regexp.MustCompile(`^[A-Z][A-Z0-9_]{2,63}$`)
	m3NodePathRE     = regexp.MustCompile(`^/[A-Za-z0-9][A-Za-z0-9_./-]{0,254}$`)
	m3KindRE         = regexp.MustCompile(`^[a-z][a-z0-9_.-]{2,39}$`)
	m3OperationRE    = regexp.MustCompile(`^[a-z][a-z0-9_.-]{2,63}$`)
	m3ArtifactRE     = regexp.MustCompile(`^art_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3TokenRE        = regexp.MustCompile(`^[0-9a-f]{32}$`)
	m3ReconcileRE    = regexp.MustCompile(`^rec_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`)
	m3OperationRefRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$`)
)

func m3RandomID(prefix string) (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(b[:]), nil
}

func m3SafeText(value string, min, max int) bool {
	if len(value) < min || len(value) > max {
		return false
	}
	for _, r := range value {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return true
}

func m3ValidEvidenceRefs(refs []string) bool {
	if len(refs) > 32 {
		return false
	}
	for _, ref := range refs {
		if !m3DigestRE.MatchString(ref) && !m3ArtifactRE.MatchString(ref) {
			return false
		}
	}
	return true
}

func m3ValidateScope(tenantID, runID string) error {
	if !m3TenantRE.MatchString(tenantID) || !m3RunRE.MatchString(runID) {
		return ErrM3Invalid
	}
	return nil
}

func m3ValidateIdempotency(key, digest string) error {
	if !m3IdempotencyRE.MatchString(key) || !m3DigestRE.MatchString(digest) {
		return ErrM3Invalid
	}
	return nil
}

func m3Terminal(state M3RunState) bool {
	switch state {
	case M3RunRejected, M3RunSucceeded, M3RunFailed, M3RunCancelled,
		M3RunBudgetExhausted, M3RunDeadLettered:
		return true
	default:
		return false
	}
}

var m3Transitions = map[M3RunState]map[M3RunState]bool{
	M3RunCreated:          {M3RunRunning: true, M3RunCancelled: true},
	M3RunRunning:          {M3RunAwaitingInput: true, M3RunAwaitingApproval: true, M3RunSucceeded: true, M3RunFailed: true, M3RunCancelled: true, M3RunBudgetExhausted: true, M3RunDeadLettered: true},
	M3RunAwaitingInput:    {M3RunRunning: true, M3RunFailed: true, M3RunCancelled: true, M3RunBudgetExhausted: true},
	M3RunAwaitingApproval: {M3RunFailed: true, M3RunCancelled: true},
	M3RunApproved:         {M3RunRunning: true, M3RunSucceeded: true, M3RunFailed: true, M3RunCancelled: true, M3RunDeadLettered: true},
}

var m3EventTypes = map[string]bool{
	"run.created": true, "run.transitioned": true, "approval.recorded": true,
	"release.created": true, "launch.recorded": true, "reconciliation.recorded": true,
	"task.enqueued": true, "attempt.started": true, "attempt.completed": true,
	"lease.expired": true, "task.retry_scheduled": true, "task.dead_lettered": true,
	"effect.reserved": true, "effect.committed": true,
}

func m3TransitionAllowed(from, to M3RunState) bool {
	return m3Transitions[from][to]
}

func (r *M3PostgresRepository) beginIdempotent(
	ctx context.Context, tenantID, runID, nodePath, planDigest, operation, key, requestDigest string,
) (*sql.Tx, *M3CommandResult, error) {
	if err := m3ValidateScope(tenantID, runID); err != nil || !m3NodePathRE.MatchString(nodePath) ||
		!m3OperationRE.MatchString(operation) || (planDigest != "" && !m3DigestRE.MatchString(planDigest)) {
		return nil, nil, ErrM3Invalid
	}
	if err := m3ValidateIdempotency(key, requestDigest); err != nil {
		return nil, nil, err
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return nil, nil, err
	}
	fail := func(err error) (*sql.Tx, *M3CommandResult, error) {
		_ = tx.Rollback()
		return nil, nil, err
	}
	lockName := strings.Join([]string{tenantID, runID, nodePath, operation, key}, "\x1f")
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockName); err != nil {
		return fail(err)
	}
	var storedDigest, storedPlanDigest string
	var raw []byte
	err = tx.QueryRowContext(ctx, `
		SELECT request_digest, COALESCE(plan_digest, ''), response_json
		FROM mission_control_v2.idempotency_results
		WHERE tenant_id = $1 AND run_id = $2 AND node_path = $3
			AND operation = $4 AND idempotency_key = $5`,
		tenantID, runID, nodePath, operation, key).Scan(&storedDigest, &storedPlanDigest, &raw)
	if err == nil {
		if storedDigest != requestDigest || storedPlanDigest != planDigest {
			return fail(ErrM3IdempotencyReuse)
		}
		var result M3CommandResult
		if err := json.Unmarshal(raw, &result); err != nil {
			return fail(fmt.Errorf("decode idempotency result: %w", err))
		}
		if err := tx.Commit(); err != nil {
			return nil, nil, err
		}
		result.Replayed = true
		return nil, &result, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return fail(err)
	}
	return tx, nil, nil
}

func m3StoreIdempotency(ctx context.Context, tx *sql.Tx, nodePath, planDigest, operation, key, digest string, result M3CommandResult) error {
	raw, err := json.Marshal(result)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.idempotency_results
			(tenant_id, run_id, node_path, plan_digest, operation,
			 idempotency_key, request_digest, response_json)
		VALUES ($1, $2, $3, NULLIF($4, ''), $5, $6, $7, $8::jsonb)`,
		result.TenantID, result.RunID, nodePath, planDigest, operation, key, digest, string(raw))
	return err
}

func m3Rollback(tx *sql.Tx, err error) error {
	_ = tx.Rollback()
	return err
}

func (r *M3PostgresRepository) appendEvent(
	ctx context.Context, tx *sql.Tx, run M3Run, eventType, taskID, attemptID,
	approvalID, releaseID, code string, evidenceRefs []string,
) (int64, error) {
	if !m3EventTypes[eventType] || !m3ValidEvidenceRefs(evidenceRefs) ||
		(taskID != "" && !m3TaskRE.MatchString(taskID)) ||
		(attemptID != "" && !m3AttemptRE.MatchString(attemptID)) ||
		(approvalID != "" && !m3ApprovalRE.MatchString(approvalID)) ||
		(releaseID != "" && !m3ReleaseRE.MatchString(releaseID)) ||
		(code != "" && !m3CodeRE.MatchString(code)) {
		return 0, ErrM3Invalid
	}
	var sequence int64
	err := tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.runs
		SET next_event_sequence = next_event_sequence + 1
		WHERE tenant_id = $1 AND run_id = $2
		RETURNING next_event_sequence - 1`, run.TenantID, run.RunID).Scan(&sequence)
	if err != nil {
		return 0, err
	}
	eventID, err := r.newID("evt_")
	if err != nil {
		return 0, err
	}
	refsJSON, err := json.Marshal(evidenceRefs)
	if err != nil {
		return 0, err
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.events
			(tenant_id, run_id, sequence, event_id, event_type, run_revision,
			 run_state, task_id, attempt_id, approval_id, release_id, code, evidence_refs)
		VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8, ''),
			NULLIF($9, ''), NULLIF($10, ''), NULLIF($11, ''), NULLIF($12, ''),
			ARRAY(SELECT jsonb_array_elements_text($13::jsonb)))`,
		run.TenantID, run.RunID, sequence, eventID, eventType, run.Revision,
		string(run.State), taskID, attemptID, approvalID, releaseID, code, string(refsJSON))
	return sequence, err
}

func m3LockRun(ctx context.Context, tx *sql.Tx, tenantID, runID string) (M3Run, error) {
	var run M3Run
	err := tx.QueryRowContext(ctx, `
		SELECT tenant_id, run_id, lifecycle_state, revision,
			COALESCE(plan_digest, ''), COALESCE(approval_id, ''), COALESCE(release_id, ''),
			created_at, updated_at
		FROM mission_control_v2.runs
		WHERE tenant_id = $1 AND run_id = $2
		FOR UPDATE`, tenantID, runID).Scan(
		&run.TenantID, &run.RunID, &run.State, &run.Revision,
		&run.PlanDigest, &run.ApprovalID, &run.ReleaseID, &run.CreatedAt, &run.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return M3Run{}, ErrM3NotFound
	}
	return run, err
}

func (r *M3PostgresRepository) GetRun(ctx context.Context, tenantID, runID string) (M3Run, error) {
	if err := m3ValidateScope(tenantID, runID); err != nil {
		return M3Run{}, err
	}
	var run M3Run
	err := r.db.QueryRowContext(ctx, `
		SELECT tenant_id, run_id, lifecycle_state, revision,
			COALESCE(plan_digest, ''), COALESCE(approval_id, ''), COALESCE(release_id, ''),
			created_at, updated_at
		FROM mission_control_v2.runs
		WHERE tenant_id = $1 AND run_id = $2`, tenantID, runID).Scan(
		&run.TenantID, &run.RunID, &run.State, &run.Revision,
		&run.PlanDigest, &run.ApprovalID, &run.ReleaseID, &run.CreatedAt, &run.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return M3Run{}, ErrM3NotFound
	}
	return run, err
}

type M3CreateRunCommand struct {
	TenantID, RunID, IdempotencyKey, RequestDigest string
}

func (r *M3PostgresRepository) CreateRun(ctx context.Context, cmd M3CreateRunCommand) (M3CommandResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil {
		return M3CommandResult{}, err
	}
	const nodePath = "/control/run.create"
	tx, replay, err := r.beginIdempotent(ctx, cmd.TenantID, cmd.RunID, nodePath, "", "run.create", cmd.IdempotencyKey, cmd.RequestDigest)
	if err != nil {
		return M3CommandResult{}, err
	}
	if replay != nil {
		return *replay, nil
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.runs (tenant_id, run_id, lifecycle_state)
		VALUES ($1, $2, 'created') ON CONFLICT DO NOTHING`, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3Conflict
		}
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	seq, err := r.appendEvent(ctx, tx, run, "run.created", "", "", "", "", "", nil)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	result := M3CommandResult{TenantID: run.TenantID, RunID: run.RunID, Revision: run.Revision, State: run.State, EventSequence: seq}
	if err := m3StoreIdempotency(ctx, tx, nodePath, "", "run.create", cmd.IdempotencyKey, cmd.RequestDigest, result); err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return M3CommandResult{}, err
	}
	return result, nil
}

type M3TransitionCommand struct {
	TenantID, RunID, IdempotencyKey, RequestDigest string
	ExpectedRevision                               int64
	To                                             M3RunState
	PlanDigest                                     string
	Code                                           string
}

func (r *M3PostgresRepository) TransitionRun(ctx context.Context, cmd M3TransitionCommand) (M3CommandResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil || cmd.ExpectedRevision < 1 {
		return M3CommandResult{}, ErrM3Invalid
	}
	if cmd.Code != "" && !m3CodeRE.MatchString(cmd.Code) {
		return M3CommandResult{}, ErrM3Invalid
	}
	if cmd.To == M3RunAwaitingApproval {
		if !m3DigestRE.MatchString(cmd.PlanDigest) {
			return M3CommandResult{}, ErrM3Invalid
		}
	} else if cmd.PlanDigest != "" && !m3DigestRE.MatchString(cmd.PlanDigest) {
		return M3CommandResult{}, ErrM3Invalid
	}
	const nodePath = "/control/run.transition"
	tx, replay, err := r.beginIdempotent(ctx, cmd.TenantID, cmd.RunID, nodePath, cmd.PlanDigest, "run.transition", cmd.IdempotencyKey, cmd.RequestDigest)
	if err != nil {
		return M3CommandResult{}, err
	}
	if replay != nil {
		return *replay, nil
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if run.Revision != cmd.ExpectedRevision {
		return M3CommandResult{}, m3Rollback(tx, ErrM3RevisionConflict)
	}
	if m3Terminal(run.State) || !m3TransitionAllowed(run.State, cmd.To) {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	if cmd.To == M3RunAwaitingApproval && (run.ApprovalID != "" || run.ReleaseID != "") {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	if cmd.To == M3RunSucceeded && run.ReleaseID == "" {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	if run.PlanDigest != "" && run.PlanDigest != cmd.PlanDigest {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	if cmd.To == M3RunSucceeded {
		var verified bool
		if err := tx.QueryRowContext(ctx, `
			SELECT outcome = 'verified' FROM mission_control_v2.reconciliation_results
			WHERE tenant_id = $1 AND run_id = $2 AND release_id = $3`,
			cmd.TenantID, cmd.RunID, run.ReleaseID).Scan(&verified); err != nil || !verified {
			if err == nil || errors.Is(err, sql.ErrNoRows) {
				err = ErrM3Conflict
			}
			return M3CommandResult{}, m3Rollback(tx, err)
		}
	}
	var plan any
	if cmd.PlanDigest == "" {
		plan = nil
	} else {
		plan = cmd.PlanDigest
	}
	err = tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.runs
		SET lifecycle_state = $3, revision = revision + 1,
			plan_digest = COALESCE($4, plan_digest), updated_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND revision = $5
		RETURNING revision, updated_at`,
		cmd.TenantID, cmd.RunID, string(cmd.To), plan, cmd.ExpectedRevision).Scan(&run.Revision, &run.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrM3RevisionConflict
	}
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	run.State = cmd.To
	if cmd.PlanDigest != "" {
		run.PlanDigest = cmd.PlanDigest
	}
	refs := []string(nil)
	if run.State == M3RunAwaitingApproval {
		refs = []string{run.PlanDigest}
	}
	seq, err := r.appendEvent(ctx, tx, run, "run.transitioned", "", "", "", run.ReleaseID, cmd.Code, refs)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	result := M3CommandResult{TenantID: run.TenantID, RunID: run.RunID, Revision: run.Revision, State: run.State, EventSequence: seq, ApprovalID: run.ApprovalID, ReleaseID: run.ReleaseID}
	if err := m3StoreIdempotency(ctx, tx, nodePath, cmd.PlanDigest, "run.transition", cmd.IdempotencyKey, cmd.RequestDigest, result); err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return M3CommandResult{}, err
	}
	return result, nil
}

type M3ApprovalCommand struct {
	TenantID, RunID, ApprovalID, SubjectDigest, NonceDigest, Decision, ActorSubject string
	IdempotencyKey, RequestDigest                                                   string
	ExpectedRevision                                                                int64
}

func (r *M3PostgresRepository) RecordApproval(ctx context.Context, cmd M3ApprovalCommand) (M3CommandResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3ApprovalRE.MatchString(cmd.ApprovalID) || !m3DigestRE.MatchString(cmd.SubjectDigest) || !m3DigestRE.MatchString(cmd.NonceDigest) ||
		(cmd.Decision != "approved" && cmd.Decision != "rejected") ||
		!m3SafeText(cmd.ActorSubject, 3, 160) || cmd.ExpectedRevision < 1 {
		return M3CommandResult{}, ErrM3Invalid
	}
	const nodePath = "/control/approval.record"
	tx, replay, err := r.beginIdempotent(ctx, cmd.TenantID, cmd.RunID, nodePath, cmd.SubjectDigest, "approval.record", cmd.IdempotencyKey, cmd.RequestDigest)
	if err != nil {
		return M3CommandResult{}, err
	}
	if replay != nil {
		return *replay, nil
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if run.Revision != cmd.ExpectedRevision {
		return M3CommandResult{}, m3Rollback(tx, ErrM3RevisionConflict)
	}
	if run.State != M3RunAwaitingApproval || run.PlanDigest != cmd.SubjectDigest || run.ApprovalID != "" {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	res, err := tx.ExecContext(ctx, `
		UPDATE mission_control_v2.approval_nonces
		SET consumed_at = clock_timestamp(), approval_id = $4
		WHERE tenant_id = $1 AND run_id = $2 AND nonce_digest = $3
			AND subject_digest = $5 AND consumed_at IS NULL
			AND expires_at > clock_timestamp()`,
		cmd.TenantID, cmd.RunID, cmd.NonceDigest, cmd.ApprovalID, cmd.SubjectDigest)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3Conflict
		}
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.approvals
			(tenant_id, approval_id, run_id, subject_digest, nonce_digest, decision, actor_subject)
		VALUES ($1, $2, $3, $4, $5, $6, $7)`,
		cmd.TenantID, cmd.ApprovalID, cmd.RunID, cmd.SubjectDigest, cmd.NonceDigest, cmd.Decision, cmd.ActorSubject); err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	run.State = M3RunState(cmd.Decision)
	err = tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.runs
		SET lifecycle_state = $3, approval_id = $4, revision = revision + 1,
			updated_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND revision = $5
		RETURNING revision, updated_at`,
		cmd.TenantID, cmd.RunID, cmd.Decision, cmd.ApprovalID, cmd.ExpectedRevision).Scan(&run.Revision, &run.UpdatedAt)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	run.ApprovalID = cmd.ApprovalID
	seq, err := r.appendEvent(ctx, tx, run, "approval.recorded", "", "", cmd.ApprovalID, "", "", []string{cmd.SubjectDigest})
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	result := M3CommandResult{TenantID: run.TenantID, RunID: run.RunID, Revision: run.Revision, State: run.State, EventSequence: seq, ApprovalID: run.ApprovalID}
	if err := m3StoreIdempotency(ctx, tx, nodePath, cmd.SubjectDigest, "approval.record", cmd.IdempotencyKey, cmd.RequestDigest, result); err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return M3CommandResult{}, err
	}
	return result, nil
}

type M3ApprovalNonceCommand struct {
	TenantID, RunID, SubjectDigest, NonceDigest string
	ExpiresAt                                   time.Time
}

// RegisterApprovalNonce records a one-time, digest-bound authorization
// challenge. Authentication/identity policy belongs to the approval surface;
// this repository guarantees consumption is atomic with the decision.
func (r *M3PostgresRepository) RegisterApprovalNonce(ctx context.Context, cmd M3ApprovalNonceCommand) error {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3DigestRE.MatchString(cmd.SubjectDigest) || !m3DigestRE.MatchString(cmd.NonceDigest) || cmd.ExpiresAt.IsZero() {
		return ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return err
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if run.State != M3RunAwaitingApproval || run.PlanDigest != cmd.SubjectDigest {
		return m3Rollback(tx, ErrM3Conflict)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.approval_nonces
			(tenant_id, run_id, nonce_digest, subject_digest, expires_at)
		SELECT $1, $2, $3, $4, $5
		WHERE $5 > clock_timestamp()
		ON CONFLICT DO NOTHING`, cmd.TenantID, cmd.RunID, cmd.NonceDigest, cmd.SubjectDigest, cmd.ExpiresAt.UTC())
	if err != nil {
		return m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3Conflict
		}
		return m3Rollback(tx, err)
	}
	return tx.Commit()
}

type M3ReleaseCommand struct {
	TenantID, RunID, ReleaseID, ApprovalID, SubjectDigest, ReleaseKind, ArtifactDigest string
	SignerKeyVersion, SignatureDigest                                                  string
	IdempotencyKey, RequestDigest                                                      string
	ExpectedRevision                                                                   int64
}

func (r *M3PostgresRepository) CreateRelease(ctx context.Context, cmd M3ReleaseCommand) (M3CommandResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3ReleaseRE.MatchString(cmd.ReleaseID) || !m3ApprovalRE.MatchString(cmd.ApprovalID) ||
		!m3DigestRE.MatchString(cmd.SubjectDigest) || !m3DigestRE.MatchString(cmd.ArtifactDigest) ||
		!m3KindRE.MatchString(cmd.ReleaseKind) || !m3SafeText(cmd.SignerKeyVersion, 8, 160) ||
		!m3DigestRE.MatchString(cmd.SignatureDigest) || cmd.ExpectedRevision < 1 {
		return M3CommandResult{}, ErrM3Invalid
	}
	const nodePath = "/control/release.create"
	tx, replay, err := r.beginIdempotent(ctx, cmd.TenantID, cmd.RunID, nodePath, cmd.SubjectDigest, "release.create", cmd.IdempotencyKey, cmd.RequestDigest)
	if err != nil {
		return M3CommandResult{}, err
	}
	if replay != nil {
		return *replay, nil
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if run.Revision != cmd.ExpectedRevision {
		return M3CommandResult{}, m3Rollback(tx, ErrM3RevisionConflict)
	}
	if run.State != M3RunApproved || run.ApprovalID != cmd.ApprovalID || run.PlanDigest != cmd.SubjectDigest || run.ReleaseID != "" {
		return M3CommandResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	var approved bool
	if err := tx.QueryRowContext(ctx, `
		SELECT decision = 'approved' AND subject_digest = $4
		FROM mission_control_v2.approvals
		WHERE tenant_id = $1 AND run_id = $2 AND approval_id = $3`,
		cmd.TenantID, cmd.RunID, cmd.ApprovalID, cmd.SubjectDigest).Scan(&approved); err != nil || !approved {
		if err == nil {
			err = ErrM3Conflict
		}
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.releases
			(tenant_id, release_id, run_id, approval_id, subject_digest, release_kind,
			 artifact_digest, signer_key_version, signature_digest)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO NOTHING`,
		cmd.TenantID, cmd.ReleaseID, cmd.RunID, cmd.ApprovalID, cmd.SubjectDigest,
		cmd.ReleaseKind, cmd.ArtifactDigest, cmd.SignerKeyVersion, cmd.SignatureDigest)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3Conflict
		}
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	err = tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.runs
		SET release_id = $3, revision = revision + 1, updated_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND revision = $4
		RETURNING revision, updated_at`, cmd.TenantID, cmd.RunID, cmd.ReleaseID, cmd.ExpectedRevision).Scan(&run.Revision, &run.UpdatedAt)
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	run.ReleaseID = cmd.ReleaseID
	seq, err := r.appendEvent(ctx, tx, run, "release.created", "", "", cmd.ApprovalID, cmd.ReleaseID, "", []string{cmd.SubjectDigest, cmd.ArtifactDigest, cmd.SignatureDigest})
	if err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	result := M3CommandResult{TenantID: run.TenantID, RunID: run.RunID, Revision: run.Revision, State: run.State, EventSequence: seq, ApprovalID: run.ApprovalID, ReleaseID: run.ReleaseID}
	if err := m3StoreIdempotency(ctx, tx, nodePath, cmd.SubjectDigest, "release.create", cmd.IdempotencyKey, cmd.RequestDigest, result); err != nil {
		return M3CommandResult{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return M3CommandResult{}, err
	}
	return result, nil
}

type M3LaunchResultCommand struct {
	TenantID, RunID, LaunchKey, ReleaseID, RequestDigest string
	Status, OperationRef, ResultDigest                   string
}

type M3LaunchResult struct {
	TenantID, RunID, LaunchKey, ReleaseID string
	Status, OperationRef, ResultDigest    string
	EventSequence                         int64
	Replayed                              bool
}

// RecordLaunchResult durably records the create-once result of dispatching a
// signed release. LaunchKey is also the downstream idempotency key; a retry
// with the same facts returns the original row and appends no second event.
func (r *M3PostgresRepository) RecordLaunchResult(ctx context.Context, cmd M3LaunchResultCommand) (M3LaunchResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3SafeText(cmd.LaunchKey, 8, 160) || !m3ReleaseRE.MatchString(cmd.ReleaseID) ||
		!m3DigestRE.MatchString(cmd.RequestDigest) ||
		(cmd.Status != "launched" && cmd.Status != "failed") ||
		!m3OperationRefRE.MatchString(cmd.OperationRef) || !m3DigestRE.MatchString(cmd.ResultDigest) {
		return M3LaunchResult{}, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return M3LaunchResult{}, err
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3LaunchResult{}, m3Rollback(tx, err)
	}
	if run.ReleaseID != cmd.ReleaseID || (run.State != M3RunApproved && run.State != M3RunRunning) {
		return M3LaunchResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.launch_results
			(tenant_id, run_id, launch_key, release_id, request_digest,
			 status, operation_ref, result_digest)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT DO NOTHING`, cmd.TenantID, cmd.RunID, cmd.LaunchKey,
		cmd.ReleaseID, cmd.RequestDigest, cmd.Status, cmd.OperationRef, cmd.ResultDigest)
	if err != nil {
		return M3LaunchResult{}, m3Rollback(tx, err)
	}
	inserted, err := res.RowsAffected()
	if err != nil {
		return M3LaunchResult{}, m3Rollback(tx, err)
	}
	result := M3LaunchResult{
		TenantID: cmd.TenantID, RunID: cmd.RunID, LaunchKey: cmd.LaunchKey,
		ReleaseID: cmd.ReleaseID, Status: cmd.Status, OperationRef: cmd.OperationRef,
		ResultDigest: cmd.ResultDigest,
	}
	if inserted == 0 {
		var stored M3LaunchResult
		var storedRequestDigest string
		err := tx.QueryRowContext(ctx, `
			SELECT tenant_id, run_id, launch_key, release_id, status, operation_ref,
				result_digest, request_digest
			FROM mission_control_v2.launch_results
			WHERE tenant_id = $1 AND run_id = $2 AND (launch_key = $3 OR release_id = $4)
			FOR UPDATE`, cmd.TenantID, cmd.RunID, cmd.LaunchKey, cmd.ReleaseID).Scan(
			&stored.TenantID, &stored.RunID, &stored.LaunchKey, &stored.ReleaseID,
			&stored.Status, &stored.OperationRef, &stored.ResultDigest, &storedRequestDigest)
		if err != nil {
			return M3LaunchResult{}, m3Rollback(tx, err)
		}
		if stored.LaunchKey != cmd.LaunchKey || stored.ReleaseID != cmd.ReleaseID || stored.Status != cmd.Status ||
			stored.OperationRef != cmd.OperationRef || stored.ResultDigest != cmd.ResultDigest {
			return M3LaunchResult{}, m3Rollback(tx, ErrM3IdempotencyReuse)
		}
		if storedRequestDigest != cmd.RequestDigest {
			return M3LaunchResult{}, m3Rollback(tx, ErrM3IdempotencyReuse)
		}
		stored.Replayed = true
		if err := tx.Commit(); err != nil {
			return M3LaunchResult{}, err
		}
		return stored, nil
	}
	seq, err := r.appendEvent(ctx, tx, run, "launch.recorded", "", "", run.ApprovalID, cmd.ReleaseID, "", []string{cmd.RequestDigest, cmd.ResultDigest})
	if err != nil {
		return M3LaunchResult{}, m3Rollback(tx, err)
	}
	result.EventSequence = seq
	if err := tx.Commit(); err != nil {
		return M3LaunchResult{}, err
	}
	return result, nil
}

type M3ReconciliationCommand struct {
	TenantID, RunID, ReconciliationID, ReleaseID, LaunchKey string
	Outcome, ResultDigest, EvidenceDigest                   string
}

type M3ReconciliationResult struct {
	TenantID, RunID, ReconciliationID, ReleaseID, LaunchKey string
	Outcome, ResultDigest, EvidenceDigest                   string
	EventSequence                                           int64
	Replayed                                                bool
}

// RecordReconciliation persists the deterministic verification fact before a
// run can transition to succeeded. The unique run/release key prevents a
// second or contradictory verification record.
func (r *M3PostgresRepository) RecordReconciliation(ctx context.Context, cmd M3ReconciliationCommand) (M3ReconciliationResult, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3ReconcileRE.MatchString(cmd.ReconciliationID) || !m3ReleaseRE.MatchString(cmd.ReleaseID) ||
		!m3SafeText(cmd.LaunchKey, 8, 160) || (cmd.Outcome != "verified" && cmd.Outcome != "failed") ||
		!m3DigestRE.MatchString(cmd.ResultDigest) || !m3DigestRE.MatchString(cmd.EvidenceDigest) {
		return M3ReconciliationResult{}, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return M3ReconciliationResult{}, err
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3ReconciliationResult{}, m3Rollback(tx, err)
	}
	if run.ReleaseID != cmd.ReleaseID {
		return M3ReconciliationResult{}, m3Rollback(tx, ErrM3Conflict)
	}
	var launchStatus, launchRelease string
	err = tx.QueryRowContext(ctx, `
		SELECT status, release_id FROM mission_control_v2.launch_results
		WHERE tenant_id = $1 AND run_id = $2 AND launch_key = $3
		FOR UPDATE`, cmd.TenantID, cmd.RunID, cmd.LaunchKey).Scan(&launchStatus, &launchRelease)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrM3Conflict
	}
	if err != nil || launchStatus != "launched" || launchRelease != cmd.ReleaseID {
		if err == nil {
			err = ErrM3Conflict
		}
		return M3ReconciliationResult{}, m3Rollback(tx, err)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.reconciliation_results
			(tenant_id, run_id, reconciliation_id, release_id, launch_key,
			 outcome, result_digest, evidence_digest)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT DO NOTHING`, cmd.TenantID, cmd.RunID, cmd.ReconciliationID,
		cmd.ReleaseID, cmd.LaunchKey, cmd.Outcome, cmd.ResultDigest, cmd.EvidenceDigest)
	if err != nil {
		return M3ReconciliationResult{}, m3Rollback(tx, err)
	}
	inserted, err := res.RowsAffected()
	if err != nil {
		return M3ReconciliationResult{}, m3Rollback(tx, err)
	}
	result := M3ReconciliationResult{
		TenantID: cmd.TenantID, RunID: cmd.RunID, ReconciliationID: cmd.ReconciliationID,
		ReleaseID: cmd.ReleaseID, LaunchKey: cmd.LaunchKey, Outcome: cmd.Outcome,
		ResultDigest: cmd.ResultDigest, EvidenceDigest: cmd.EvidenceDigest,
	}
	if inserted == 0 {
		var stored M3ReconciliationResult
		err := tx.QueryRowContext(ctx, `
			SELECT tenant_id, run_id, reconciliation_id, release_id, launch_key,
				outcome, result_digest, evidence_digest
			FROM mission_control_v2.reconciliation_results
			WHERE tenant_id = $1 AND
				(reconciliation_id = $3 OR (run_id = $2 AND release_id = $4))
			FOR UPDATE`, cmd.TenantID, cmd.RunID, cmd.ReconciliationID, cmd.ReleaseID).Scan(
			&stored.TenantID, &stored.RunID, &stored.ReconciliationID, &stored.ReleaseID,
			&stored.LaunchKey, &stored.Outcome, &stored.ResultDigest, &stored.EvidenceDigest)
		if err != nil {
			return M3ReconciliationResult{}, m3Rollback(tx, err)
		}
		if stored.ReconciliationID != cmd.ReconciliationID || stored.LaunchKey != cmd.LaunchKey ||
			stored.RunID != cmd.RunID || stored.ReleaseID != cmd.ReleaseID ||
			stored.Outcome != cmd.Outcome || stored.ResultDigest != cmd.ResultDigest ||
			stored.EvidenceDigest != cmd.EvidenceDigest {
			return M3ReconciliationResult{}, m3Rollback(tx, ErrM3IdempotencyReuse)
		}
		stored.Replayed = true
		if err := tx.Commit(); err != nil {
			return M3ReconciliationResult{}, err
		}
		return stored, nil
	}
	seq, err := r.appendEvent(ctx, tx, run, "reconciliation.recorded", "", "", run.ApprovalID, cmd.ReleaseID, "", []string{cmd.ResultDigest, cmd.EvidenceDigest})
	if err != nil {
		return M3ReconciliationResult{}, m3Rollback(tx, err)
	}
	result.EventSequence = seq
	if err := tx.Commit(); err != nil {
		return M3ReconciliationResult{}, err
	}
	return result, nil
}

type M3EnqueueTaskCommand struct {
	TenantID, RunID, TaskID, NodePath, InputDigest, EffectKey string
	MaxAttempts                                               int
}

func (r *M3PostgresRepository) EnqueueTask(ctx context.Context, cmd M3EnqueueTaskCommand) error {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil ||
		!m3TaskRE.MatchString(cmd.TaskID) || !m3NodePathRE.MatchString(cmd.NodePath) ||
		!m3DigestRE.MatchString(cmd.InputDigest) || cmd.MaxAttempts < 1 || cmd.MaxAttempts > 32 ||
		(cmd.EffectKey != "" && !m3SafeText(cmd.EffectKey, 8, 160)) {
		return ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return err
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if m3Terminal(run.State) {
		return m3Rollback(tx, ErrM3Conflict)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.tasks
			(tenant_id, run_id, task_id, node_path, input_digest, max_attempts, effect_key)
		VALUES ($1, $2, $3, $4, $5, $6, NULLIF($7, '')) ON CONFLICT DO NOTHING`,
		cmd.TenantID, cmd.RunID, cmd.TaskID, cmd.NodePath, cmd.InputDigest, cmd.MaxAttempts, cmd.EffectKey)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3Conflict
		}
		return m3Rollback(tx, err)
	}
	if _, err := r.appendEvent(ctx, tx, run, "task.enqueued", cmd.TaskID, "", "", "", "", []string{cmd.InputDigest}); err != nil {
		return m3Rollback(tx, err)
	}
	return tx.Commit()
}

type m3TaskRow struct {
	TaskID, Status, LeaseOwner, LeaseToken, ActiveAttemptID string
	AttemptsStarted, MaxAttempts                            int
	LeaseGeneration                                         int64
	LeaseExpired                                            bool
	Available                                               bool
}

func m3LockTask(ctx context.Context, tx *sql.Tx, tenantID, runID, taskID string) (m3TaskRow, error) {
	var task m3TaskRow
	err := tx.QueryRowContext(ctx, `
		SELECT task_id, status, attempts_started, max_attempts,
			COALESCE(lease_owner, ''), COALESCE(lease_token, ''), lease_generation,
			COALESCE(active_attempt_id, ''),
			COALESCE(lease_expires_at <= clock_timestamp(), false),
			available_at <= clock_timestamp()
		FROM mission_control_v2.tasks
		WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3
		FOR UPDATE`, tenantID, runID, taskID).Scan(
		&task.TaskID, &task.Status, &task.AttemptsStarted, &task.MaxAttempts,
		&task.LeaseOwner, &task.LeaseToken, &task.LeaseGeneration,
		&task.ActiveAttemptID, &task.LeaseExpired, &task.Available,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return m3TaskRow{}, ErrM3NotFound
	}
	return task, err
}

type M3ClaimTaskCommand struct {
	TenantID, RunID, TaskID, WorkerID string
	LeaseDuration                     time.Duration
}

func (r *M3PostgresRepository) ClaimTask(ctx context.Context, cmd M3ClaimTaskCommand) (M3Lease, error) {
	if err := m3ValidateScope(cmd.TenantID, cmd.RunID); err != nil || !m3TaskRE.MatchString(cmd.TaskID) ||
		!m3SafeText(cmd.WorkerID, 3, 128) || cmd.LeaseDuration < time.Second || cmd.LeaseDuration > time.Hour {
		return M3Lease{}, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return M3Lease{}, err
	}
	run, err := m3LockRun(ctx, tx, cmd.TenantID, cmd.RunID)
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	if m3Terminal(run.State) {
		return M3Lease{}, m3Rollback(tx, ErrM3Conflict)
	}
	task, err := m3LockTask(ctx, tx, cmd.TenantID, cmd.RunID, cmd.TaskID)
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	recovered := false
	if task.Status == "running" {
		if !task.LeaseExpired {
			return M3Lease{}, m3Rollback(tx, ErrM3LeaseUnavailable)
		}
		res, err := tx.ExecContext(ctx, `
			UPDATE mission_control_v2.attempts
			SET status = 'timed_out', completed_at = clock_timestamp(), failure_code = 'LEASE_EXPIRED'
			WHERE tenant_id = $1 AND run_id = $2 AND attempt_id = $3
				AND status = 'running' AND lease_generation = $4`,
			cmd.TenantID, cmd.RunID, task.ActiveAttemptID, task.LeaseGeneration)
		if err != nil {
			return M3Lease{}, m3Rollback(tx, err)
		}
		if n, err := res.RowsAffected(); err != nil || n != 1 {
			if err == nil {
				err = ErrM3StaleLease
			}
			return M3Lease{}, m3Rollback(tx, err)
		}
		if _, err := r.appendEvent(ctx, tx, run, "lease.expired", task.TaskID, task.ActiveAttemptID, "", "", "LEASE_EXPIRED", nil); err != nil {
			return M3Lease{}, m3Rollback(tx, err)
		}
		recovered = true
	} else if task.Status != "ready" && task.Status != "failed" {
		if task.Status == "dead_lettered" {
			return M3Lease{}, m3Rollback(tx, ErrM3DeadLettered)
		}
		return M3Lease{}, m3Rollback(tx, ErrM3LeaseUnavailable)
	}
	if task.Status == "failed" && !task.Available {
		return M3Lease{}, m3Rollback(tx, ErrM3LeaseUnavailable)
	}
	if task.AttemptsStarted >= task.MaxAttempts {
		_, err := tx.ExecContext(ctx, `
			UPDATE mission_control_v2.tasks SET status = 'dead_lettered', revision = revision + 1,
				lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
				active_attempt_id = NULL, updated_at = clock_timestamp()
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3`, cmd.TenantID, cmd.RunID, cmd.TaskID)
		if err != nil {
			return M3Lease{}, m3Rollback(tx, err)
		}
		if _, err := r.appendEvent(ctx, tx, run, "task.dead_lettered", task.TaskID, task.ActiveAttemptID, "", "", "ATTEMPTS_EXHAUSTED", nil); err != nil {
			return M3Lease{}, m3Rollback(tx, err)
		}
		if err := tx.Commit(); err != nil {
			return M3Lease{}, err
		}
		return M3Lease{}, ErrM3DeadLettered
	}
	attemptID, err := r.newID("att_")
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	token, err := r.newID("")
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	lease := M3Lease{
		TenantID: cmd.TenantID, RunID: cmd.RunID, TaskID: cmd.TaskID,
		AttemptID: attemptID, AttemptNumber: task.AttemptsStarted + 1,
		Owner: cmd.WorkerID, Token: token, Generation: task.LeaseGeneration + 1,
		RecoveredLease: recovered,
	}
	seconds := int64(cmd.LeaseDuration / time.Second)
	err = tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.tasks
		SET status = 'running', revision = revision + 1,
			attempts_started = attempts_started + 1,
			retry_count = retry_count + CASE WHEN $8 THEN 1 ELSE 0 END,
			lease_owner = $4, lease_token = $5, lease_generation = lease_generation + 1,
			lease_expires_at = clock_timestamp() + ($6 * interval '1 second'),
			active_attempt_id = $7, updated_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3
			AND attempts_started < max_attempts
			AND (status = 'ready' OR (status = 'failed' AND available_at <= clock_timestamp())
				OR (status = 'running' AND lease_expires_at <= clock_timestamp()))
		RETURNING lease_generation, lease_expires_at`,
		cmd.TenantID, cmd.RunID, cmd.TaskID, cmd.WorkerID, token, seconds, attemptID, recovered).Scan(&lease.Generation, &lease.ExpiresAt)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrM3LeaseUnavailable
	}
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.attempts
			(tenant_id, run_id, task_id, attempt_id, attempt_number, lease_generation, worker_id, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7, 'running')`,
		cmd.TenantID, cmd.RunID, cmd.TaskID, attemptID, lease.AttemptNumber, lease.Generation, cmd.WorkerID)
	if err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	if _, err := r.appendEvent(ctx, tx, run, "attempt.started", cmd.TaskID, attemptID, "", "", "", nil); err != nil {
		return M3Lease{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return M3Lease{}, err
	}
	return lease, nil
}

func (r *M3PostgresRepository) HeartbeatLease(ctx context.Context, lease M3Lease, extension time.Duration) (time.Time, error) {
	if err := m3ValidateScope(lease.TenantID, lease.RunID); err != nil || !m3TaskRE.MatchString(lease.TaskID) ||
		!m3AttemptRE.MatchString(lease.AttemptID) || !m3SafeText(lease.Owner, 3, 128) ||
		!m3TokenRE.MatchString(lease.Token) || lease.Generation < 1 ||
		extension < time.Second || extension > time.Hour {
		return time.Time{}, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return time.Time{}, err
	}
	var expires time.Time
	err = tx.QueryRowContext(ctx, `
		UPDATE mission_control_v2.tasks
		SET lease_expires_at = clock_timestamp() + ($8 * interval '1 second'),
			updated_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3
			AND active_attempt_id = $4 AND lease_owner = $5 AND lease_token = $6
			AND lease_generation = $7 AND status = 'running'
			AND lease_expires_at > clock_timestamp()
		RETURNING lease_expires_at`, lease.TenantID, lease.RunID, lease.TaskID,
		lease.AttemptID, lease.Owner, lease.Token, lease.Generation, int64(extension/time.Second)).Scan(&expires)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrM3StaleLease
	}
	if err != nil {
		return time.Time{}, m3Rollback(tx, err)
	}
	res, err := tx.ExecContext(ctx, `
		UPDATE mission_control_v2.attempts
		SET last_heartbeat_at = clock_timestamp()
		WHERE tenant_id = $1 AND run_id = $2 AND attempt_id = $3
			AND lease_generation = $4 AND worker_id = $5 AND status = 'running'`,
		lease.TenantID, lease.RunID, lease.AttemptID, lease.Generation, lease.Owner)
	if err != nil {
		return time.Time{}, m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3StaleLease
		}
		return time.Time{}, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return time.Time{}, err
	}
	return expires, nil
}

type M3CompleteTaskCommand struct {
	Lease        M3Lease
	Succeeded    bool
	OutputDigest string
	FailureCode  string
	RetryDelay   time.Duration
}

func (r *M3PostgresRepository) CompleteTask(ctx context.Context, cmd M3CompleteTaskCommand) error {
	lease := cmd.Lease
	if err := m3ValidateScope(lease.TenantID, lease.RunID); err != nil ||
		!m3TaskRE.MatchString(lease.TaskID) || !m3AttemptRE.MatchString(lease.AttemptID) ||
		!m3SafeText(lease.Owner, 3, 128) || !m3TokenRE.MatchString(lease.Token) ||
		lease.Generation < 1 || cmd.RetryDelay < 0 || cmd.RetryDelay > 24*time.Hour {
		return ErrM3Invalid
	}
	if cmd.Succeeded {
		if !m3DigestRE.MatchString(cmd.OutputDigest) || cmd.FailureCode != "" {
			return ErrM3Invalid
		}
	} else if !m3CodeRE.MatchString(cmd.FailureCode) || cmd.OutputDigest != "" {
		return ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return err
	}
	run, err := m3LockRun(ctx, tx, lease.TenantID, lease.RunID)
	if err != nil {
		return m3Rollback(tx, err)
	}
	task, err := m3LockTask(ctx, tx, lease.TenantID, lease.RunID, lease.TaskID)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if task.Status != "running" || task.LeaseExpired || task.ActiveAttemptID != lease.AttemptID ||
		task.LeaseOwner != lease.Owner || task.LeaseToken != lease.Token || task.LeaseGeneration != lease.Generation {
		return m3Rollback(tx, ErrM3StaleLease)
	}
	attemptStatus := "failed"
	var output any
	var failure any = cmd.FailureCode
	if cmd.Succeeded {
		attemptStatus = "succeeded"
		output = cmd.OutputDigest
		failure = nil
	}
	res, err := tx.ExecContext(ctx, `
		UPDATE mission_control_v2.attempts
		SET status = $6, completed_at = clock_timestamp(), output_digest = $7, failure_code = $8
		WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3 AND attempt_id = $4
			AND lease_generation = $5 AND status = 'running'`,
		lease.TenantID, lease.RunID, lease.TaskID, lease.AttemptID, lease.Generation,
		attemptStatus, output, failure)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err == nil {
			err = ErrM3StaleLease
		}
		return m3Rollback(tx, err)
	}
	if cmd.Succeeded {
		_, err = tx.ExecContext(ctx, `
			UPDATE mission_control_v2.tasks SET status = 'succeeded', revision = revision + 1,
				lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
				active_attempt_id = NULL, updated_at = clock_timestamp()
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3`, lease.TenantID, lease.RunID, lease.TaskID)
		if err == nil {
			_, err = r.appendEvent(ctx, tx, run, "attempt.completed", lease.TaskID, lease.AttemptID, "", "", "", []string{cmd.OutputDigest})
		}
	} else if task.AttemptsStarted < task.MaxAttempts {
		_, err = tx.ExecContext(ctx, `
			UPDATE mission_control_v2.tasks SET status = 'failed', revision = revision + 1,
				retry_count = retry_count + 1,
				available_at = clock_timestamp() + ($4 * interval '1 second'),
				lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
				active_attempt_id = NULL, updated_at = clock_timestamp()
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3`,
			lease.TenantID, lease.RunID, lease.TaskID, int64(cmd.RetryDelay/time.Second))
		if err == nil {
			_, err = r.appendEvent(ctx, tx, run, "attempt.completed", lease.TaskID, lease.AttemptID, "", "", cmd.FailureCode, nil)
		}
		if err == nil {
			_, err = r.appendEvent(ctx, tx, run, "task.retry_scheduled", lease.TaskID, lease.AttemptID, "", "", cmd.FailureCode, nil)
		}
	} else {
		_, err = tx.ExecContext(ctx, `
			UPDATE mission_control_v2.tasks SET status = 'dead_lettered', revision = revision + 1,
				lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
				active_attempt_id = NULL, updated_at = clock_timestamp()
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3`, lease.TenantID, lease.RunID, lease.TaskID)
		if err == nil {
			_, err = r.appendEvent(ctx, tx, run, "attempt.completed", lease.TaskID, lease.AttemptID, "", "", cmd.FailureCode, nil)
		}
		if err == nil {
			_, err = r.appendEvent(ctx, tx, run, "task.dead_lettered", lease.TaskID, lease.AttemptID, "", "", "ATTEMPTS_EXHAUSTED", nil)
		}
	}
	if err != nil {
		return m3Rollback(tx, err)
	}
	return tx.Commit()
}

// RecoverExpiredLeases is the deterministic recovery evaluator. It uses the
// database clock and row locks, so only one evaluator can terminate a lease.
func (r *M3PostgresRepository) RecoverExpiredLeases(ctx context.Context, tenantID, runID string, limit int, retryDelay time.Duration) (int, error) {
	if err := m3ValidateScope(tenantID, runID); err != nil || limit < 1 || limit > 500 || retryDelay < 0 || retryDelay > 24*time.Hour {
		return 0, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return 0, err
	}
	run, err := m3LockRun(ctx, tx, tenantID, runID)
	if err != nil {
		return 0, m3Rollback(tx, err)
	}
	rows, err := tx.QueryContext(ctx, `
		SELECT task_id, active_attempt_id, lease_generation, attempts_started, max_attempts
		FROM mission_control_v2.tasks
		WHERE tenant_id = $1 AND run_id = $2 AND status = 'running'
			AND lease_expires_at <= clock_timestamp()
		ORDER BY lease_expires_at, task_id
		FOR UPDATE SKIP LOCKED LIMIT $3`, tenantID, runID, limit)
	if err != nil {
		return 0, m3Rollback(tx, err)
	}
	type expired struct {
		taskID, attemptID     string
		generation            int64
		attempts, maxAttempts int
	}
	var found []expired
	for rows.Next() {
		var item expired
		if err := rows.Scan(&item.taskID, &item.attemptID, &item.generation, &item.attempts, &item.maxAttempts); err != nil {
			_ = rows.Close()
			return 0, m3Rollback(tx, err)
		}
		found = append(found, item)
	}
	if err := rows.Close(); err != nil {
		return 0, m3Rollback(tx, err)
	}
	for _, item := range found {
		res, err := tx.ExecContext(ctx, `
			UPDATE mission_control_v2.attempts
			SET status = 'timed_out', completed_at = clock_timestamp(), failure_code = 'LEASE_EXPIRED'
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3 AND attempt_id = $4
				AND lease_generation = $5 AND status = 'running'`,
			tenantID, runID, item.taskID, item.attemptID, item.generation)
		if err != nil {
			return 0, m3Rollback(tx, err)
		}
		if n, err := res.RowsAffected(); err != nil || n != 1 {
			if err == nil {
				err = ErrM3StaleLease
			}
			return 0, m3Rollback(tx, err)
		}
		dead := item.attempts >= item.maxAttempts
		status := "failed"
		if dead {
			status = "dead_lettered"
		}
		_, err = tx.ExecContext(ctx, `
			UPDATE mission_control_v2.tasks
			SET status = $4, revision = revision + 1, retry_count = retry_count + 1,
				available_at = clock_timestamp() + ($5 * interval '1 second'),
				lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
				active_attempt_id = NULL, updated_at = clock_timestamp()
			WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3
				AND lease_generation = $6 AND status = 'running'`,
			tenantID, runID, item.taskID, status, int64(retryDelay/time.Second), item.generation)
		if err != nil {
			return 0, m3Rollback(tx, err)
		}
		if _, err := r.appendEvent(ctx, tx, run, "lease.expired", item.taskID, item.attemptID, "", "", "LEASE_EXPIRED", nil); err != nil {
			return 0, m3Rollback(tx, err)
		}
		eventType := "task.retry_scheduled"
		code := "LEASE_EXPIRED"
		if dead {
			eventType = "task.dead_lettered"
			code = "ATTEMPTS_EXHAUSTED"
		}
		if _, err := r.appendEvent(ctx, tx, run, eventType, item.taskID, item.attemptID, "", "", code, nil); err != nil {
			return 0, m3Rollback(tx, err)
		}
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return len(found), nil
}

type M3EffectCommand struct {
	Lease         M3Lease
	EffectKey     string
	RequestDigest string
}

// ReserveEffect creates the local create-once side-effect ledger entry. The
// caller must also pass EffectKey to the downstream idempotency mechanism.
func (r *M3PostgresRepository) ReserveEffect(ctx context.Context, cmd M3EffectCommand) (bool, error) {
	if err := m3ValidateScope(cmd.Lease.TenantID, cmd.Lease.RunID); err != nil ||
		!m3TaskRE.MatchString(cmd.Lease.TaskID) || !m3AttemptRE.MatchString(cmd.Lease.AttemptID) ||
		!m3SafeText(cmd.Lease.Owner, 3, 128) || !m3TokenRE.MatchString(cmd.Lease.Token) ||
		cmd.Lease.Generation < 1 || !m3SafeText(cmd.EffectKey, 8, 160) ||
		!m3DigestRE.MatchString(cmd.RequestDigest) {
		return false, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return false, err
	}
	run, err := m3LockRun(ctx, tx, cmd.Lease.TenantID, cmd.Lease.RunID)
	if err != nil {
		return false, m3Rollback(tx, err)
	}
	task, err := m3LockTask(ctx, tx, cmd.Lease.TenantID, cmd.Lease.RunID, cmd.Lease.TaskID)
	if err != nil {
		return false, m3Rollback(tx, err)
	}
	if task.Status != "running" || task.LeaseExpired || task.ActiveAttemptID != cmd.Lease.AttemptID ||
		task.LeaseOwner != cmd.Lease.Owner || task.LeaseToken != cmd.Lease.Token || task.LeaseGeneration != cmd.Lease.Generation {
		return false, m3Rollback(tx, ErrM3StaleLease)
	}
	res, err := tx.ExecContext(ctx, `
		INSERT INTO mission_control_v2.effects
			(tenant_id, effect_key, run_id, task_id, attempt_id, request_digest, status)
		VALUES ($1, $2, $3, $4, $5, $6, 'reserved') ON CONFLICT DO NOTHING`,
		cmd.Lease.TenantID, cmd.EffectKey, cmd.Lease.RunID, cmd.Lease.TaskID, cmd.Lease.AttemptID, cmd.RequestDigest)
	if err != nil {
		return false, m3Rollback(tx, err)
	}
	inserted, err := res.RowsAffected()
	if err != nil {
		return false, m3Rollback(tx, err)
	}
	if inserted == 0 {
		var requestDigest, runID, taskID string
		err := tx.QueryRowContext(ctx, `
			SELECT request_digest, run_id, task_id FROM mission_control_v2.effects
			WHERE tenant_id = $1 AND effect_key = $2 FOR UPDATE`, cmd.Lease.TenantID, cmd.EffectKey).Scan(&requestDigest, &runID, &taskID)
		if err != nil {
			return false, m3Rollback(tx, err)
		}
		if requestDigest != cmd.RequestDigest || runID != cmd.Lease.RunID || taskID != cmd.Lease.TaskID {
			return false, m3Rollback(tx, ErrM3IdempotencyReuse)
		}
		if err := tx.Commit(); err != nil {
			return false, err
		}
		return false, nil
	}
	if _, err := r.appendEvent(ctx, tx, run, "effect.reserved", cmd.Lease.TaskID, cmd.Lease.AttemptID, "", "", "", []string{cmd.RequestDigest}); err != nil {
		return false, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return false, err
	}
	return true, nil
}

func (r *M3PostgresRepository) CommitEffect(ctx context.Context, tenantID, effectKey, resultDigest string) error {
	if !m3TenantRE.MatchString(tenantID) || !m3SafeText(effectKey, 8, 160) || !m3DigestRE.MatchString(resultDigest) {
		return ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return err
	}
	var runID, taskID, attemptID, status, storedDigest string
	err = tx.QueryRowContext(ctx, `
		SELECT run_id, task_id, attempt_id, status, COALESCE(result_digest, '')
		FROM mission_control_v2.effects WHERE tenant_id = $1 AND effect_key = $2 FOR UPDATE`, tenantID, effectKey).Scan(
		&runID, &taskID, &attemptID, &status, &storedDigest)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrM3NotFound
	}
	if err != nil {
		return m3Rollback(tx, err)
	}
	if status == "committed" {
		if storedDigest != resultDigest {
			return m3Rollback(tx, ErrM3IdempotencyReuse)
		}
		return tx.Commit()
	}
	run, err := m3LockRun(ctx, tx, tenantID, runID)
	if err != nil {
		return m3Rollback(tx, err)
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE mission_control_v2.effects SET status = 'committed', result_digest = $3,
			committed_at = clock_timestamp()
		WHERE tenant_id = $1 AND effect_key = $2 AND status = 'reserved'`, tenantID, effectKey, resultDigest); err != nil {
		return m3Rollback(tx, err)
	}
	if _, err := r.appendEvent(ctx, tx, run, "effect.committed", taskID, attemptID, "", "", "", []string{resultDigest}); err != nil {
		return m3Rollback(tx, err)
	}
	return tx.Commit()
}

func (r *M3PostgresRepository) ReplayEvents(ctx context.Context, tenantID, runID string, afterSequence int64, limit int) ([]M3Event, error) {
	if err := m3ValidateScope(tenantID, runID); err != nil || afterSequence < 0 || limit < 1 || limit > 1000 {
		return nil, ErrM3Invalid
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT tenant_id, run_id, sequence, event_id, event_type, run_revision, run_state,
			COALESCE(task_id, ''), COALESCE(attempt_id, ''),
			COALESCE(approval_id, ''), COALESCE(release_id, ''),
			COALESCE(code, ''), array_to_json(evidence_refs), occurred_at
		FROM mission_control_v2.events
		WHERE tenant_id = $1 AND run_id = $2 AND sequence > $3
		ORDER BY sequence LIMIT $4`, tenantID, runID, afterSequence, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var events []M3Event
	for rows.Next() {
		var event M3Event
		var refs []byte
		if err := rows.Scan(&event.TenantID, &event.RunID, &event.Sequence, &event.EventID,
			&event.EventType, &event.RunRevision, &event.RunState, &event.TaskID, &event.AttemptID,
			&event.ApprovalID, &event.ReleaseID, &event.Code, &refs, &event.OccurredAt); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(refs, &event.EvidenceRefs); err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	return events, rows.Err()
}

func (r *M3PostgresRepository) ListAttempts(ctx context.Context, tenantID, runID, taskID string) ([]M3Attempt, error) {
	if err := m3ValidateScope(tenantID, runID); err != nil || !m3TaskRE.MatchString(taskID) {
		return nil, ErrM3Invalid
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT tenant_id, run_id, task_id, attempt_id, attempt_number, lease_generation,
			worker_id, status, started_at, last_heartbeat_at, completed_at,
			COALESCE(output_digest, ''), COALESCE(failure_code, '')
		FROM mission_control_v2.attempts
		WHERE tenant_id = $1 AND run_id = $2 AND task_id = $3
		ORDER BY attempt_number`, tenantID, runID, taskID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var attempts []M3Attempt
	for rows.Next() {
		var item M3Attempt
		var completed sql.NullTime
		if err := rows.Scan(&item.TenantID, &item.RunID, &item.TaskID, &item.AttemptID,
			&item.AttemptNumber, &item.LeaseGeneration, &item.WorkerID, &item.Status,
			&item.StartedAt, &item.LastHeartbeatAt, &completed,
			&item.OutputDigest, &item.FailureCode); err != nil {
			return nil, err
		}
		if completed.Valid {
			value := completed.Time
			item.CompletedAt = &value
		}
		attempts = append(attempts, item)
	}
	return attempts, rows.Err()
}

func (r *M3PostgresRepository) ClaimOutbox(ctx context.Context, owner string, limit int, leaseDuration time.Duration) ([]M3OutboxDelivery, error) {
	if !m3SafeText(owner, 3, 128) || limit < 1 || limit > 500 || leaseDuration < time.Second || leaseDuration > time.Hour {
		return nil, ErrM3Invalid
	}
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return nil, err
	}
	token, err := r.newID("")
	if err != nil {
		return nil, m3Rollback(tx, err)
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE mission_control_v2.events
		SET delivery_status = 'dead_lettered', dead_lettered_at = clock_timestamp(),
			delivery_owner = NULL, delivery_token = NULL, delivery_expires_at = NULL,
			last_error_code = COALESCE(last_error_code, 'DELIVERY_LEASE_EXPIRED')
		WHERE delivery_status = 'in_flight'
			AND delivery_expires_at <= clock_timestamp()
			AND delivery_attempts >= max_delivery_attempts`); err != nil {
		return nil, m3Rollback(tx, err)
	}
	rows, err := tx.QueryContext(ctx, `
		WITH candidates AS (
			SELECT e.tenant_id, e.run_id, e.sequence
			FROM mission_control_v2.events AS e
			WHERE e.delivery_status IN ('pending', 'in_flight')
				AND e.available_at <= clock_timestamp()
				AND (e.delivery_status = 'pending' OR e.delivery_expires_at <= clock_timestamp())
				AND e.delivery_attempts < e.max_delivery_attempts
				AND NOT EXISTS (
					SELECT 1 FROM mission_control_v2.events AS prior
					WHERE prior.tenant_id = e.tenant_id AND prior.run_id = e.run_id
						AND prior.sequence < e.sequence AND prior.delivery_status <> 'published'
				)
			ORDER BY e.occurred_at, e.tenant_id, e.run_id, e.sequence
			FOR UPDATE OF e SKIP LOCKED LIMIT $1
		)
		UPDATE mission_control_v2.events AS e
		SET delivery_status = 'in_flight', delivery_owner = $2, delivery_token = $3,
			delivery_generation = delivery_generation + 1,
			delivery_attempts = delivery_attempts + 1,
			delivery_expires_at = clock_timestamp() + ($4 * interval '1 second')
		FROM candidates AS c
		WHERE e.tenant_id = c.tenant_id AND e.run_id = c.run_id AND e.sequence = c.sequence
		RETURNING e.tenant_id, e.run_id, e.sequence, e.event_id, e.event_type,
			e.run_revision, e.run_state, COALESCE(e.task_id, ''), COALESCE(e.attempt_id, ''),
			COALESCE(e.approval_id, ''), COALESCE(e.release_id, ''), COALESCE(e.code, ''),
			array_to_json(e.evidence_refs), e.occurred_at, e.delivery_generation,
			e.delivery_attempts, e.delivery_expires_at`,
		limit, owner, token, int64(leaseDuration/time.Second))
	if err != nil {
		return nil, m3Rollback(tx, err)
	}
	var deliveries []M3OutboxDelivery
	for rows.Next() {
		var item M3OutboxDelivery
		var refs []byte
		if err := rows.Scan(&item.Event.TenantID, &item.Event.RunID, &item.Event.Sequence,
			&item.Event.EventID, &item.Event.EventType, &item.Event.RunRevision,
			&item.Event.RunState, &item.Event.TaskID, &item.Event.AttemptID, &item.Event.ApprovalID,
			&item.Event.ReleaseID, &item.Event.Code, &refs, &item.Event.OccurredAt,
			&item.DeliveryGeneration, &item.DeliveryAttempts, &item.DeliveryExpiresAt); err != nil {
			_ = rows.Close()
			return nil, m3Rollback(tx, err)
		}
		if err := json.Unmarshal(refs, &item.Event.EvidenceRefs); err != nil {
			_ = rows.Close()
			return nil, m3Rollback(tx, err)
		}
		item.DeliveryOwner = owner
		item.DeliveryToken = token
		deliveries = append(deliveries, item)
	}
	if err := rows.Close(); err != nil {
		return nil, m3Rollback(tx, err)
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	sort.Slice(deliveries, func(i, j int) bool {
		left, right := deliveries[i].Event, deliveries[j].Event
		if !left.OccurredAt.Equal(right.OccurredAt) {
			return left.OccurredAt.Before(right.OccurredAt)
		}
		if left.TenantID != right.TenantID {
			return left.TenantID < right.TenantID
		}
		if left.RunID != right.RunID {
			return left.RunID < right.RunID
		}
		return left.Sequence < right.Sequence
	})
	return deliveries, nil
}

func (r *M3PostgresRepository) MarkOutboxPublished(ctx context.Context, delivery M3OutboxDelivery) error {
	res, err := r.db.ExecContext(ctx, `
		UPDATE mission_control_v2.events
		SET delivery_status = 'published', published_at = clock_timestamp(),
			delivery_owner = NULL, delivery_token = NULL, delivery_expires_at = NULL,
			last_error_code = NULL
		WHERE tenant_id = $1 AND run_id = $2 AND sequence = $3
			AND delivery_status = 'in_flight' AND delivery_owner = $4
			AND delivery_token = $5 AND delivery_generation = $6
			AND delivery_expires_at > clock_timestamp()`,
		delivery.Event.TenantID, delivery.Event.RunID, delivery.Event.Sequence,
		delivery.DeliveryOwner, delivery.DeliveryToken, delivery.DeliveryGeneration)
	if err != nil {
		return err
	}
	if n, err := res.RowsAffected(); err != nil || n != 1 {
		if err != nil {
			return err
		}
		return ErrM3StaleLease
	}
	return nil
}

func (r *M3PostgresRepository) FailOutbox(ctx context.Context, delivery M3OutboxDelivery, errorCode string, retryDelay time.Duration) (bool, error) {
	if !m3CodeRE.MatchString(errorCode) || retryDelay < 0 || retryDelay > 24*time.Hour {
		return false, ErrM3Invalid
	}
	var status string
	err := r.db.QueryRowContext(ctx, `
		UPDATE mission_control_v2.events
		SET delivery_status = CASE WHEN delivery_attempts >= max_delivery_attempts
			THEN 'dead_lettered' ELSE 'pending' END,
			available_at = clock_timestamp() + ($8 * interval '1 second'),
			dead_lettered_at = CASE WHEN delivery_attempts >= max_delivery_attempts
				THEN clock_timestamp() ELSE NULL END,
			delivery_owner = NULL, delivery_token = NULL, delivery_expires_at = NULL,
			last_error_code = $7
		WHERE tenant_id = $1 AND run_id = $2 AND sequence = $3
			AND delivery_status = 'in_flight' AND delivery_owner = $4
			AND delivery_token = $5 AND delivery_generation = $6
			AND delivery_expires_at > clock_timestamp()
		RETURNING delivery_status`,
		delivery.Event.TenantID, delivery.Event.RunID, delivery.Event.Sequence,
		delivery.DeliveryOwner, delivery.DeliveryToken, delivery.DeliveryGeneration,
		errorCode, int64(retryDelay/time.Second)).Scan(&status)
	if errors.Is(err, sql.ErrNoRows) {
		return false, ErrM3StaleLease
	}
	return status == "dead_lettered", err
}
