# Milestone 3 — Trust Spine Design

## What this is, plainly

The trust spine is a **local, injectable kernel**. It is a small Python state
machine that runs in the caller's process, drives a fixed sequence of seven
node kinds, and writes an auditable trace through injected ports.

It is **not** cloud execution. There is no scheduler, no queue, no worker pool,
no network client and no hosted control plane anywhere in
`agent_runtime/trust_spine/`. The package ships **zero** implementations of its
own ports: a caller must inject a state store, an approval authority, a model
repair adapter, a template dispatcher, a ledger reader and a certification
signer. Everything the tests exercise runs against local fakes.

The production `StateStore` seam is intentionally transactional. Cloud
SQL/PostgreSQL is the authoritative target: its adapter must compare-and-swap
the expected checkpoint and, in one database transaction, append the
production approval and replace the checkpoint with the irreversible
`APPROVED_FOR_EXECUTION` seal. BigQuery is downstream analytics only and may
not implement this authority port. SQLite is not a production authority.

It is also **not** an extension of the planning graph. It is a *separate,
post-plan* kernel: an immutable plan goes in, a certified result comes out, and
nothing in between re-enters planning. Recursion depth is fixed at `0`,
side-effect concurrency is fixed at `1`, and the node list is a closed constant
(`NODE_PLAN`) that a plan is not permitted to alter.

The executable join is `agent_runtime.m3_integration.TrustSpineCoordinator`.
It accepts exactly a `ReadyFrozenPlan`, constructed from an M2 snapshot whose
phase is `COMPLETE`, status is `SUCCEEDED`, pending interrupt is absent, and
immutable graph binding equals the full `FrozenPlan.plan_digest`. It rejects a
generic `ResumeInput`, A2A `ContractDocument`, bare `FrozenPlan`, mapping, or
duck-typed object. This is a local coordinator seam, not a deployed adapter,
and it does not change or pass through the v1 compatibility wrapper.

## The fixed trace

```
prisma_validate ──(invalid)──> prisma_repair ──┐   (≤ 3 attempts, pre-approval only)
      ▲                                        │
      └────────────────────────────────────────┘
      │ valid
      ▼
deterministic_policy ──> vale_verify
      │
      ▼
  simulation approval        (server-side, via ApprovalAuthority)
      │
      ▼
  production approval        (server-side, distinct subject — SEALS THE RUN)
      │
      ▼
flow_dispatch ──> ledger_reconcile ──> forge_certify
```

Approvals are not nodes. They are separate `ApprovalRecord`s appended to the
journal and folded into the same hash chain, because an approval is a decision
about a subject, not a computation over an input.

### Node responsibilities

| Node | Kind | Owns |
| --- | --- | --- |
| `prisma_validate` | pure | Turns an untrusted payload into a `ValidatedProposal`: a registry template identity plus closed typed parameter values. |
| `prisma_repair` | model | The single model boundary. Bounded to `MAX_REPAIRS = 3`, pre-approval only, returns **data** (a `CanonicalMap`), never a callable or a target. |
| `deterministic_policy` | pure | Tenant/template allowlists, parameter conformance against the registry-owned specs, obligations. |
| `vale_verify` | pure | Independent re-derivation of the decision under its own configuration. Verifies only: it has no repair path and no widening path. |
| `flow_dispatch` | effect | Hands the sealed bundle to the registry dispatcher and validates the receipt. |
| `ledger_reconcile` | externally observed read | Validates the receipt against the sealed expectations and the ledger's report. |
| `forge_certify` | effect | Re-walks the entire digest chain, then signs and releases under separate authority. |

## The frozen plan is the only first state

`TrustSpineRuntime.execute` accepts a `FrozenPlan` and nothing else. A dict, a
mapping, a namespace or a mutable "plan object" is refused with
`FailureCode.INVALID_TYPE` at the boundary — it is never coerced into shape.

`FrozenPlan` is a frozen, slotted dataclass whose every field is itself
immutable: a `RunRequest` (with a `CanonicalMap` payload), a `PolicyConfig`, a
`BudgetPolicy` and the closed `node_plan`. Its digest is therefore stable for
the life of the run, which is what makes it safe to bind into every key below.

## The production boundary

The production approval seals the run in **one PostgreSQL transaction**:

```python
checkpoint.advanced(phase=RunPhase.APPROVED_FOR_EXECUTION, seal_digest=..., ...)
```

