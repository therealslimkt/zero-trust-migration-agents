# Milestone 3 Cloud SQL authority

Status: implemented and locally verified against PostgreSQL 18; not deployed

## Authority decision

PostgreSQL on Cloud SQL is the v2 transactional authority. It owns tenant/run
lifecycle, optimistic revisions, approval nonces and decisions, signed
releases, launch and reconciliation facts, task/attempt history, worker lease
fences, effect reservations, idempotency results, and the durable event
outbox.

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

The migration lives at
`studio-backend/migrations/m3_001_cloud_sql_authority.sql`. The repository is
`studio-backend/m3_persistence.go` and accepts an injected `*sql.DB`; it never
opens a database or reads credentials implicitly.

## Invariants

### Tenant and run scope

- Tenant is the leading column of every authority key and lookup.
- Foreign keys include tenant identity, preventing cross-tenant references.
- Commands require an exact tenant/run scope. SQL never looks up a run by
  `run_id` alone.
- Idempotency records bind tenant, run, deterministic node path, operation,
  request digest, and the plan digest once a plan exists. Pre-plan create and
  start commands store a null plan binding; no post-plan command does.
- `SERIALIZABLE` commands and `FOR UPDATE` locks make revision checks and
  state-machine transitions atomic.

### Approval and release

- An approval nonce is one-time, expiring, and bound to the exact plan digest.
- `RecordApproval` consumes the nonce before inserting the immutable approval
  row, advances the run, appends the event, and commits all four together.
- Approval actor identity is retained only in the authority table; it is not
  copied into Mission Control events.
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
  -run TestM3PostgresContractIntegration -v ./studio-backend
```

It rewrites the migration to a process-unique schema, exercises transaction
rollback, nonce consumption, immutable approval/release/attempt records,
signed release, create-once launch and reconciliation counts, lease fencing,
and unsafe event rejection, then rolls the entire schema back. With no DSN it
skips cleanly so the offline v1 baseline remains green.

This milestone does not claim a Cloud SQL instance, Datastream stream,
Pub/Sub topic, BigQuery projection, or production relay was deployed or live
tested.
