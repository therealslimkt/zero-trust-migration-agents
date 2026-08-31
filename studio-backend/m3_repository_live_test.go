package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestM3PostgresRepositoryLive executes real database/sql repository methods.
// It is opt-in because the offline v1 gate must not require PostgreSQL. The
// database-name guard prevents this test from resetting a non-test database.
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

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	var databaseName string
	if err := db.QueryRowContext(ctx, `SELECT current_database()`).Scan(&databaseName); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(databaseName, "zero_trust_m3_test") {
		t.Fatalf("refusing live repository test against non-M3 test database %q", databaseName)
	}

	// The dedicated database is disposable. Resetting the product schema makes
	// repeated runs deterministic without weakening immutable-row triggers.
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
	const (
		tenantID    = "tnt_LIVEREPO01"
		runID       = "run_LIVEREPO0001"
		planDigest  = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		nonceDigest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	)

	created, err := repository.CreateRun(ctx, M3CreateRunCommand{
		TenantID: tenantID, RunID: runID,
		IdempotencyKey: "live-run-create-01", RequestDigest: digestForTest("create"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if created.State != M3RunCreated || created.Revision != 1 || created.EventSequence != 1 {
		t.Fatalf("unexpected create result: %#v", created)
	}
	replayed, err := repository.CreateRun(ctx, M3CreateRunCommand{
		TenantID: tenantID, RunID: runID,
		IdempotencyKey: "live-run-create-01", RequestDigest: digestForTest("create"),
	})
	if err != nil || !replayed.Replayed || replayed.EventSequence != created.EventSequence {
		t.Fatalf("create replay was not stable: result=%#v err=%v", replayed, err)
	}

	running, err := repository.TransitionRun(ctx, M3TransitionCommand{
		TenantID: tenantID, RunID: runID, ExpectedRevision: created.Revision,
		To: M3RunRunning, IdempotencyKey: "live-run-running-01", RequestDigest: digestForTest("running"),
	})
	if err != nil {
		t.Fatal(err)
	}
	waiting, err := repository.TransitionRun(ctx, M3TransitionCommand{
		TenantID: tenantID, RunID: runID, ExpectedRevision: running.Revision,
		To: M3RunAwaitingApproval, PlanDigest: planDigest,
		IdempotencyKey: "live-run-approval-01", RequestDigest: digestForTest("waiting"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := repository.RegisterApprovalNonce(ctx, M3ApprovalNonceCommand{
		TenantID: tenantID, RunID: runID, SubjectDigest: planDigest,
		NonceDigest: nonceDigest, ExpiresAt: time.Now().UTC().Add(time.Minute),
	}); err != nil {
		t.Fatal(err)
	}
	approved, err := repository.RecordApproval(ctx, M3ApprovalCommand{
		TenantID: tenantID, RunID: runID, ApprovalID: "apr_LIVEREPO0001",
		SubjectDigest: planDigest, NonceDigest: nonceDigest, Decision: "approved",
		ActorSubject: "actor_live_test", ExpectedRevision: waiting.Revision,
		IdempotencyKey: "live-approval-record-01", RequestDigest: digestForTest("approved"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if approved.State != M3RunApproved || approved.Revision != 4 || approved.EventSequence != 4 {
		t.Fatalf("unexpected approval result: %#v", approved)
	}

	events, err := repository.ReplayEvents(ctx, tenantID, runID, 0, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 4 {
		t.Fatalf("expected four committed events, got %d", len(events))
	}
	for index, event := range events {
		if event.Sequence != int64(index+1) {
			t.Fatalf("non-contiguous sequence at index %d: %#v", index, event)
		}
	}
}

func digestForTest(label string) string {
	sum := sha256.Sum256([]byte(label))
	return "sha256:" + hex.EncodeToString(sum[:])
}