`StateStore.commit_production_approval(expected_checkpoint, record,
sealed_checkpoint)` must compare-and-swap the expected checkpoint, append the
production decision, and install the sealed checkpoint atomically. That
checkpoint simultaneously sets the phase, fixes `seal_digest` and copies the
current model-call total into `model_calls_at_seal`. There is no intermediate
"production decision exists but execution is unsealed" state.

It is irreversible in three independent ways:

1. `RunCheckpoint.advanced` refuses any backwards phase transition, refuses to
   re-seal to a different digest, and refuses any change to `model_calls` once
   sealed.
2. `Journal.commit_production_approval` refuses conflicts and delegates the
   decision plus seal to the store's atomic compare-and-swap transaction.
3. `RunCheckpoint.__post_init__` pins `post_seal_model_calls` to
   `POST_PRODUCTION_MODEL_CALLS` (`0`) and requires
   `model_calls == model_calls_at_seal` whenever the checkpoint is sealed. A
   checkpoint that claims a post-production model call cannot be *constructed*,
   let alone persisted.

### Post-approval model access is structural, not counted

After the seal, the runtime builds a `SealedExecution` and runs the three
effect nodes through it. That object has exactly five slots — `sealed`,
`plan_digest`, `flow`, `ledger`, `forge` — and:

* it does not satisfy the `ModelCapable` protocol (no `repair` method exists to
  satisfy it);
* it holds no field named like a model adapter or provider;
* it holds **no callable field at all**;
* `assert_no_model_surface` performs a cycle-safe traversal of stored fields,
  mappings and containers at arbitrary nesting depth, and checks private as
  well as public class members. A bounded object-count ceiling fails closed;
  callers cannot weaken the proof by passing a shallow depth. Ordinary class
  methods on deterministic dispatcher, reader and signer ports remain valid,
  while stored callables and private/nested model capabilities do not.

The distinction matters. A counter would answer "how many model calls have
happened?" with `0` and still leave a method that could make one. Here there is
no method to call: `PrismaKernel` — the only object in the package that holds
an adapter — is simply not reachable from the post-approval path. The same
check is applied to the `Journal` (the one object that legitimately crosses the
boundary), which is why the journal stores model *accounting* (integers) rather
than a model *capability*.

The runtime still enforces the accounting belt-and-braces:

* `Journal.begin` refuses to journal a non-zero `model_call_delta` once the
  checkpoint is sealed;
* `NodeRecord` refuses a non-zero delta on any node outside `MODEL_NODES`;
* `_finalise` asserts every record at or after the first side-effect record has
  `model_call_delta == 0`, that `RunResult.post_production_model_calls == 0`,
  and that the checkpoint itself
  `proves_post_production_model_free`.

## Idempotency keys

Two derivations, both pure functions of durable material, both validating every
component at full length:

```python
derive_effect_key(tenant_id, run_id, source_digest, node,
                  plan_digest, proposal_digest, seal_digest, input_digest)

derive_approval_key(tenant_id, run_id, source_digest, stage,
                    subject_digest, plan_digest)
```

Side-effect keys bind tenant + run + node + the **full** plan digest + the
**full** proposal digest + the seal digest + the node's input digest. Changing
any component changes the key; a truncated digest is refused with
`INVALID_DIGEST` rather than accepted or padded.

Approval keys bind the stage and the subject, which is what makes a simulation
approval structurally unusable at the production boundary: replaying it
produces the wrong key and fails with `APPROVAL_REPLAY`.

The M2 graph applies the same rule before the handoff. Its snapshot contains a
full immutable SHA-256 `binding_digest`; operation, checkpoint, interrupt and
resume-receipt identities hash a domain tag plus tenant, run and that complete
binding. Approval interrupts additionally bind their distinct subject. The
hash encoding uses all 64 hexadecimal characters. A caller presenting the
same run under a different binding gets `run_binding_mismatch`; values are
never trimmed, case-folded, padded or prefix-compared.

## Intent before effect, and stable-key replay

Every node — including the *read* in `ledger_reconcile`, because that read is
externally observed — follows the same order:

1. append a `STARTED` record carrying the exact idempotency key the port will
   be given, and write the checkpoint;
2. invoke the port;
3. write the durable output into the checkpoint state;
4. append the `SUCCEEDED` record and write the checkpoint.

Step 3 deliberately precedes step 4, so a persisted `SUCCEEDED` record always
implies a readable output.

