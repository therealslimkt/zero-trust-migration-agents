# Milestone 3 Cloud SQL authority

Status: implemented and locally verified against PostgreSQL 18; not deployed

## Authority decision

PostgreSQL on Cloud SQL is the v2 transactional authority. It owns tenant/run
lifecycle, optimistic revisions, approval nonces and decisions, signed
releases, trust-spine checkpoints and approval journal entries, launch and
reconciliation facts, task/attempt history, worker lease fences, effect
reservations, idempotency results, and the durable event outbox.

Firestore and ADK Session Service may retain compatibility/session views, but
they are not v2 approval, release, lease, idempotency, or lifecycle authority.
On disagreement, the PostgreSQL record wins and execution fails closed.

BigQuery is a downstream analytics and audit projection. The expected cloud
path is Cloud SQL PostgreSQL change data capture through Datastream, or a
sanitized outbox consumer through Pub/Sub/Dataflow, into partitioned BigQuery
tables. BigQuery must never be read to decide a lifecycle transition, validate
an approval, fence a worker, or authorize a release.

## Transaction shape

Every authoritative command follows this trace:

```text
BEGIN
  -> acquire tenant/run/idempotency or row lock
  -> validate expected revision, approval/release binding, or lease fence
  -> mutate authoritative state / append or finish attempt
  -> allocate the next sequence from the locked run row
  -> append one sanitized outbox event
  -> store the typed idempotency result when applicable
COMMIT
```

Any failure rolls back state, event sequence allocation, outbox row, and
idempotency record together. A relay crash after commit is recovered by
reclaiming the outbox delivery lease; it does not reconstruct an event from
current state.

The production approval boundary is one `SERIALIZABLE`
`CommitProductionApprovalSeal` transaction. It locks the run and checkpoint,
compares the exact expected run revision plus checkpoint revision and digest,
requires the unsealed `simulation_approved` phase, validates distinct approved
simulation and production authority rows and the simulation journal entry,
then appends the production journal entry, seals the checkpoint, advances the
run, appends `checkpoint.sealed`, and stores the idempotency result before
commit. A duplicate request with the same complete binding returns that result
without another journal row, revision, or event.

The migration lives at
`studio-backend/migrations/m3_001_cloud_sql_authority.sql`. The repository is
`studio-backend/m3_persistence.go` and accepts an injected `*sql.DB`; it never
opens a database or reads credentials implicitly.

## Invariants

### Tenant and run scope

- Tenant is the leading column of every authority key and lookup.
- Foreign keys include tenant identity, preventing cross-tenant references.
- The shared identifier domain is lowercase `tnt_...` (8--64 characters,
  letters/digits/underscore) and `run_...` (16--64 characters,
  letters/digits/underscore/hyphen). Commands require that exact tenant/run
  scope; SQL never looks up a run by `run_id` alone.
- Idempotency records bind tenant, run, deterministic node path, operation,
  request digest, and the plan digest once a plan exists. Pre-plan create and
  start commands store a null plan binding; no post-plan command does.
- `SERIALIZABLE` commands and `FOR UPDATE` locks make revision checks and
  state-machine transitions atomic.

### Approval, checkpoint, and release

- Simulation and production authority decisions are separate immutable rows,
  unique by tenant/run/stage. Both bind request, record, plan, release,
  artifact, subject, nonce, and checkpoint digests. A production row also
  binds the exact prior simulation approval ID and record digest; a trigger
  requires that prior row to be an approved simulation decision with distinct
  record and subject digests.
- An approval nonce is one-time and expiring. It binds all decision inputs,
  not just a plan. Its primary key is `(tenant_id, nonce_digest)`, so a digest
  is usable once across every run in one tenant. The same digest may exist in
  another tenant; this is deliberate tenant-global, not cross-tenant-global,
  replay scope.
- `RecordApproval` consumes the exact staged nonce before inserting the
  immutable authority row, retains the run in `awaiting_approval` after an
  approval, appends the sanitized event, and commits all mutations together.
  Only the atomic production seal moves the run to `approved`.
- `workflow_approval_entries` stores the canonical trust-spine approval facts
  separately from authenticated authority decisions and binds each journal
  record to its authority record digest. `workflow_checkpoints` stores exact
  canonical bytes plus their digest and a monotonic revision. A checkpoint
  cannot be created already sealed.
- At `approved_for_execution`, `model_calls_at_seal` must equal
  `model_calls`, and `post_seal_model_calls` is structurally pinned to zero.
  Later checkpoint updates cannot change that frozen model-call boundary.
- Approval identity is retained in the authority row and typed workflow
  journal fact; it is never copied into Mission Control events.
- A release requires the approved decision, exact plan digest, content digest,
  signer key-version reference, and signature digest. Release rows are
  append-only.
- A launch result is create-once by stable `launch_key`. Repeating identical
  facts returns the original record; contradictory reuse fails.
- Reconciliation requires a persisted successful launch. A run cannot become
  `succeeded` without a verified reconciliation bound to its release.

