package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

const (
	m3TestTenant = "tnt_testtenant01"
	m3TestRun    = "run_testrun000001"
	m3TestDigest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

func TestM3TransitionStateMachine(t *testing.T) {
	allowed := []struct{ from, to M3RunState }{
		{M3RunCreated, M3RunRunning},
		{M3RunCreated, M3RunCancelled},
		{M3RunRunning, M3RunAwaitingInput},
		{M3RunRunning, M3RunAwaitingApproval},
		{M3RunAwaitingInput, M3RunRunning},
		{M3RunApproved, M3RunRunning},
		{M3RunApproved, M3RunSucceeded},
	}
	for _, transition := range allowed {
		if !m3TransitionAllowed(transition.from, transition.to) {
			t.Errorf("expected %s -> %s to be allowed", transition.from, transition.to)
		}
	}
	blocked := []struct{ from, to M3RunState }{
		{M3RunCreated, M3RunSucceeded},
		{M3RunAwaitingApproval, M3RunApproved}, // approval command only
		{M3RunRejected, M3RunRunning},
		{M3RunSucceeded, M3RunRunning},
		{M3RunFailed, M3RunRunning},
		{M3RunCancelled, M3RunRunning},
	}
	for _, transition := range blocked {
		if m3TransitionAllowed(transition.from, transition.to) {
			t.Errorf("expected %s -> %s to be blocked", transition.from, transition.to)
		}
	}
}

func TestM3SanitizedEventValidation(t *testing.T) {
	valid := []string{
		m3TestDigest,
		"art_PROTECTED0001",
	}
	if !m3ValidEvidenceRefs(valid) {
		t.Fatal("digest and artifact references should be accepted")
	}
	for _, unsafe := range [][]string{
		{"customer@example.com"},
		{"raw row contents"},
		{"sha256:ABC"},
		{strings.Repeat("art_A", 40)},
	} {
		if m3ValidEvidenceRefs(unsafe) {
			t.Errorf("unsafe evidence accepted: %#v", unsafe)
		}
	}
	tooMany := make([]string, 33)
	for i := range tooMany {
		tooMany[i] = m3TestDigest
	}
	if m3ValidEvidenceRefs(tooMany) {
		t.Fatal("oversized evidence set should be rejected")
	}
}

func TestM3ValidationRejectsCrossScopeAndUnsafeValues(t *testing.T) {
	if err := m3ValidateScope(m3TestTenant, m3TestRun); err != nil {
		t.Fatalf("valid scope: %v", err)
	}
	for _, scope := range [][2]string{
		{"tenant", m3TestRun},
		{m3TestTenant, "run"},
		{m3TestTenant + "\n", m3TestRun},
	} {
		if !errors.Is(m3ValidateScope(scope[0], scope[1]), ErrM3Invalid) {
			t.Errorf("scope accepted: %#v", scope)
		}
	}
	if m3SafeText("worker\nforged", 3, 128) {
		t.Fatal("control character accepted")
	}
	if !m3TokenRE.MatchString("0123456789abcdef0123456789abcdef") {
		t.Fatal("valid lease token rejected")
	}
}

func TestM3MigrationContract(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("migrations", "m3_001_cloud_sql_authority.sql"))
	if err != nil {
		t.Fatal(err)
	}
	sqlText := string(raw)
	required := []string{
		"CREATE TABLE runs (",
		"PRIMARY KEY (tenant_id, run_id)",
		"CREATE TABLE approval_nonces (",
		"PRIMARY KEY (tenant_id, nonce_digest)",
		"CREATE TABLE approvals (",
		"UNIQUE (tenant_id, run_id, stage)",
		"production approval requires a distinct approved simulation decision",
		"CREATE TABLE workflow_checkpoints (",
		"post_seal_model_calls integer NOT NULL DEFAULT 0 CHECK (post_seal_model_calls = 0)",
		"CREATE TABLE workflow_approval_entries (",
		"authority_record_digest varchar(71) NOT NULL",
		"workflow checkpoint must be created before the production boundary",
		"CREATE TABLE releases (",
		"signature_digest varchar(71) NOT NULL",
		"CREATE TABLE launch_results (",
		"CREATE TABLE reconciliation_results (",
		"CREATE TABLE tasks (",
		"CREATE TABLE attempts (",
		"CREATE TABLE effects (",
		"CREATE TABLE idempotency_results (",
		"PRIMARY KEY (tenant_id, run_id, node_path, operation, idempotency_key)",
		"CREATE TABLE events (",
		"CREATE INDEX events_outbox_claim_idx",
		"terminal attempt is immutable",
		"event projection is immutable",
		"event sequence must be allocated by the locked run row",
		"consumed approval nonce is immutable",
		"'checkpoint.sealed'",
	}
	for _, fragment := range required {
		if !strings.Contains(sqlText, fragment) {
			t.Errorf("migration missing %q", fragment)
		}
	}
	eventsStart := strings.Index(sqlText, "CREATE TABLE events (")
	eventsEnd := strings.Index(sqlText[eventsStart:], ");")
	if eventsStart < 0 || eventsEnd < 0 {
		t.Fatal("cannot isolate events table")
	}
	eventColumns := strings.ToLower(sqlText[eventsStart : eventsStart+eventsEnd])
	for _, forbidden := range []string{"payload", "prompt", "reasoning", "raw_data", "actor_subject", "summary"} {
		if strings.Contains(eventColumns, forbidden) {
			t.Errorf("events table exposes forbidden field %q", forbidden)
		}
	}
}