Resume is driven entirely from the journal:

| Crash point | Durable state | Resume behaviour |
| --- | --- | --- |
| before the intent | nothing | node runs for the first time |
| after the intent, before the effect | `STARTED` | the same intent is reused; the port is called once |
| after the effect, before persistence | `STARTED` | the port is re-invoked **under the identical key** and answers from its own idempotency store |
| after the output, before the success record | `STARTED` + output | the port is re-invoked; the fresh answer is compared with the durable one |
| after the success record | `STARTED` + output + `SUCCEEDED` | the port is not touched; the result is decoded from the checkpoint |

Pure nodes are re-computed rather than decoded, and their digests compared to
the journal: a deterministic stage that no longer reproduces its recorded
answer is treated as corruption.

### Conflicting replay fails closed

* A port that answers the same key with a different result →
  `IDEMPOTENCY_CONFLICT`.
* A record whose `predecessor_digest` does not link to the recomputed chain, or
  a checkpoint whose chain is not a prefix of the durable trace →
  `CHAIN_CORRUPTION`.
* A run id already bound to a different frozen plan (or a different stored
  result) → `RUN_CONFLICT`.
* An effect node with a durable terminal failure → the run stops; it is not
  retried past a recorded failure.

The model-call budget is charged on an intent record immediately before every
actual repair-adapter boundary entry, including failures and crash re-entry.
The stable request key still lets the adapter deduplicate its effect, but every
real invocation remains visible and consumes one of the maximum three repair
entries (and one unit of the global budget).

## Approvals

Approvals enter the runtime through `ApprovalAuthority.fetch_approval` and
nowhere else. Each record is verified against the exact query that was asked:
authority principal, tenant/run/source, stage, subject digest, chain position
and derived key, and finally the decision itself.

The two boundaries are genuinely distinct:

* the **simulation** subject is a digest over the plan, proposal, policy and
  Vale verdict;
* the **production** subject is the `ExecutionBundle` digest — an object that
  did not exist when the simulation approval was answered, because the bundle
  embeds the simulation approval.

The runtime additionally refuses two approvals that share a digest, a key or a
stage.

On a sealed resume, authentication is not performed again and the
`ApprovalAuthority` is not read. The runtime instead revalidates both immutable
records: approved decision, shared recorded authority, tenant/run/source,
stage, exact simulation and production subjects, predecessor positions,
derived idempotency keys, and the approval digests embedded by the sealed
bundle. Any mismatch fails closed before Flow can run.

**There is no generic resume input.** `TrustSpineRuntime` has exactly one
public method, `execute(plan)`. A pending approval raises `APPROVAL_MISSING`
and leaves the checkpoint intact; the caller resumes by calling `execute` again
with the same frozen plan. Nothing a caller can hand back is capable of
standing in for an approval. Clarification resume — asking a human for more
*input* mid-plan — is a planning-graph concern and is deliberately absent here;
conflating the two is exactly how an approval boundary gets bypassed.

## Flow, Ledger, Forge

**Flow** is handed a `DispatchRequest`, whose only fields are a `SealedBundle`
and an idempotency key. The bundle carries a registry template *identity* and
`ParameterBinding`s of closed `TypedValue`s. String parameters must come from a
registry-declared allowlist; the character class for any text is restricted to
letters, digits, spaces and `_ . , : # -`, which cannot express a path, a
command, a URL or an expression. The executable handle stays in the registry
and is represented only by an opaque `handle_fingerprint` digest. There is no
field anywhere in which a caller or a model could supply a command, module, SQL
statement, path, image reference or expression — and payload keys that merely
*read* like one are rejected with `DANGEROUS_KEY`.

The runtime derives `expected_effect_digest(sealed)` independently and requires
the receipt to carry exactly that digest, so Flow cannot execute one thing and
report another.

**Ledger** validates the report against the receipt *and* the sealed
expectations: tenant, run, seal, bundle, dispatch id, the independently derived
effect digest, the query key and the reader principal — then requires
`reconciled` to be true.

**Forge** re-walks the entire chain from genesis, verifying every record's link,
before it will build a signature request, and validates that the seal is bound
to the production approval. Signing and release authority live only in
`CertificationPort`.

## Principal and object separation

