BEGIN;

CREATE SCHEMA IF NOT EXISTS mission_control_v2;
SET LOCAL search_path = mission_control_v2, pg_catalog;

CREATE TABLE runs (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    lifecycle_state varchar(32) NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    plan_digest varchar(71),
    simulation_approval_id varchar(80),
    production_approval_id varchar(80),
    approval_id varchar(80),
    release_id varchar(80),
    next_event_sequence bigint NOT NULL DEFAULT 1 CHECK (next_event_sequence > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id),
    CHECK (tenant_id ~ '^tnt_[a-z0-9][a-z0-9_]{3,59}$'),
    CHECK (run_id ~ '^run_[a-z0-9][a-z0-9_-]{11,59}$'),
    CHECK (lifecycle_state IN (
        'created', 'running', 'awaiting_input', 'awaiting_approval',
        'approved', 'rejected', 'succeeded', 'failed', 'cancelled',
        'budget_exhausted', 'dead_lettered'
    )),
    CHECK (plan_digest IS NULL OR plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (simulation_approval_id IS NULL OR simulation_approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (production_approval_id IS NULL OR production_approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (approval_id IS NULL OR approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (release_id IS NULL OR release_id ~ '^rel_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$')
);

CREATE TABLE approvals (
    tenant_id varchar(80) NOT NULL,
    approval_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    stage varchar(16) NOT NULL,
    request_digest varchar(71) NOT NULL,
    record_digest varchar(71) NOT NULL,
    plan_digest varchar(71) NOT NULL,
    release_digest varchar(71) NOT NULL,
    artifact_digest varchar(71) NOT NULL,
    subject_digest varchar(71) NOT NULL,
    nonce_digest varchar(71) NOT NULL,
    checkpoint_digest varchar(71) NOT NULL,
    simulation_approval_id varchar(80),
    simulation_record_digest varchar(71),
    decision varchar(16) NOT NULL,
    actor_subject varchar(160) NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, approval_id),
    UNIQUE (tenant_id, run_id, stage),
    UNIQUE (tenant_id, run_id, approval_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id, simulation_approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (stage IN ('simulation', 'production')),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (release_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (nonce_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (checkpoint_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (simulation_approval_id IS NULL OR simulation_approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (simulation_record_digest IS NULL OR simulation_record_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((stage = 'simulation' AND simulation_approval_id IS NULL AND simulation_record_digest IS NULL)
        OR (stage = 'production' AND simulation_approval_id IS NOT NULL AND simulation_record_digest IS NOT NULL)),
    CHECK (decision IN ('approve', 'reject')),
    CHECK (length(actor_subject) BETWEEN 3 AND 160),
    CHECK (actor_subject !~ '[[:cntrl:]]')
);

CREATE TABLE approval_nonces (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    request_id varchar(128) NOT NULL,
    stage varchar(16) NOT NULL,
    nonce_digest varchar(71) NOT NULL,
    request_digest varchar(71) NOT NULL,
    plan_digest varchar(71) NOT NULL,
    release_digest varchar(71) NOT NULL,
    artifact_digest varchar(71) NOT NULL,
    subject_digest varchar(71) NOT NULL,
    checkpoint_digest varchar(71) NOT NULL,
    simulation_record_digest varchar(71),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    approval_id varchar(80),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, nonce_digest),
    UNIQUE (tenant_id, request_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK (request_id ~ '^[A-Za-z][A-Za-z0-9_.:-]{2,127}$'),
    CHECK (stage IN ('simulation', 'production')),
    CHECK (nonce_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (release_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (checkpoint_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (simulation_record_digest IS NULL OR simulation_record_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((stage = 'simulation' AND simulation_record_digest IS NULL)
        OR (stage = 'production' AND simulation_record_digest IS NOT NULL)),
    CHECK ((consumed_at IS NULL) = (approval_id IS NULL)),
    CHECK (approval_id IS NULL OR approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    FOREIGN KEY (tenant_id, run_id, approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id)
        DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE runs
    ADD CONSTRAINT runs_simulation_approval_fk
    FOREIGN KEY (tenant_id, run_id, simulation_approval_id)
    REFERENCES approvals (tenant_id, run_id, approval_id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT runs_production_approval_fk
    FOREIGN KEY (tenant_id, run_id, production_approval_id)
    REFERENCES approvals (tenant_id, run_id, approval_id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT runs_approval_fk
    FOREIGN KEY (tenant_id, run_id, approval_id)
    REFERENCES approvals (tenant_id, run_id, approval_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE releases (
    tenant_id varchar(80) NOT NULL,
    release_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    approval_id varchar(80) NOT NULL,
    subject_digest varchar(71) NOT NULL,
    release_kind varchar(40) NOT NULL,
    artifact_digest varchar(71) NOT NULL,
    signer_key_version varchar(160) NOT NULL,
    signature_digest varchar(71) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, release_id),
    UNIQUE (tenant_id, run_id, release_kind),
    UNIQUE (tenant_id, run_id, release_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id, approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id),
    CHECK (release_id ~ '^rel_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (release_kind ~ '^[a-z][a-z0-9_.-]{2,39}$'),
    CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (length(signer_key_version) BETWEEN 8 AND 160 AND signer_key_version !~ '[[:cntrl:]]'),
    CHECK (signature_digest ~ '^sha256:[0-9a-f]{64}$')
);

ALTER TABLE runs
    ADD CONSTRAINT runs_release_fk
    FOREIGN KEY (tenant_id, run_id, release_id)
    REFERENCES releases (tenant_id, run_id, release_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE tasks (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    task_id varchar(80) NOT NULL,
    node_path varchar(256) NOT NULL,
    input_digest varchar(71) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'ready',
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 32),
    attempts_started integer NOT NULL DEFAULT 0 CHECK (attempts_started >= 0),
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner varchar(128),
    lease_token varchar(64),
    lease_generation bigint NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_expires_at timestamptz,
    active_attempt_id varchar(80),
    effect_key varchar(160),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, task_id),
    UNIQUE (tenant_id, run_id, effect_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK (task_id ~ '^tsk_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (node_path ~ '^/[A-Za-z0-9][A-Za-z0-9_./-]{0,254}$'),
    CHECK (input_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (status IN ('ready', 'running', 'succeeded', 'failed', 'dead_lettered', 'cancelled')),
    CHECK (attempts_started <= max_attempts),
    CHECK ((status = 'running') =
        (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND
         lease_expires_at IS NOT NULL AND active_attempt_id IS NOT NULL)),
    CHECK (lease_owner IS NULL OR (length(lease_owner) BETWEEN 3 AND 128 AND lease_owner !~ '[[:cntrl:]]')),
    CHECK (lease_token IS NULL OR lease_token ~ '^[0-9a-f]{32}$'),
    CHECK (active_attempt_id IS NULL OR active_attempt_id ~ '^att_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (effect_key IS NULL OR (length(effect_key) BETWEEN 8 AND 160 AND effect_key !~ '[[:cntrl:]]'))
);

CREATE INDEX tasks_claimable_idx
    ON tasks (tenant_id, run_id, available_at, task_id)
    WHERE status IN ('ready', 'failed', 'running');

CREATE TABLE attempts (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    task_id varchar(80) NOT NULL,
    attempt_id varchar(80) NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    lease_generation bigint NOT NULL CHECK (lease_generation > 0),
    worker_id varchar(128) NOT NULL,
    status varchar(24) NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    output_digest varchar(71),
    failure_code varchar(64),
    PRIMARY KEY (tenant_id, run_id, attempt_id),
    UNIQUE (tenant_id, run_id, task_id, attempt_number),
    UNIQUE (tenant_id, run_id, task_id, attempt_id),
    FOREIGN KEY (tenant_id, run_id, task_id) REFERENCES tasks (tenant_id, run_id, task_id),
    CHECK (attempt_id ~ '^att_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (length(worker_id) BETWEEN 3 AND 128 AND worker_id !~ '[[:cntrl:]]'),
    CHECK (status IN ('running', 'succeeded', 'failed', 'timed_out', 'cancelled')),
    CHECK (output_digest IS NULL OR output_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CHECK ((status = 'running') = (completed_at IS NULL)),
    CHECK (status <> 'succeeded' OR output_digest IS NOT NULL),
    CHECK (status NOT IN ('failed', 'timed_out') OR failure_code IS NOT NULL)
);

ALTER TABLE tasks
    ADD CONSTRAINT tasks_active_attempt_fk
    FOREIGN KEY (tenant_id, run_id, task_id, active_attempt_id)
    REFERENCES attempts (tenant_id, run_id, task_id, attempt_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE effects (
    tenant_id varchar(80) NOT NULL,
    effect_key varchar(160) NOT NULL,
    run_id varchar(80) NOT NULL,
    task_id varchar(80) NOT NULL,
    attempt_id varchar(80) NOT NULL,
    request_digest varchar(71) NOT NULL,
    status varchar(16) NOT NULL,
    result_digest varchar(71),
    reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    committed_at timestamptz,
    PRIMARY KEY (tenant_id, effect_key),
    FOREIGN KEY (tenant_id, run_id, task_id) REFERENCES tasks (tenant_id, run_id, task_id),
    FOREIGN KEY (tenant_id, run_id, task_id, attempt_id)
        REFERENCES attempts (tenant_id, run_id, task_id, attempt_id),
    CHECK (length(effect_key) BETWEEN 8 AND 160 AND effect_key !~ '[[:cntrl:]]'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (status IN ('reserved', 'committed')),
    CHECK (result_digest IS NULL OR result_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((status = 'committed') = (committed_at IS NOT NULL AND result_digest IS NOT NULL))
);

CREATE TABLE idempotency_results (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    node_path varchar(256) NOT NULL,
    plan_digest varchar(71),
    operation varchar(64) NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    request_digest varchar(71) NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, node_path, operation, idempotency_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK (node_path ~ '^/[A-Za-z0-9][A-Za-z0-9_./-]{0,254}$'),
    CHECK (plan_digest IS NULL OR plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (operation ~ '^[a-z][a-z0-9_.-]{2,63}$'),
    CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(response_json) = 'object'),
    CHECK (octet_length(response_json::text) <= 16384)
);

CREATE INDEX idempotency_lookup_idx
    ON idempotency_results (tenant_id, operation, idempotency_key);

CREATE TABLE workflow_checkpoints (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0),
    checkpoint_digest varchar(71) NOT NULL,
    source_digest varchar(71) NOT NULL,
    request_digest varchar(71) NOT NULL,
    plan_digest varchar(71) NOT NULL,
    phase varchar(32) NOT NULL,
    sequence bigint NOT NULL CHECK (sequence >= 0),
    chain_digest varchar(71) NOT NULL,
    canonical_json text NOT NULL,
    model_calls integer NOT NULL CHECK (model_calls >= 0),
    model_calls_at_seal integer,
    post_seal_model_calls integer NOT NULL DEFAULT 0 CHECK (post_seal_model_calls = 0),
    seal_digest varchar(71),
    production_approval_id varchar(80),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id),
    UNIQUE (tenant_id, checkpoint_digest),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id, production_approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (checkpoint_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (chain_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (phase IN (
        'planned', 'validated', 'policy_decided', 'verified',
        'simulation_approved', 'approved_for_execution',
        'dispatched', 'reconciled', 'certified'
    )),
    CHECK (jsonb_typeof(canonical_json::jsonb) = 'object'),
    CHECK (octet_length(canonical_json) <= 262144),
    CHECK (model_calls_at_seal IS NULL OR model_calls_at_seal = model_calls),
    CHECK (seal_digest IS NULL OR seal_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (production_approval_id IS NULL OR production_approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK ((phase IN ('approved_for_execution', 'dispatched', 'reconciled', 'certified'))
        = (seal_digest IS NOT NULL AND model_calls_at_seal IS NOT NULL AND production_approval_id IS NOT NULL))
);

CREATE TABLE workflow_approval_entries (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    stage varchar(16) NOT NULL,
    approval_id varchar(80) NOT NULL,
    record_digest varchar(71) NOT NULL,
    authority_record_digest varchar(71) NOT NULL,
    source_digest varchar(71) NOT NULL,
    subject_digest varchar(71) NOT NULL,
    predecessor_digest varchar(71) NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    authority_id varchar(128) NOT NULL,
    approver_id varchar(128) NOT NULL,
    canonical_json text NOT NULL,
    appended_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, stage),
    UNIQUE (tenant_id, run_id, record_digest),
    UNIQUE (tenant_id, run_id, idempotency_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id, approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id),
    CHECK (stage IN ('simulation', 'production')),
    CHECK (approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (authority_record_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (predecessor_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'),
    CHECK (length(authority_id) BETWEEN 3 AND 128 AND authority_id !~ '[[:cntrl:]]'),
    CHECK (length(approver_id) BETWEEN 3 AND 128 AND approver_id !~ '[[:cntrl:]]'),
    CHECK (jsonb_typeof(canonical_json::jsonb) = 'object'),
    CHECK (octet_length(canonical_json) <= 65536)
);

CREATE TABLE launch_results (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    launch_key varchar(160) NOT NULL,
    release_id varchar(80) NOT NULL,
    request_digest varchar(71) NOT NULL,
    status varchar(16) NOT NULL,
    operation_ref varchar(160) NOT NULL,
    result_digest varchar(71) NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, launch_key),
    UNIQUE (tenant_id, run_id, release_id),
    FOREIGN KEY (tenant_id, run_id, release_id)
        REFERENCES releases (tenant_id, run_id, release_id),
    CHECK (length(launch_key) BETWEEN 8 AND 160 AND launch_key !~ '[[:cntrl:]]'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (status IN ('launched', 'failed')),
    CHECK (length(operation_ref) BETWEEN 3 AND 160 AND operation_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$'),
    CHECK (result_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE reconciliation_results (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    reconciliation_id varchar(80) NOT NULL,
    release_id varchar(80) NOT NULL,
    launch_key varchar(160) NOT NULL,
    outcome varchar(16) NOT NULL,
    result_digest varchar(71) NOT NULL,
    evidence_digest varchar(71) NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, reconciliation_id),
    UNIQUE (tenant_id, run_id, release_id),
    FOREIGN KEY (tenant_id, run_id, launch_key) REFERENCES launch_results (tenant_id, run_id, launch_key),
    FOREIGN KEY (tenant_id, run_id, release_id)
        REFERENCES releases (tenant_id, run_id, release_id),
    CHECK (reconciliation_id ~ '^rec_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (outcome IN ('verified', 'failed')),
    CHECK (result_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE FUNCTION evidence_refs_are_safe(refs varchar[]) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    ref varchar;
BEGIN
    FOREACH ref IN ARRAY refs LOOP
        IF ref !~ '^(sha256:[0-9a-f]{64}|art_[A-Za-z0-9][A-Za-z0-9._-]{7,63})$' THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

CREATE TABLE events (
    tenant_id varchar(80) NOT NULL,
    run_id varchar(80) NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_id varchar(80) NOT NULL,
    event_type varchar(64) NOT NULL,
    run_revision bigint NOT NULL CHECK (run_revision > 0),
    run_state varchar(32) NOT NULL,
    task_id varchar(80),
    attempt_id varchar(80),
    approval_id varchar(80),
    release_id varchar(80),
    code varchar(64),
    evidence_refs varchar(80)[] NOT NULL DEFAULT '{}',
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    delivery_status varchar(24) NOT NULL DEFAULT 'pending',
    delivery_attempts integer NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
    max_delivery_attempts integer NOT NULL DEFAULT 10 CHECK (max_delivery_attempts BETWEEN 1 AND 32),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    delivery_owner varchar(128),
    delivery_token varchar(64),
    delivery_generation bigint NOT NULL DEFAULT 0 CHECK (delivery_generation >= 0),
    delivery_expires_at timestamptz,
    published_at timestamptz,
    dead_lettered_at timestamptz,
    last_error_code varchar(64),
    PRIMARY KEY (tenant_id, run_id, sequence),
    UNIQUE (tenant_id, event_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id, task_id)
        REFERENCES tasks (tenant_id, run_id, task_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tenant_id, run_id, task_id, attempt_id)
        REFERENCES attempts (tenant_id, run_id, task_id, attempt_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tenant_id, run_id, approval_id)
        REFERENCES approvals (tenant_id, run_id, approval_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tenant_id, run_id, release_id)
        REFERENCES releases (tenant_id, run_id, release_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (event_id ~ '^evt_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (event_type IN (
        'run.created', 'run.transitioned', 'approval.recorded', 'checkpoint.sealed',
        'release.created', 'launch.recorded', 'reconciliation.recorded',
        'task.enqueued', 'attempt.started',
        'attempt.completed', 'lease.expired', 'task.retry_scheduled',
        'task.dead_lettered', 'effect.reserved', 'effect.committed'
    )),
    CHECK (run_state IN (
        'created', 'running', 'awaiting_input', 'awaiting_approval',
        'approved', 'rejected', 'succeeded', 'failed', 'cancelled',
        'budget_exhausted', 'dead_lettered'
    )),
    CHECK (task_id IS NULL OR task_id ~ '^tsk_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (attempt_id IS NULL OR attempt_id ~ '^att_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (approval_id IS NULL OR approval_id ~ '^apr_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (release_id IS NULL OR release_id ~ '^rel_[A-Za-z0-9][A-Za-z0-9._-]{7,63}$'),
    CHECK (code IS NULL OR code ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CHECK (cardinality(evidence_refs) <= 32),
    CHECK (evidence_refs_are_safe(evidence_refs)),
    CHECK (delivery_status IN ('pending', 'in_flight', 'published', 'dead_lettered')),
    CHECK ((delivery_status = 'in_flight') =
        (delivery_owner IS NOT NULL AND delivery_token IS NOT NULL AND delivery_expires_at IS NOT NULL)),
    CHECK (delivery_owner IS NULL OR (length(delivery_owner) BETWEEN 3 AND 128 AND delivery_owner !~ '[[:cntrl:]]')),
    CHECK (delivery_token IS NULL OR delivery_token ~ '^[0-9a-f]{32}$'),
    CHECK (last_error_code IS NULL OR last_error_code ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CHECK ((delivery_status = 'published') = (published_at IS NOT NULL)),
    CHECK ((delivery_status = 'dead_lettered') = (dead_lettered_at IS NOT NULL))
);

CREATE INDEX events_replay_idx ON events (tenant_id, run_id, sequence);
CREATE INDEX events_outbox_claim_idx
    ON events (available_at, tenant_id, run_id, sequence)
    WHERE delivery_status IN ('pending', 'in_flight');

CREATE FUNCTION reject_all_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION guard_attempt_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.task_id IS DISTINCT FROM NEW.task_id
       OR OLD.attempt_id IS DISTINCT FROM NEW.attempt_id
       OR OLD.attempt_number IS DISTINCT FROM NEW.attempt_number
       OR OLD.lease_generation IS DISTINCT FROM NEW.lease_generation
       OR OLD.worker_id IS DISTINCT FROM NEW.worker_id
       OR OLD.started_at IS DISTINCT FROM NEW.started_at THEN
        RAISE EXCEPTION 'attempt identity/history is immutable' USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'terminal attempt is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_event_projection() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(
        OLD.tenant_id, OLD.run_id, OLD.sequence, OLD.event_id, OLD.event_type,
        OLD.run_revision, OLD.run_state, OLD.task_id, OLD.attempt_id, OLD.approval_id,
        OLD.release_id, OLD.code, OLD.evidence_refs, OLD.occurred_at
    ) IS DISTINCT FROM ROW(
        NEW.tenant_id, NEW.run_id, NEW.sequence, NEW.event_id, NEW.event_type,
        NEW.run_revision, NEW.run_state, NEW.task_id, NEW.attempt_id, NEW.approval_id,
        NEW.release_id, NEW.code, NEW.evidence_refs, NEW.occurred_at
    ) THEN
        RAISE EXCEPTION 'event projection is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_event_sequence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_sequence bigint;
BEGIN
    SELECT next_event_sequence - 1 INTO expected_sequence
    FROM mission_control_v2.runs
    WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id;
    IF expected_sequence IS NULL OR NEW.sequence <> expected_sequence THEN
        RAISE EXCEPTION 'event sequence must be allocated by the locked run row'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_effect_ledger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.effect_key IS DISTINCT FROM NEW.effect_key
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.task_id IS DISTINCT FROM NEW.task_id
       OR OLD.attempt_id IS DISTINCT FROM NEW.attempt_id
       OR OLD.request_digest IS DISTINCT FROM NEW.request_digest
       OR OLD.reserved_at IS DISTINCT FROM NEW.reserved_at THEN
        RAISE EXCEPTION 'effect reservation identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'committed' THEN
        RAISE EXCEPTION 'committed effect is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_approval_nonce() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.request_id IS DISTINCT FROM NEW.request_id
       OR OLD.stage IS DISTINCT FROM NEW.stage
       OR OLD.nonce_digest IS DISTINCT FROM NEW.nonce_digest
       OR OLD.request_digest IS DISTINCT FROM NEW.request_digest
       OR OLD.plan_digest IS DISTINCT FROM NEW.plan_digest
       OR OLD.release_digest IS DISTINCT FROM NEW.release_digest
       OR OLD.artifact_digest IS DISTINCT FROM NEW.artifact_digest
       OR OLD.subject_digest IS DISTINCT FROM NEW.subject_digest
       OR OLD.checkpoint_digest IS DISTINCT FROM NEW.checkpoint_digest
       OR OLD.simulation_record_digest IS DISTINCT FROM NEW.simulation_record_digest
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'approval nonce identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF OLD.consumed_at IS NOT NULL THEN
        RAISE EXCEPTION 'consumed approval nonce is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.consumed_at IS NULL OR NEW.approval_id IS NULL THEN
        RAISE EXCEPTION 'approval nonce can only transition to consumed' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_staged_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    prior_stage varchar;
    prior_decision varchar;
    prior_record_digest varchar;
    prior_subject_digest varchar;
BEGIN
    IF NEW.stage = 'production' THEN
        SELECT stage, decision, record_digest, subject_digest
        INTO prior_stage, prior_decision, prior_record_digest, prior_subject_digest
        FROM mission_control_v2.approvals
        WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
          AND approval_id = NEW.simulation_approval_id;
        IF prior_stage IS DISTINCT FROM 'simulation'
           OR prior_decision IS DISTINCT FROM 'approve'
           OR prior_record_digest IS DISTINCT FROM NEW.simulation_record_digest
           OR prior_record_digest IS NOT DISTINCT FROM NEW.record_digest
           OR prior_subject_digest IS NOT DISTINCT FROM NEW.subject_digest THEN
            RAISE EXCEPTION 'production approval requires a distinct approved simulation decision'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_release_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    approval_valid boolean;
BEGIN
    SELECT stage = 'production' AND decision = 'approve'
    INTO approval_valid
    FROM mission_control_v2.approvals
    WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
      AND approval_id = NEW.approval_id;
    IF approval_valid IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'release requires an approved production decision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION workflow_phase_rank(phase_value varchar) RETURNS integer
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT CASE phase_value
        WHEN 'planned' THEN 1 WHEN 'validated' THEN 2
        WHEN 'policy_decided' THEN 3 WHEN 'verified' THEN 4
        WHEN 'simulation_approved' THEN 5 WHEN 'approved_for_execution' THEN 6
        WHEN 'dispatched' THEN 7 WHEN 'reconciled' THEN 8
        WHEN 'certified' THEN 9 ELSE 0 END
$$;

CREATE FUNCTION guard_workflow_checkpoint() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.source_digest IS DISTINCT FROM NEW.source_digest
       OR OLD.request_digest IS DISTINCT FROM NEW.request_digest
       OR OLD.plan_digest IS DISTINCT FROM NEW.plan_digest
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'workflow checkpoint identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.revision <> OLD.revision + 1
       OR NEW.sequence < OLD.sequence
       OR mission_control_v2.workflow_phase_rank(NEW.phase) < mission_control_v2.workflow_phase_rank(OLD.phase) THEN
        RAISE EXCEPTION 'workflow checkpoint CAS is not monotonic' USING ERRCODE = '40001';
    END IF;
    IF OLD.seal_digest IS NOT NULL AND (
        NEW.seal_digest IS DISTINCT FROM OLD.seal_digest
        OR NEW.production_approval_id IS DISTINCT FROM OLD.production_approval_id
        OR NEW.model_calls IS DISTINCT FROM OLD.model_calls
        OR NEW.model_calls_at_seal IS DISTINCT FROM OLD.model_calls_at_seal
    ) THEN
        RAISE EXCEPTION 'sealed workflow checkpoint is immutable at the production boundary'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_workflow_checkpoint_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF mission_control_v2.workflow_phase_rank(NEW.phase) >=
       mission_control_v2.workflow_phase_rank('approved_for_execution') THEN
        RAISE EXCEPTION 'workflow checkpoint must be created before the production boundary'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION guard_workflow_approval_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    approval_valid boolean;
BEGIN
    SELECT stage = NEW.stage AND decision = 'approve'
           AND actor_subject = NEW.approver_id
           AND record_digest = NEW.authority_record_digest
           AND subject_digest = NEW.subject_digest
    INTO approval_valid
    FROM mission_control_v2.approvals
    WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
      AND approval_id = NEW.approval_id;
    IF approval_valid IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'workflow approval entry does not match its authority decision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER approvals_guard_insert BEFORE INSERT ON approvals
    FOR EACH ROW EXECUTE FUNCTION guard_staged_approval();
CREATE TRIGGER approvals_no_update BEFORE UPDATE OR DELETE ON approvals
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER approval_nonces_no_delete BEFORE DELETE ON approval_nonces
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER approval_nonces_guard_update BEFORE UPDATE ON approval_nonces
    FOR EACH ROW EXECUTE FUNCTION guard_approval_nonce();
CREATE TRIGGER releases_no_update BEFORE UPDATE OR DELETE ON releases
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER releases_guard_insert BEFORE INSERT ON releases
    FOR EACH ROW EXECUTE FUNCTION guard_release_approval();
CREATE TRIGGER launch_results_no_update BEFORE UPDATE OR DELETE ON launch_results
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER reconciliation_results_no_update BEFORE UPDATE OR DELETE ON reconciliation_results
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER idempotency_no_update BEFORE UPDATE OR DELETE ON idempotency_results
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER workflow_checkpoints_guard_update BEFORE UPDATE ON workflow_checkpoints
    FOR EACH ROW EXECUTE FUNCTION guard_workflow_checkpoint();
CREATE TRIGGER workflow_checkpoints_guard_insert BEFORE INSERT ON workflow_checkpoints
    FOR EACH ROW EXECUTE FUNCTION guard_workflow_checkpoint_insert();
CREATE TRIGGER workflow_checkpoints_no_delete BEFORE DELETE ON workflow_checkpoints
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER workflow_approval_entries_guard_insert BEFORE INSERT ON workflow_approval_entries
    FOR EACH ROW EXECUTE FUNCTION guard_workflow_approval_entry();
CREATE TRIGGER workflow_approval_entries_no_update BEFORE UPDATE OR DELETE ON workflow_approval_entries
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER effects_guard_update BEFORE UPDATE ON effects
    FOR EACH ROW EXECUTE FUNCTION guard_effect_ledger();
CREATE TRIGGER effects_no_delete BEFORE DELETE ON effects
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER attempts_guard_update BEFORE UPDATE ON attempts
    FOR EACH ROW EXECUTE FUNCTION guard_attempt_history();
CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();
CREATE TRIGGER events_guard_update BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION guard_event_projection();
CREATE TRIGGER events_guard_insert BEFORE INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION guard_event_sequence();
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION reject_all_mutation();

COMMIT;