### Leases, attempts, retry, and effects

- Lease authority is the tuple `(tenant, run, task, attempt, owner, token,
  generation, unexpired database timestamp)`.
- Heartbeat, completion, and effect reservation include the entire tuple and
  reject stale owners, tokens, generations, and expiry.
- The database clock decides expiry. The evaluator claims expired tasks with
  row locks, terminalizes the old attempt, and either schedules a bounded
  retry or visibly dead-letters the task in the same transaction.
- Attempt identity fields never change. Once an attempt is terminal, a trigger
  rejects every later update or deletion.
- The effect ledger has a tenant-leading create-once key. Local reservation
  prevents a second worker from issuing the same effect. The same stable key
  must also be sent to the downstream API: no database can promise exactly-once
  behavior across an external system that lacks idempotency/reconciliation.

### Ordered sanitized events

- Event sequence is allocated by incrementing `runs.next_event_sequence` while
  the run row is locked. A trigger rejects inserts that did not use that
  allocation, so each run is contiguous.
- Replay is scoped by tenant/run and ordered only by sequence, making Mission
  Control reconstruction deterministic even when timestamps tie.
- Event projection columns are immutable. Delivery metadata is mutable only
  under an owner/token/generation/expiry fence.
- Events contain a closed event type, state, IDs, machine code, and at most 32
  digest/artifact references. They have no arbitrary JSON payload, summary,
  prompt, actor, row, raw data, error detail, credential, or reasoning field.
- The relay exposes only the first unpublished event for a run. A dead-lettered
  event blocks later publication for that run rather than creating a visible
  gap. Database replay remains available for repair.

## Recovery cases

| Crash point | Durable result | Recovery |
| --- | --- | --- |
| Before transaction commit | No state, event, nonce consumption, or result survives | Retry the same command |
| Authority decision committed before workflow resume | The staged authority row and consumed nonce survive; no seal is implied | Re-read the row and retry the exact journal/checkpoint command |
| Production journal insert or checkpoint update fails | The journal insert, checkpoint, run, event, and idempotency result all roll back | Retry `CommitProductionApprovalSeal` with the same binding |
| Production seal committed before relay | Sealed checkpoint, approved run, replay result, and pending sanitized event survive together | Return exact replay result; relay claims the pending event |
| After commit, before relay | State and pending event both survive | Relay reclaims event lease |
| After downstream publish, before acknowledgement | Event remains reclaimable with the same stable `event_id` | Subscriber deduplicates `event_id`; relay marks published |
| Worker stops heartbeating | Running attempt remains until database expiry | Evaluator records `timed_out`, then retry or DLQ |
| Launch response is lost | Create-once launch/effect key remains authoritative | Read/reconcile downstream using the same key |
| Reconciliation fails | Launch evidence is retained; run cannot succeed | Record failed reconciliation and fail closed |

## Cloud integration seam

The repository intentionally depends only on `database/sql`, so the service
composition layer must supply a PostgreSQL driver and an already configured
pool. The intended shared-module integration is the pgx standard-library
adapter (`github.com/jackc/pgx/v5/stdlib`) with `sql.Open("pgx", dsn)`, plus the
approved Cloud SQL connection method (private IP or the Cloud SQL Go Connector)
and workload identity. Pool lifetime, IAM authentication refresh, TLS, query
timeouts, and migration execution belong to deployment composition, not this
repository file.

Do not grant the application role schema-owner permissions. Use a migration
role for DDL and a runtime role restricted to the required tables/sequences.
Datastream/CDC gets a separate read/replication identity. Outbox consumers get
only event delivery-update rights, not lifecycle mutation rights.

## Verification boundary

Offline Go tests validate state transitions, input/event sanitization, critical
write ordering, and the migration contract. The PostgreSQL test is opt-in:

```sh
M3_TEST_DATABASE_DSN=postgresql:///zero_trust_m3_test go test \
  -run 'TestM3Postgres(ContractIntegration|RepositoryLive)' -v ./studio-backend
```

The SQL contract test rewrites the migration to a process-unique schema and
rolls the transaction back. The pgx repository test resets only a database
whose name begins `zero_trust_m3_test`, then proves seal success, exact replay,
stale-CAS rollback, missing/mismatched simulation rejection, injected failure
rollback, tenant-global nonce uniqueness, and exact authority/journal/event/
idempotency row counts. With no DSN both tests skip cleanly, so the offline v1
baseline remains green.

This milestone does not claim a Cloud SQL instance, Datastream stream,
Pub/Sub topic, BigQuery projection, or production relay was deployed or live
tested.

The M6 [cloud readiness record](../../cloud_architecture/M6_CLOUD_READINESS.md)
selects a planned sanitized Pub/Sub outbox relay and records the required
resource-scoped IAM and pre-live evidence. It does not alter this authority
boundary or claim that any named Cloud SQL, KMS, Pub/Sub, BigQuery, VPC Service
Controls, or Model Armor resource exists.
