# Enterprise Fleet Milestone 3 delivery report

Status: **complete, merged, and ready for user review**

Milestone 3 delivers the local, deterministic trust and execution spine that
sits after the Milestone 2 planning graph. It preserves v1, keeps the frozen
three-path v2 orchestration contract unchanged, and proves its transactional
authority against a dedicated local PostgreSQL 18 database. It does not claim
that Google Cloud resources were deployed.

## What was delivered

### 1. Fixed deterministic security and execution graph

`agent_runtime/trust_spine/` implements a separate post-plan graph:

```text
Prisma validate -> bounded Prisma repair -> deterministic policy -> Vale
-> simulation approval -> production approval/seal
-> Flow dispatch -> Ledger reconciliation -> Forge certification
```

Predictable work is implemented as function nodes. The only model-capable
node is the bounded pre-approval Prisma repair boundary. Flow accepts a
registered template identity and typed parameters; no model or caller can
supply shell, SQL, source code, module, image, path, URL, or executable handle.
Ledger independently reconciles the dispatched effect. Forge re-walks the
digest chain before it can request certification.

Example: changing a plan, proposal, policy verdict, simulation decision, or
production decision changes the sealed bundle digest and therefore changes
the effect idempotency key. Replaying an old approval cannot authorize the new
bundle.

The M2-to-M3 join is now concrete and typed. A `ReadyFrozenPlan` must match a
completed, non-resumable M2 snapshot and its exact plan digest before
`TrustSpineCoordinator` accepts it. `ResumeInput`, A2A documents, mutable maps,
and bare unjoined plans fail closed.

### 2. Authenticated, two-stage approval boundary

`agent_runtime/approval/` and the Go M3 approval surface implement separate
simulation and production request types, decision vocabularies, handlers, and
bindings. A production decision requires the exact approved simulation record
and binds tenant, run, plan, release, artifact, interrupt, checkpoint, nonce,
expiry, audience, and quorum.

The Go composition derives the actor only from the existing
`WebIdentityVerifier` bearer-token path and then applies a mandatory
server-side stage-role policy. Request bodies cannot select an actor or
tenant. Tenant and run identifiers share the strict lowercase persistence
domain and are never lowercased, prefixed, truncated, or otherwise repaired.

The composable mux preserves both frozen v1 approval bodies. It adds no
approval path to the exactly-three-path v2 orchestration contract. When the v2
input path addresses a simulation or production approval interrupt, it returns
HTTP 403 with `APPROVAL_NOT_RESUMABLE_VIA_INPUT` before generic resume code can
read the body. Tests show that forged resume and A2A approval claims produce
zero approval mutations.

### 3. PostgreSQL transactional authority

`studio-backend/migrations/m3_001_cloud_sql_authority.sql` and
`M3PostgresRepository` provide the local proof for the intended Cloud SQL for
PostgreSQL authority. Tenant-leading tables cover runs, staged decisions,
one-time nonces, workflow checkpoints, workflow approval journal entries,
leases, attempts, tasks, effects, releases, launch and reconciliation facts,
idempotency results, sanitized events, and the transactional outbox.

Simulation and production are distinct immutable rows under
`UNIQUE (tenant_id, run_id, stage)`. Production carries the prior simulation
approval and record digests. Nonces are unique by
`(tenant_id, nonce_digest)`, making them one-time per tenant.

The central production boundary is
`CommitProductionApprovalSeal`. In one serializable transaction it:

1. takes an advisory lock and checks exact idempotent replay;
2. locks the run and checkpoint;
3. compares the expected run revision and complete checkpoint digest;
4. verifies the unsealed `simulation_approved` phase;
5. re-reads and matches both authority decisions and the simulation journal;
6. inserts the production workflow approval entry;
7. seals the checkpoint and freezes `model_calls_at_seal`;
8. advances the authoritative run to `approved`;
9. appends the sanitized contiguous `checkpoint.sealed` outbox event;
10. stores the idempotency result and commits.

A stale checkpoint, missing or mismatched simulation, reused nonce, injected
checkpoint-update failure, or conflicting replay rolls the whole transaction
back. Exact replay returns the original result and appends no duplicate row or
event.

The repository also supplies fenced leases and heartbeats, bounded retry and
dead-letter behavior, immutable terminal attempts, effect reservation and
commit deduplication, ordered per-run replay, and leased outbox delivery.
Events deliberately contain only bounded identifiers, digests, codes, and
evidence references—not prompts, raw rows, credentials, or free-text payloads.

### 4. Structural zero-model boundary

Production approval and checkpoint sealing are one atomic boundary. The
sealed checkpoint fixes `model_calls_at_seal`; PostgreSQL constrains
`post_seal_model_calls` to zero. The post-seal `SealedExecution` object has no
Prisma/model adapter and is checked recursively for public, private, direct,
and nested model-capable or callable surfaces.

On restart, the runtime reads the immutable sealed bundle and revalidates both
persisted approval records, their stages, decisions, subjects, predecessor
chain, authority identities, and idempotency bindings. It does not call an
approval model or accept human text again. Persisted post-seal records must
all have `model_call_delta == 0`.

### 5. Crash recovery, idempotency, and deterministic replay

Every externally observable node records intent before invoking its port and
uses a stable key bound to tenant, run, node, full plan digest, proposal,
seal, and input. A crash after an effect but before result persistence invokes
the port again under the identical key; the port must return the original
effect rather than launch another.