func TestM3RepositoryCriticalWriteOrdering(t *testing.T) {
	raw, err := os.ReadFile("m3_persistence.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(raw)
	assertOrdered := func(name string, fragments ...string) {
		t.Helper()
		positions := make([]int, len(fragments))
		cursor := 0
		for i, fragment := range fragments {
			at := strings.Index(source[cursor:], fragment)
			if at < 0 {
				t.Errorf("%s missing %q", name, fragment)
				return
			}
			cursor += at + len(fragment)
			positions[i] = cursor
		}
		if !slices.IsSorted(positions) {
			t.Errorf("%s ordering not monotonic: %v", name, positions)
		}
	}
	assertOrdered("state/outbox/commit",
		"func (r *M3PostgresRepository) TransitionRun",
		"UPDATE mission_control_v2.runs",
		"r.appendEvent",
		"m3StoreIdempotency",
		"tx.Commit()",
	)
	assertOrdered("nonce/approval/advance/outbox/commit",
		"func (r *M3PostgresRepository) RecordApproval",
		"UPDATE mission_control_v2.approval_nonces",
		"INSERT INTO mission_control_v2.approvals",
		"UPDATE mission_control_v2.runs",
		"r.appendEvent",
		"tx.Commit()",
	)
	assertOrdered("production journal/seal/run/outbox/idempotency/commit",
		"func (r *M3PostgresRepository) CommitProductionApprovalSeal",
		"m3InsertWorkflowApprovalEntry",
		"UPDATE mission_control_v2.workflow_checkpoints",
		"UPDATE mission_control_v2.runs",
		"r.appendEvent",
		"m3StoreIdempotency",
		"tx.Commit()",
	)
	assertOrdered("signed release/outbox/commit",
		"func (r *M3PostgresRepository) CreateRelease",
		"INSERT INTO mission_control_v2.releases",
		"signature_digest",
		"UPDATE mission_control_v2.runs",
		"r.appendEvent",
		"tx.Commit()",
	)
	assertOrdered("launch/outbox/commit",
		"func (r *M3PostgresRepository) RecordLaunchResult",
		"INSERT INTO mission_control_v2.launch_results",
		"r.appendEvent",
		"tx.Commit()",
	)
	assertOrdered("reconciliation/outbox/commit",
		"func (r *M3PostgresRepository) RecordReconciliation",
		"INSERT INTO mission_control_v2.reconciliation_results",
		"r.appendEvent",
		"tx.Commit()",
	)
}

// TestM3PostgresContractIntegration applies the actual migration to a unique
// schema inside one transaction and rolls the entire test back. It is skipped
// in the normal offline gate unless M3_TEST_DATABASE_DSN is explicitly set.
func TestM3PostgresContractIntegration(t *testing.T) {
	dsn := os.Getenv("M3_TEST_DATABASE_DSN")
	if dsn == "" {
		t.Skip("M3_TEST_DATABASE_DSN is unset; live PostgreSQL contract test not requested")
	}
	psql, err := exec.LookPath("psql")
	if err != nil {
		t.Skip("psql is unavailable")
	}
	raw, err := os.ReadFile(filepath.Join("migrations", "m3_001_cloud_sql_authority.sql"))
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("mission_control_v2_it_%d", os.Getpid())
	migration := strings.TrimSpace(string(raw))
	migration = strings.TrimPrefix(migration, "BEGIN;")
	migration = strings.TrimSuffix(strings.TrimSpace(migration), "COMMIT;")
	migration = strings.ReplaceAll(migration, "mission_control_v2", schema)
	script := "BEGIN;\n" + migration + "\n" + m3PostgresAssertions(schema) + "\nROLLBACK;\n"
	cmd := exec.Command(psql, "-X", "-v", "ON_ERROR_STOP=1", "-d", dsn)
	cmd.Stdin = strings.NewReader(script)
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("live PostgreSQL contract failed: %v\n%s", err, output)
	}
}

