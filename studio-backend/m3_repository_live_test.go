package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestM3PostgresRepositoryLive executes real pgx/database/sql repository
// methods. It stays opt-in so offline gates never require PostgreSQL. The
// database-name guard prevents resetting anything except a dedicated M3 test
// database.
func TestM3PostgresRepositoryLive(t *testing.T) {
	dsn := os.Getenv("M3_TEST_DATABASE_DSN")
	if dsn == "" {
		t.Skip("M3_TEST_DATABASE_DSN is unset; live repository test not requested")
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	var databaseName string
	if err := db.QueryRowContext(ctx, `SELECT current_database()`).Scan(&databaseName); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(databaseName, "zero_trust_m3_test") {
		t.Fatalf("refusing live repository test against non-M3 test database %q", databaseName)
	}

	if _, err := db.ExecContext(ctx, `DROP SCHEMA IF EXISTS mission_control_v2 CASCADE`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, cleanupErr := db.ExecContext(context.Background(), `DROP SCHEMA IF EXISTS mission_control_v2 CASCADE`); cleanupErr != nil {
			t.Errorf("clean live schema: %v", cleanupErr)
		}
	}()
	migration, err := os.ReadFile(filepath.Join("migrations", "m3_001_cloud_sql_authority.sql"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, string(migration)); err != nil {
		t.Fatalf("apply M3 migration: %v", err)
	}
	repository, err := NewM3PostgresRepository(db)
	if err != nil {
		t.Fatal(err)
	}

	t.Run("missing simulation rejects seal without writes", func(t *testing.T) {
		const tenantID = "tnt_liverepo01"
		const runID = "run_missing_sim_0001"
		plan := digestForTest("missing-plan")
		revision := m3LiveCreateWaitingRun(t, ctx, repository, tenantID, runID, plan, "missing")
		raw, checkpointDigest := m3LiveCanonical("run_checkpoint", "missing-current")
		checkpoint := M3WorkflowCheckpoint{
			TenantID: tenantID, RunID: runID, Revision: 1,
			CheckpointDigest: checkpointDigest, SourceDigest: digestForTest("missing-source"),
			RequestDigest: digestForTest("missing-request"), PlanDigest: plan,
			Phase: "verified", Sequence: 3, ChainDigest: digestForTest("missing-chain"),
			CanonicalJSON: raw, ModelCalls: 2,
		}
		if err := repository.CreateWorkflowCheckpoint(ctx, checkpoint); err != nil {
			t.Fatal(err)
		}
		sealed := m3LiveSealedCheckpoint(checkpoint, "missing-sealed", "apr_missing_prod_01")
		entry := m3LiveJournalEntry(tenantID, runID, M3ProductionStage,
			"apr_missing_prod_01", "missing-prod-journal", digestForTest("missing-prod-authority"),
			checkpoint.SourceDigest, digestForTest("missing-prod-subject"), checkpoint.ChainDigest,
			"actor_missing_prod")
		_, err := repository.CommitProductionApprovalSeal(ctx, M3CommitProductionApprovalSealCommand{
			TenantID: tenantID, RunID: runID, ExpectedRunRevision: revision,
			ExpectedCheckpointRevision: 1, ExpectedCheckpointDigest: checkpoint.CheckpointDigest,
			SimulationApprovalID: "apr_missing_sim_001", ProductionApprovalID: "apr_missing_prod_01",
			ProductionEntry: entry, SealedCheckpoint: sealed,
			IdempotencyKey: "seal.missing.simulation.01", RequestDigest: digestForTest("missing-seal-request"),
		})
		if !errors.Is(err, ErrM3Conflict) {
			t.Fatalf("missing simulation error = %v, want conflict", err)
		}
		m3LiveAssertCounts(t, ctx, db, tenantID, runID, map[string]int{
			"approvals": 0, "workflow_approval_entries": 0, "workflow_checkpoints": 1,
			"events": 3, "idempotency_results": 3,
		})
	})

	t.Run("production seal CAS is atomic and replayable", func(t *testing.T) {
		fixture := m3LivePrepareSealableRun(t, ctx, repository)
		baseCounts := map[string]int{
			"approvals": 2, "approval_nonces": 2, "workflow_approval_entries": 1,
			"workflow_checkpoints": 1, "events": 5, "idempotency_results": 5,
		}
		m3LiveAssertCounts(t, ctx, db, fixture.tenantID, fixture.runID, baseCounts)

		mismatched := fixture.command
		mismatched.SimulationApprovalID = "apr_wrong_simulation_01"
		mismatched.IdempotencyKey = "seal.mismatched.simulation.01"
		mismatched.RequestDigest = digestForTest("mismatched-simulation-request")
		if _, err := repository.CommitProductionApprovalSeal(ctx, mismatched); !errors.Is(err, ErrM3Conflict) {
			t.Fatalf("mismatched simulation error = %v, want conflict", err)
		}
		m3LiveAssertCounts(t, ctx, db, fixture.tenantID, fixture.runID, baseCounts)

		stale := fixture.command
		stale.ExpectedCheckpointDigest = digestForTest("stale-checkpoint")
		stale.IdempotencyKey = "seal.stale.checkpoint.0001"
		stale.RequestDigest = digestForTest("stale-checkpoint-request")
		if _, err := repository.CommitProductionApprovalSeal(ctx, stale); !errors.Is(err, ErrM3RevisionConflict) {
			t.Fatalf("stale checkpoint error = %v, want revision conflict", err)
		}
		m3LiveAssertCounts(t, ctx, db, fixture.tenantID, fixture.runID, baseCounts)

		if _, err := db.ExecContext(ctx, `
			CREATE FUNCTION mission_control_v2.m3_test_fail_checkpoint_update() RETURNS trigger
			LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected seal failure'; END; $$;
			CREATE TRIGGER m3_test_fail_checkpoint_update
			BEFORE UPDATE ON mission_control_v2.workflow_checkpoints
			FOR EACH ROW EXECUTE FUNCTION mission_control_v2.m3_test_fail_checkpoint_update()`); err != nil {
			t.Fatal(err)
		}
		injected := fixture.command
		injected.IdempotencyKey = "seal.injected.failure.0001"
		injected.RequestDigest = digestForTest("injected-failure-request")
		if _, err := repository.CommitProductionApprovalSeal(ctx, injected); err == nil {
			t.Fatal("injected checkpoint failure unexpectedly committed")
		}
		if _, err := db.ExecContext(ctx, `
			DROP TRIGGER m3_test_fail_checkpoint_update ON mission_control_v2.workflow_checkpoints;
			DROP FUNCTION mission_control_v2.m3_test_fail_checkpoint_update()`); err != nil {
			t.Fatal(err)
		}
		m3LiveAssertCounts(t, ctx, db, fixture.tenantID, fixture.runID, baseCounts)
		current, err := repository.GetWorkflowCheckpoint(ctx, fixture.tenantID, fixture.runID)
		if err != nil || current.Phase != "simulation_approved" || current.SealDigest != "" || current.Revision != 1 {
			t.Fatalf("injected failure changed checkpoint: checkpoint=%#v err=%v", current, err)
		}

		committed, err := repository.CommitProductionApprovalSeal(ctx, fixture.command)
		if err != nil {
			t.Fatal(err)
		}
		if committed.State != M3RunApproved || committed.Revision != 6 || committed.EventSequence != 6 || committed.Replayed {
			t.Fatalf("unexpected production seal result: %#v", committed)
		}
		replayed, err := repository.CommitProductionApprovalSeal(ctx, fixture.command)
		if err != nil {
			t.Fatal(err)
		}
		if !replayed.Replayed || replayed.Revision != committed.Revision ||
			replayed.EventSequence != committed.EventSequence || replayed.ApprovalID != committed.ApprovalID {
			t.Fatalf("seal replay changed result: first=%#v replay=%#v", committed, replayed)
		}
		m3LiveAssertCounts(t, ctx, db, fixture.tenantID, fixture.runID, map[string]int{
			"approvals": 2, "approval_nonces": 2, "workflow_approval_entries": 2,
			"workflow_checkpoints": 1, "events": 6, "idempotency_results": 6,
		})
		sealed, err := repository.GetWorkflowCheckpoint(ctx, fixture.tenantID, fixture.runID)
		if err != nil || sealed.Phase != "approved_for_execution" || sealed.Revision != 2 ||
			sealed.ModelCallsAtSeal == nil || *sealed.ModelCallsAtSeal != sealed.ModelCalls ||
			sealed.PostSealModelCalls != 0 || sealed.ProductionApprovalID != fixture.productionApprovalID {
			t.Fatalf("invalid durable seal: checkpoint=%#v err=%v", sealed, err)
		}
		var pendingSealEvents int
		if err := db.QueryRowContext(ctx, `
			SELECT count(*) FROM mission_control_v2.events
			WHERE tenant_id = $1 AND run_id = $2 AND event_type = 'checkpoint.sealed'
			  AND delivery_status = 'pending'`, fixture.tenantID, fixture.runID).Scan(&pendingSealEvents); err != nil {
			t.Fatal(err)
		}
		if pendingSealEvents != 1 {
			t.Fatalf("state commit before relay lost/duplicated seal event: %d", pendingSealEvents)
		}
		events, err := repository.ReplayEvents(ctx, fixture.tenantID, fixture.runID, 0, 20)
		if err != nil {
			t.Fatal(err)
		}
		if len(events) != 6 || events[5].EventType != "checkpoint.sealed" || len(events[5].EvidenceRefs) != 3 {
			t.Fatalf("unexpected replay projection: %#v", events)
		}
		for index, event := range events {
			if event.Sequence != int64(index+1) {
				t.Fatalf("non-contiguous replay at %d: %#v", index, event)
			}
		}
	})

	t.Run("nonce digest is tenant-global", func(t *testing.T) {
		const tenantID = "tnt_liverepo01"
		const runID = "run_nonce_scope_0001"
		plan := digestForTest("nonce-scope-plan")
		m3LiveCreateWaitingRun(t, ctx, repository, tenantID, runID, plan, "nonce-scope")
		err := repository.RegisterApprovalNonce(ctx, M3ApprovalNonceCommand{
			TenantID: tenantID, RunID: runID, RequestID: "req.nonce.scope.0001",
			Stage: M3SimulationStage, NonceDigest: digestForTest("simulation-nonce"),
			RequestDigest: digestForTest("nonce-scope-request"), PlanDigest: plan,
			ReleaseDigest:    digestForTest("nonce-scope-release"),
			ArtifactDigest:   digestForTest("nonce-scope-artifact"),
			SubjectDigest:    digestForTest("nonce-scope-subject"),
			CheckpointDigest: digestForTest("nonce-scope-checkpoint"),
			ExpiresAt:        time.Now().UTC().Add(time.Minute),
		})
		if !errors.Is(err, ErrM3Conflict) {
			t.Fatalf("tenant-global nonce reuse error = %v, want conflict", err)
		}
		var count int
		if err := db.QueryRowContext(ctx, `
			SELECT count(*) FROM mission_control_v2.approval_nonces
			WHERE tenant_id = $1 AND nonce_digest = $2`, tenantID, digestForTest("simulation-nonce")).Scan(&count); err != nil {
			t.Fatal(err)
		}
		if count != 1 {
			t.Fatalf("tenant-global nonce duplicate count = %d", count)
		}
	})
}

type m3LiveSealFixture struct {
	tenantID, runID, productionApprovalID string
	command                               M3CommitProductionApprovalSealCommand
}

func m3LivePrepareSealableRun(t *testing.T, ctx context.Context, repository *M3PostgresRepository) m3LiveSealFixture {
	t.Helper()
	const (
		tenantID           = "tnt_liverepo01"
		runID              = "run_sealable_prod_001"
		simulationApproval = "apr_simulation_live_01"
		productionApproval = "apr_production_live_01"
	)
	plan := digestForTest("live-plan")
	source := digestForTest("live-source")
	checkpointRaw, checkpointDigest := m3LiveCanonical("run_checkpoint", "simulation-approved")
	revision := m3LiveCreateWaitingRun(t, ctx, repository, tenantID, runID, plan, "sealable")
	simulationRecord := digestForTest("simulation-authority-record")
	simulationSubject := digestForTest("simulation-subject")
	if err := repository.RegisterApprovalNonce(ctx, M3ApprovalNonceCommand{
		TenantID: tenantID, RunID: runID, RequestID: "req.simulation.live.0001",
		Stage: M3SimulationStage, NonceDigest: digestForTest("simulation-nonce"),
		RequestDigest: digestForTest("simulation-request"), PlanDigest: plan,
		ReleaseDigest: digestForTest("simulation-release"), ArtifactDigest: digestForTest("simulation-artifact"),
		SubjectDigest: simulationSubject, CheckpointDigest: checkpointDigest,
		ExpiresAt: time.Now().UTC().Add(time.Minute),
	}); err != nil {
		t.Fatal(err)
	}
	simulation, err := repository.RecordApproval(ctx, M3ApprovalCommand{
		TenantID: tenantID, RunID: runID, ApprovalID: simulationApproval,
		RequestID: "req.simulation.live.0001", Stage: M3SimulationStage,
		RequestDigest: digestForTest("simulation-request"), RecordDigest: simulationRecord,
		PlanDigest: plan, ReleaseDigest: digestForTest("simulation-release"),
		ArtifactDigest: digestForTest("simulation-artifact"), SubjectDigest: simulationSubject,
		NonceDigest: digestForTest("simulation-nonce"), CheckpointDigest: checkpointDigest,
		Decision: M3Approve, ActorSubject: "actor_simulation",
		IdempotencyKey: "approval.simulation.live.01", ExpectedRevision: revision,
	})
	if err != nil {
		t.Fatal(err)
	}
	simulationEntry := m3LiveJournalEntry(tenantID, runID, M3SimulationStage,
		simulationApproval, "simulation-journal", simulationRecord, source,
		simulationSubject, digestForTest("pre-simulation-chain"), "actor_simulation")
	if err := repository.AppendSimulationApprovalJournal(ctx, simulationEntry); err != nil {
		t.Fatal(err)
	}
	checkpoint := M3WorkflowCheckpoint{
		TenantID: tenantID, RunID: runID, Revision: 1,
		CheckpointDigest: checkpointDigest, SourceDigest: source,
		RequestDigest: digestForTest("workflow-request"), PlanDigest: plan,
		Phase: "simulation_approved", Sequence: 17, ChainDigest: digestForTest("simulation-chain"),
		CanonicalJSON: checkpointRaw, ModelCalls: 7,
	}
	if err := repository.CreateWorkflowCheckpoint(ctx, checkpoint); err != nil {
		t.Fatal(err)
	}
	productionRecord := digestForTest("production-authority-record")
	productionSubject := plan
	if err := repository.RegisterApprovalNonce(ctx, M3ApprovalNonceCommand{
		TenantID: tenantID, RunID: runID, RequestID: "req.production.live.0001",
		Stage: M3ProductionStage, NonceDigest: digestForTest("production-nonce"),
		RequestDigest: digestForTest("production-request"), PlanDigest: plan,
		ReleaseDigest: digestForTest("production-release"), ArtifactDigest: digestForTest("production-artifact"),
		SubjectDigest: productionSubject, CheckpointDigest: checkpointDigest,
		SimulationRecordDigest: simulationRecord, ExpiresAt: time.Now().UTC().Add(time.Minute),
	}); err != nil {
		t.Fatal(err)
	}
	production, err := repository.RecordApproval(ctx, M3ApprovalCommand{
		TenantID: tenantID, RunID: runID, ApprovalID: productionApproval,
		RequestID: "req.production.live.0001", Stage: M3ProductionStage,
		RequestDigest: digestForTest("production-request"), RecordDigest: productionRecord,
		PlanDigest: plan, ReleaseDigest: digestForTest("production-release"),
		ArtifactDigest: digestForTest("production-artifact"), SubjectDigest: productionSubject,
		NonceDigest: digestForTest("production-nonce"), CheckpointDigest: checkpointDigest,
		SimulationApprovalID: simulationApproval, SimulationRecordDigest: simulationRecord,
		Decision: M3Approve, ActorSubject: "actor_production",
		IdempotencyKey: "approval.production.live.01", ExpectedRevision: simulation.Revision,
	})
	if err != nil {
		t.Fatal(err)
	}
	sealed := m3LiveSealedCheckpoint(checkpoint, "production-sealed", productionApproval)
	productionEntry := m3LiveJournalEntry(tenantID, runID, M3ProductionStage,
		productionApproval, "production-journal", productionRecord, source,
		productionSubject, checkpoint.ChainDigest, "actor_production")
	return m3LiveSealFixture{
		tenantID: tenantID, runID: runID, productionApprovalID: productionApproval,
		command: M3CommitProductionApprovalSealCommand{
			TenantID: tenantID, RunID: runID, ExpectedRunRevision: production.Revision,
			ExpectedCheckpointRevision: checkpoint.Revision,
			ExpectedCheckpointDigest:   checkpoint.CheckpointDigest,
			SimulationApprovalID:       simulationApproval, ProductionApprovalID: productionApproval,
			ProductionEntry: productionEntry, SealedCheckpoint: sealed,
			IdempotencyKey: "seal.production.live.0001", RequestDigest: digestForTest("production-seal-request"),
		},
	}
}

func m3LiveCreateWaitingRun(
	t *testing.T, ctx context.Context, repository *M3PostgresRepository,
	tenantID, runID, plan, label string,
) int64 {
	t.Helper()
	created, err := repository.CreateRun(ctx, M3CreateRunCommand{
		TenantID: tenantID, RunID: runID,
		IdempotencyKey: "create." + label + ".0001", RequestDigest: digestForTest(label + "-create"),
	})
	if err != nil {
		t.Fatal(err)
	}
	running, err := repository.TransitionRun(ctx, M3TransitionCommand{
		TenantID: tenantID, RunID: runID, ExpectedRevision: created.Revision,
		To: M3RunRunning, IdempotencyKey: "running." + label + ".0001",
		RequestDigest: digestForTest(label + "-running"),
	})
	if err != nil {
		t.Fatal(err)
	}
	waiting, err := repository.TransitionRun(ctx, M3TransitionCommand{
		TenantID: tenantID, RunID: runID, ExpectedRevision: running.Revision,
		To: M3RunAwaitingApproval, PlanDigest: plan,
		IdempotencyKey: "waiting." + label + ".0001", RequestDigest: digestForTest(label + "-waiting"),
	})
	if err != nil {
		t.Fatal(err)
	}
	return waiting.Revision
}

func m3LiveJournalEntry(
	tenantID, runID string, stage M3ApprovalStage, approvalID, label,
	authorityRecord, source, subject, predecessor, actor string,
) M3WorkflowApprovalEntry {
	raw, recordDigest := m3LiveCanonical("approval_record", label)
	return M3WorkflowApprovalEntry{
		TenantID: tenantID, RunID: runID, Stage: stage, ApprovalID: approvalID,
		RecordDigest: recordDigest, AuthorityRecordDigest: authorityRecord,
		SourceDigest: source, SubjectDigest: subject, PredecessorDigest: predecessor,
		IdempotencyKey: "journal." + label + ".0001", AuthorityID: "authority_primary",
		ApproverID: actor, CanonicalJSON: raw,
	}
}

func m3LiveSealedCheckpoint(
	current M3WorkflowCheckpoint, label, productionApprovalID string,
) M3WorkflowCheckpoint {
	raw, checkpointDigest := m3LiveCanonical("run_checkpoint", label)
	atSeal := current.ModelCalls
	return M3WorkflowCheckpoint{
		TenantID: current.TenantID, RunID: current.RunID, Revision: current.Revision + 1,
		CheckpointDigest: checkpointDigest, SourceDigest: current.SourceDigest,
		RequestDigest: current.RequestDigest, PlanDigest: current.PlanDigest,
		Phase: "approved_for_execution", Sequence: current.Sequence,
		ChainDigest: digestForTest(label + "-chain"), CanonicalJSON: raw,
		ModelCalls: current.ModelCalls, ModelCallsAtSeal: &atSeal, PostSealModelCalls: 0,
		SealDigest: digestForTest(label + "-seal"), ProductionApprovalID: productionApprovalID,
	}
}

func m3LiveCanonical(kind, label string) (json.RawMessage, string) {
	raw := json.RawMessage(fmt.Sprintf(`{"kind":%q,"label":%q}`, kind, label))
	sum := sha256.Sum256(raw)
	return raw, "sha256:" + hex.EncodeToString(sum[:])
}

func m3LiveAssertCounts(
	t *testing.T, ctx context.Context, db *sql.DB, tenantID, runID string, expected map[string]int,
) {
	t.Helper()
	for table, want := range expected {
		var got int
		query := fmt.Sprintf(`SELECT count(*) FROM mission_control_v2.%s WHERE tenant_id = $1 AND run_id = $2`, table)
		if err := db.QueryRowContext(ctx, query, tenantID, runID).Scan(&got); err != nil {
			t.Fatalf("count %s: %v", table, err)
		}
		if got != want {
			t.Fatalf("%s row count = %d, want %d", table, got, want)
		}
	}
}

func digestForTest(label string) string {
	sum := sha256.Sum256([]byte(label))
	return "sha256:" + hex.EncodeToString(sum[:])
}