`TrustSpineRuntime.__init__` requires five distinct principals — model adapter,
approval authority, dispatcher, ledger reader, signer — *and* five distinct
objects (checked by identity). `SealedExecution` repeats the check for the
three effect principals. One object may not hold two roles even if it presents
two identifiers.

## Identifier domain

Identifiers are matched with `fullmatch` against patterns anchored with `\Z`
(not `$`, which also matches before a trailing newline). Run ids must be at
least 16 characters, so a truncated prefix of a real run id cannot satisfy the
shape check. Source digests must be exactly `sha256:` plus 64 lowercase hex
characters.

Candidates outside the domain are **refused, never repaired**:
`require_match` contains no `strip()`, no `lower()` and no slice. `"acme_corp\n"`,
`" acme_corp"`, `"ACME_CORP"` and a 15-character run id are all terminal
`INVALID_IDENTIFIER` failures, and a valid identifier is stored byte-for-byte
as given.

## Durability model

The simulation approval may use the ordinary append operation. Production is
different: `StateStore.commit_production_approval(expected, approval, sealed)`
is a mandatory atomic transaction boundary. A crash before that transaction
commits leaves neither a production approval nor a seal; a committed
production approval without its matching seal is treated as corrupt state.

* `NodeRecord` — one durable record per node attempt, binding tenant/run/source,
  node, sequence, attempt, predecessor chain digest, input digest,
  output-or-error digest, key, status and model-call delta.
* `ApprovalRecord` — one per boundary, folded into the chain immediately after
  the successful `vale_verify` record, which makes the fold order
  reconstructible from the durable data alone.
* `RunCheckpoint` — phase, chain digest, sequence, model-call accounting, seal
  state, and a bounded state map keyed only by
  `proposal`/`payload`/`receipt`/`reconciliation`/`certificate`.
* `RunResult` — the immutable outcome, stored once. A completed run replays
  from the stored result without touching a port.

Repaired payloads are stored per attempt (`a1`, `a2`, `a3`) so a later repair
can never overwrite the payload an earlier attempt was journalled against, and
the repair chain is re-walked identically on every replay.

### Joining the M2 and M3 journals

The two journals remain separate and keep their own local sequence and digest
rules. They join only in the PostgreSQL event authority. In the intended
adapter, one transaction assigns a monotonically increasing
`postgres_sequence` to a reference containing journal name, local sequence and
immutable record digest. Replay orders only by that database sequence, never
by timestamps or BigQuery ingestion order.

`PostgresJournalEvent`, `project_graph_event` and
`project_trust_spine_record` are pure typed definitions of that seam. Given the
same authoritative sequence and immutable record, they produce the same closed
v2 A2A event. Deterministic components emit from `mission_control`; their exact
`implementationId` is carried in the contract-defined `contextRefs` member
because the closed A2A orchestration block has no implementation field. Router
events use the full closed route object. Approval interrupts are `blocked`,
set `requiresHumanApproval=true`, and use `interrupt_request` payload kind.
BigQuery is a downstream consumer of these projections only. This repository
does not claim that the PostgreSQL adapter is deployed.

## Failure posture

Every failure is terminal and typed (`FailureCode`). There is no retry loop
outside the bounded repair budget, no fallback path, no "best effort" branch
and no place where a refusal is downgraded to a warning. When the runtime
cannot prove a property, it stops.

## Testing

* `tests/agent_runtime/test_m3_trust_spine.py` — the fixed trace, frozen-plan
  entry, bounded pre-approval repair, the seal and its irreversibility, the
  structural model-freedom of the sealed path, key derivation, the identifier
  domain, Flow/Ledger/Forge validation, approvals, and replay stability.
* `tests/agent_runtime/test_m3_trust_spine_crash.py` — crash before the effect,
  crash after the effect before persistence, crash after each node, a crash at
  every durable write of a single run's lifetime, and conflicting-replay
  fail-closed behaviour. Every port fake is idempotent on its key and counts
  real effects, so "zero duplicate effects" is asserted directly.
* `tests/agent_runtime/test_m3_integration.py` — the READY/frozen coordinator
  boundary, rejection of generic resume/A2A inputs, exact plan binding, and
  deterministic contract-valid projection of both journals under PostgreSQL
  authority.
* `tests/agent_runtime/test_telemetry.py` — closed route projection,
  deterministic component attribution and approval-required event semantics.

All fakes are local, in-process and data-configured; none of them holds a
callable, which is what lets the model-surface assertions run against the real
objects the runtime carries across the production boundary.