func m3PostgresAssertions(schema string) string {
	return fmt.Sprintf(`
SET LOCAL search_path = %[1]s, pg_catalog;

INSERT INTO runs (tenant_id, run_id, lifecycle_state, revision, plan_digest, next_event_sequence)
VALUES ('tnt_testtenant01', 'run_testrun000001', 'awaiting_approval', 2,
        'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 2);

INSERT INTO events
    (tenant_id, run_id, sequence, event_id, event_type, run_revision, run_state, evidence_refs)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 1, 'evt_CREATED000001',
     'run.created', 1, 'created', '{}');

SAVEPOINT simulated_process_crash;
UPDATE runs SET lifecycle_state = 'failed', revision = 3, next_event_sequence = 3
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
INSERT INTO events
    (tenant_id, run_id, sequence, event_id, event_type, run_revision, run_state, code, evidence_refs)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 2, 'evt_FAILED0000001',
     'run.transitioned', 3, 'failed', 'SIMULATED_CRASH', '{}');
ROLLBACK TO SAVEPOINT simulated_process_crash;

DO $assert$
DECLARE state_value varchar; revision_value bigint; event_count bigint;
BEGIN
    SELECT lifecycle_state, revision INTO state_value, revision_value FROM runs
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    SELECT count(*) INTO event_count FROM events
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    IF state_value <> 'awaiting_approval' OR revision_value <> 2 OR event_count <> 1 THEN
        RAISE EXCEPTION 'state/outbox crash atomicity failed';
    END IF;
END
$assert$;

INSERT INTO approval_nonces
    (tenant_id, run_id, request_id, stage, nonce_digest, request_digest,
     plan_digest, release_digest, artifact_digest, subject_digest,
     checkpoint_digest, simulation_record_digest, expires_at)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'req.production.contract.01', 'production',
     'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
     'sha256:4444444444444444444444444444444444444444444444444444444444444444',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
     'sha256:3333333333333333333333333333333333333333333333333333333333333333',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'sha256:8888888888888888888888888888888888888888888888888888888888888888',
     'sha256:6666666666666666666666666666666666666666666666666666666666666666',
     clock_timestamp() + interval '1 hour');
UPDATE approval_nonces SET consumed_at = clock_timestamp(), approval_id = 'apr_PRODUCTION0001'
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001'
  AND nonce_digest = 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  AND consumed_at IS NULL;
INSERT INTO approvals
    (tenant_id, approval_id, run_id, stage, request_digest, record_digest,
     plan_digest, release_digest, artifact_digest, subject_digest, nonce_digest,
     checkpoint_digest, decision, actor_subject)
VALUES
    ('tnt_testtenant01', 'apr_SIMULATION0001', 'run_testrun000001', 'simulation',
     'sha256:1111111111111111111111111111111111111111111111111111111111111111',
     'sha256:6666666666666666666666666666666666666666666666666666666666666666',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
     'sha256:3333333333333333333333333333333333333333333333333333333333333333',
     'sha256:9999999999999999999999999999999999999999999999999999999999999999',
     'sha256:2222222222222222222222222222222222222222222222222222222222222222',
     'sha256:8888888888888888888888888888888888888888888888888888888888888888',
     'approve', 'principal:simulation');
INSERT INTO approvals
    (tenant_id, approval_id, run_id, stage, request_digest, record_digest,
     plan_digest, release_digest, artifact_digest, subject_digest, nonce_digest,
     checkpoint_digest, simulation_approval_id, simulation_record_digest,
     decision, actor_subject)
VALUES
    ('tnt_testtenant01', 'apr_PRODUCTION0001', 'run_testrun000001', 'production',
     'sha256:4444444444444444444444444444444444444444444444444444444444444444',
     'sha256:7777777777777777777777777777777777777777777777777777777777777777',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
     'sha256:3333333333333333333333333333333333333333333333333333333333333333',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
     'sha256:8888888888888888888888888888888888888888888888888888888888888888',
     'apr_SIMULATION0001',
     'sha256:6666666666666666666666666666666666666666666666666666666666666666',
     'approve', 'principal:production');
UPDATE runs SET lifecycle_state = 'approved',
    simulation_approval_id = 'apr_SIMULATION0001',
    production_approval_id = 'apr_PRODUCTION0001',
    approval_id = 'apr_PRODUCTION0001', revision = 3
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';

INSERT INTO idempotency_results
    (tenant_id, run_id, node_path, plan_digest, operation, idempotency_key, request_digest, response_json)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', '/control/approval.record',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'approval.record', 'approve.request.0001',
     'sha256:4444444444444444444444444444444444444444444444444444444444444444',
     '{"runId":"run_testrun000001","revision":3}'::jsonb);
INSERT INTO idempotency_results
    (tenant_id, run_id, node_path, plan_digest, operation, idempotency_key, request_digest, response_json)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', '/control/approval.record',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'approval.record', 'approve.request.0001',
     'sha256:4444444444444444444444444444444444444444444444444444444444444444',
     '{"runId":"run_testrun000001","revision":3}'::jsonb)
ON CONFLICT DO NOTHING;

DO $assert$
BEGIN
    BEGIN
        UPDATE approval_nonces SET approval_id = 'apr_DIFFERENT0001'
        WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
        RAISE EXCEPTION 'consumed nonce update unexpectedly succeeded';
    EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL;
    END;
END
$assert$;

INSERT INTO releases
    (tenant_id, release_id, run_id, approval_id, subject_digest, release_kind,
     artifact_digest, signer_key_version, signature_digest)
VALUES
    ('tnt_testtenant01', 'rel_RELEASE000001', 'run_testrun000001', 'apr_PRODUCTION0001',
     'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'production',
     'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
     'projects/test/locations/us/keyRings/test/cryptoKeys/release/cryptoKeyVersions/1',
     'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd');
UPDATE runs SET release_id = 'rel_RELEASE000001', revision = 4, next_event_sequence = 3
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
INSERT INTO events
    (tenant_id, run_id, sequence, event_id, event_type, run_revision, run_state,
     approval_id, release_id, evidence_refs)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 2, 'evt_RELEASE000001',
     'release.created', 4, 'approved', 'apr_PRODUCTION0001', 'rel_RELEASE000001',
     ARRAY['sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd']);

INSERT INTO launch_results
    (tenant_id, run_id, launch_key, release_id, request_digest, status, operation_ref, result_digest)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'launch:production:0001', 'rel_RELEASE000001',
     'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
     'launched', 'dataflow/job-0001',
     'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff');
INSERT INTO launch_results
    (tenant_id, run_id, launch_key, release_id, request_digest, status, operation_ref, result_digest)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'launch:production:0001', 'rel_RELEASE000001',
     'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
     'launched', 'dataflow/job-0001',
     'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff')
ON CONFLICT DO NOTHING;

INSERT INTO reconciliation_results
    (tenant_id, run_id, reconciliation_id, release_id, launch_key, outcome, result_digest, evidence_digest)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'rec_RECONCILE0001', 'rel_RELEASE000001',
     'launch:production:0001', 'verified',
     'sha256:1111111111111111111111111111111111111111111111111111111111111111',
     'sha256:2222222222222222222222222222222222222222222222222222222222222222');

DO $assert$
DECLARE launch_count bigint; release_count bigint; reconciliation_count bigint;
        idempotency_count bigint; replay_sequence text;
BEGIN
    SELECT count(*) INTO launch_count FROM launch_results
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    SELECT count(*) INTO release_count FROM releases
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    SELECT count(*) INTO reconciliation_count FROM reconciliation_results
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    SELECT count(*) INTO idempotency_count FROM idempotency_results
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001'
      AND node_path = '/control/approval.record' AND idempotency_key = 'approve.request.0001';
    SELECT string_agg(sequence::text, ',' ORDER BY sequence) INTO replay_sequence FROM events
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
    IF launch_count <> 1 OR release_count <> 1 OR reconciliation_count <> 1 OR
       idempotency_count <> 1 OR replay_sequence <> '1,2' THEN
        RAISE EXCEPTION 'duplicate/replay invariant failed: launch=%% release=%% reconciliation=%% idempotency=%% sequence=%%',
            launch_count, release_count, reconciliation_count, idempotency_count, replay_sequence;
    END IF;
END
$assert$;

INSERT INTO tasks
    (tenant_id, run_id, task_id, node_path, input_digest, max_attempts)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'tsk_TASK00000001', '/deterministic/dispatch',
     'sha256:3333333333333333333333333333333333333333333333333333333333333333', 2);
UPDATE tasks SET status = 'running', attempts_started = 1, lease_owner = 'worker:test',
    lease_token = '0123456789abcdef0123456789abcdef', lease_generation = 1,
    lease_expires_at = clock_timestamp() + interval '1 minute', active_attempt_id = 'att_ATTEMPT000001'
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001' AND task_id = 'tsk_TASK00000001';
INSERT INTO attempts
    (tenant_id, run_id, task_id, attempt_id, attempt_number, lease_generation, worker_id, status)
VALUES
    ('tnt_testtenant01', 'run_testrun000001', 'tsk_TASK00000001', 'att_ATTEMPT000001',
     1, 1, 'worker:test', 'running');

INSERT INTO effects
    (tenant_id, effect_key, run_id, task_id, attempt_id, request_digest, status)
VALUES
    ('tnt_testtenant01', 'effect:dataflow:0001', 'run_testrun000001', 'tsk_TASK00000001',
     'att_ATTEMPT000001',
     'sha256:5555555555555555555555555555555555555555555555555555555555555555',
     'reserved');
INSERT INTO effects
    (tenant_id, effect_key, run_id, task_id, attempt_id, request_digest, status)
VALUES
    ('tnt_testtenant01', 'effect:dataflow:0001', 'run_testrun000001', 'tsk_TASK00000001',
     'att_ATTEMPT000001',
     'sha256:5555555555555555555555555555555555555555555555555555555555555555',
     'reserved')
ON CONFLICT DO NOTHING;

DO $assert$
DECLARE effect_count bigint;
BEGIN
    SELECT count(*) INTO effect_count FROM effects
    WHERE tenant_id = 'tnt_testtenant01' AND effect_key = 'effect:dataflow:0001';
    IF effect_count <> 1 THEN
        RAISE EXCEPTION 'duplicate effect count was %%', effect_count;
    END IF;
END
$assert$;

DO $assert$
DECLARE changed bigint;
BEGIN
    UPDATE tasks SET lease_expires_at = clock_timestamp() + interval '1 minute'
    WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001'
      AND task_id = 'tsk_TASK00000001' AND lease_owner = 'worker:test'
      AND lease_token = 'ffffffffffffffffffffffffffffffff' AND lease_generation = 1
      AND lease_expires_at > clock_timestamp();
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 0 THEN RAISE EXCEPTION 'stale lease updated authoritative task'; END IF;
END
$assert$;

UPDATE attempts SET status = 'timed_out', completed_at = clock_timestamp(), failure_code = 'LEASE_EXPIRED'
WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001' AND attempt_id = 'att_ATTEMPT000001';
DO $assert$
BEGIN
    BEGIN
        UPDATE attempts SET failure_code = 'MUTATED'
        WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
        RAISE EXCEPTION 'terminal attempt mutation unexpectedly succeeded';
    EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL;
    END;
END
$assert$;

DO $assert$
BEGIN
    BEGIN
        UPDATE runs SET next_event_sequence = 4
        WHERE tenant_id = 'tnt_testtenant01' AND run_id = 'run_testrun000001';
        INSERT INTO events
            (tenant_id, run_id, sequence, event_id, event_type, run_revision, run_state, evidence_refs)
        VALUES
            ('tnt_testtenant01', 'run_testrun000001', 3, 'evt_UNSAFE0000001',
             'run.transitioned', 4, 'approved', ARRAY['raw customer@example.com']);
        RAISE EXCEPTION 'unsafe event unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END
$assert$;
`, schema)
}