The Python crash suite interrupts every node/checkpoint boundary and proves
Flow, Ledger, and Forge each produce one effect. PostgreSQL failure injection
proves that an error after the production journal insert leaves no journal,
seal, run transition, idempotency result, or outbox event behind. Event replay
is ordered by a contiguous per-run sequence rather than wall-clock time.

The telemetry bridge now emits the closed route object required by v2,
attributes deterministic components to `mission_control`, records their
implementation IDs, and marks approval-required events correctly. PostgreSQL
remains the sequence authority at the production adapter boundary.

## Agentic execution pattern and model use

The build used a fixed parallel graph followed by an adversarial
evaluator/optimizer and deterministic integration join:

- Approval/Security Engineer — Claude Opus 5, max: approval kernels, handlers,
  identity integration, threat model, and adversarial cases.
- Deterministic Runtime Engineer — Claude Opus 5, high: fixed trust spine,
  typed M2 join, crash recovery, structural zero-model boundary, and replay.
- Persistence/Event Engineer — GPT-5.6 Sol, xhigh: PostgreSQL schema,
  repository, leases, idempotency, attempts, outbox, and live database tests.
- Integration owner — GPT-5.6 Sol: joined the lanes, pinned pgx v5.10.0,
  added real `database/sql` execution, repaired a discovered `nil` evidence
  array defect, ran gates, and coordinated remediation.
- Independent security reviewer — Claude Opus 5, max, read-only.
- Independent GCP reviewer — Gemini 3.1 Pro High through Antigravity,
  read-only.

The initial independent reviews returned FAIL because the first join had only
one stage-less SQL approval and no atomic checkpoint seal. No pass was claimed.
The repair commits added the missing durable join, and both final reviewers
returned **PASS with no blockers**. Detailed evidence is in
`docs/execution/evidence/m3-v2-security-reviews.md`.

## Verification evidence

Final gates on the joined tree:

```text
venv/bin/python -m scripts.verify_v1_baseline
  PASS
  Python: 501 passed, 3 expected skips, 1 existing Pydantic warning
  historical M4-focused suite: 36 passed
  Go tests/race/vet: passed
  frontend build/lint: passed
  frontend: 11 files, 44 tests passed
  whitespace: passed

CPython 3.12.13 / google-adk 2.7.1
  tests/agent_runtime excluding v1 wrapper: 225 passed
  contracts/v2/tests: 10 passed
  tests/contracts: 15 passed

studio-backend
  go test ./...: passed
  go test -race ./...: passed
  go vet ./...: passed

M3_TEST_DATABASE_DSN=postgresql:///zero_trust_m3_test \
  go test -run 'TestM3Postgres(RepositoryLive|ContractIntegration)' \
  -v -count=1 .
  PASS in 0.644s
  post-test matching schemas: 0
```

The live database suite includes missing simulation, mismatched simulation,
stale CAS, injected rollback, successful atomic seal, exact replay, row/event
counts, pending sanitized outbox evidence, and tenant nonce reuse.

## Branches and commits

All lanes started from origin/main `36982fa` in fresh M3 worktrees and were
joined on `agent/v2-m3-integration`.

- `5685d3f` — PostgreSQL authority and transactional outbox
- `dc93062` — deterministic approval authority
- `281c346` — pgx and live repository execution
- `f5dce92` — deterministic trust spine
- `2ca76e0` — approval integration remediation
- `e3ffad6` — M2-to-M3 runtime join remediation
- `3167bc2` — atomic production approval/checkpoint seal remediation

## PostgreSQL hosting reminder

For this milestone, PostgreSQL is hosted locally as the Homebrew PostgreSQL 18
service. Verification uses the dedicated `zero_trust_m3_test` database through
the local Unix-socket DSN `postgresql:///zero_trust_m3_test`. Tests destroy
only their guarded M3 test schema and confirmed that no matching schema
remained.

The intended production host is a regional high-availability **Cloud SQL for
PostgreSQL** instance. Cloud SQL—not Firestore, ADK session content, BigQuery,
SQLite, or an in-memory store—is the intended transactional authority.
BigQuery is downstream analytics/audit projection only, populated later by an
outbox relay or Datastream CDC. Migrated customer data separately follows the
protected edge/GCS/Dataflow/BigQuery data plane. No Cloud SQL or BigQuery
deployment is claimed here.

## Truth boundary and deferred work

Implemented and proven locally: closed deterministic kernels, adversarial
approval validation, authenticated handler composition, registered template
dispatch contracts, atomic PostgreSQL approval/seal, leases, attempts,
idempotency, effect protection, sanitized outbox, crash/replay behavior, and
zero post-approval model calls.

Deliberately deferred:

- M5: final Python-to-Go production wire adapter, public API/UI/plugin
  composition, and hosted Mission Control replay.
- M6: Cloud SQL deployment, IAM/WIF, KMS, Pub/Sub or Datastream, BigQuery
  projection, VPC-SC, Model Armor, managed ADK sessions/memory, and live cloud
  evidence.
- Production load, failover, partitioning, connection-pool, and outbox-vacuum
  tuning.

The M4 deadline scope has separately been narrowed to JDE, Microsoft Dynamics
AX, and Oracle EBS/Oracle 19c, with the other four cartridges deferred if time
does not remain. That planning revision is not an M3 cloud claim.

## Review handoff

The integration tip `78c923f` was merged with `--no-ff` into an origin-current
local `main` as `5f3c658` (`merge: deliver enterprise fleet milestone 3`). The
remote equality check is performed after this final report metadata commit and
push. Before starting M4, the user should review this report and the final
security-review evidence, then explicitly approve the next milestone.
