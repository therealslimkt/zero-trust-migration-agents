# Milestone 2 Delivery Report

Milestone 2 implements the local ADK orchestration kernel for the Enterprise
Agent Fleet. It replaces the Milestone 1 runtime's intentionally inert root
factory with three bounded agentic patterns—a fixed catalog graph, an Atlas
collaborative team, and dynamic source/research workers—while preserving the
existing v1 three-source workflow behind a compatibility wrapper.

The capability delivered here is a **tested local orchestration kernel**. The
suite constructs real public Google ADK 2.7.1 `Workflow`, `Agent`, and `App`
objects under CPython 3.12. It does not make live Gemini calls, deploy Agent
Engine, connect managed Session Service or Memory Bank, or prove any Google
Cloud resource.

## 1. Fixed catalog graph, deterministic routing, and resumable state

### What changed

`agent_runtime/graph/` now contains a persistence-independent catalog graph
kernel with closed state types, deterministic route functions, revisioned
checkpoints, a contiguous event journal, interrupt requests, and idempotent
resume handling. `agent_runtime/workflows/catalog.py` constructs the matching
real ADK workflow from public 2.7.1 exports.

The fixed graph performs these steps:

1. Validate the typed migration intent.
2. Fan out metadata, vector, and access probes concurrently.
3. Join all three probe results.
4. Select exactly one named route: `EXISTING_ASSET`, `NEEDS_INPUT`, `MIGRATE`,
   or `FAIL_CLOSED`.
5. Send every unknown or inconsistent result through the explicit ADK default
   edge to `catalog_fail_closed`.

The ADK workflow is capped at four concurrent nodes. If any catalog probe
raises, Python 3.12 structured concurrency cancels and awaits every sibling
before the failure returns; there are no unobserved probe tasks or late probe
side effects.

### Resume and checkpoint behavior

Every snapshot binds `tenant_id`, the full `run_id`, revision, phase, status,
probe facts, route, repair count, interrupt, resume receipts, model invocation
IDs, and ordered events. Checkpoint IDs are SHA-256-derived from tenant, full
run, and unbounded revision, rather than a suffix that could collide.

A clarification resume must match all of the following:

- interrupt ID;
- checkpoint ID;
- input resume channel;
- a previously unused idempotency key, or the exact digest previously accepted
  for that key.

The kernel restores the exact pre-pause phase. A graph paused while planning
returns to `PLANNING`, not a generic earlier phase. Terminal failed or succeeded
runs reject `run`, interrupt, resume, plan-route, and model-call mutations, so a
terminal run cannot be resurrected.

`NEEDS_INPUT` commits the route and clarification pause atomically. It remains
`PAUSED/AWAITING_INPUT`; it is never reported as successful. Simulation and
production approval interrupts use separate approval channels and cannot be
forged through the clarification input endpoint.

### Planning repair example

`route_plan()` accepts one mutually exclusive outcome. A trustworthy
`needs_research` result increments the persisted repair count for attempts one,
two, and three. A fourth research request selects `REJECTED`, marks the run
failed, and makes all later state mutations conflict.

### Exact model-call accounting

Deterministic graph events are structurally prohibited from claiming model
calls. `record_model_call()` accepts only registered model agent IDs and one
unique invocation ID per real adapter boundary. Replaying the same invocation
is idempotent; a different deterministic node cannot manufacture model usage.

### Important files

- `agent_runtime/graph/model.py`
- `agent_runtime/graph/routes.py`
- `agent_runtime/graph/kernel.py`
- `agent_runtime/workflows/catalog.py`
- `tests/agent_runtime/test_graph_routes.py`
- `tests/agent_runtime/test_graph_kernel.py`
- `tests/agent_runtime/test_graph_adk_factory.py`

## 2. Same-session intake and Atlas collaborative specialist team

### What changed

`agent_runtime/collaboration/` implements Atlas planning, task-mode intake,
seven source analyst registrations, typed subset selection, bounded parallel
dispatch, result validation, and Atlas-final synthesis.

The registered analyst profiles are:

- `source_analyst_sap`
- `source_analyst_jde`
- `source_analyst_oracle`
- `source_analyst_cobol`
- `source_analyst_ibmi`
- `source_analyst_sage`
- `source_analyst_ax`

They share one typed specialist input/output boundary. Selection is derived
from the source families present in the portfolio; unrelated analysts are not
instantiated. Every ADK child object must be a fresh instance.

### Intake example

An intake draft missing `objective` and `sources` returns one typed interrupt
bound to the current session. A response for another session or interrupt is
rejected without changing state. Intake asks only for fields still missing and
fails closed after three incomplete rounds. A complete draft produces a
portfolio whose run, session, objective, and sources are verified against the
intake state.

### ADK collaboration behavior

Atlas uses ADK `chat` mode and is the only final speaker. Source intake uses
ADK `task` mode and completes with `finish_task`. Analysts use `single_turn`
mode and return structured node output. In public ADK 2.7.1, Atlas delegates by
the child agent's own name, such as `source_analyst_jde`; no stale
`request_task_*` tool-name convention is assumed.

The dispatcher enforces these hard ceilings for one collaboration run:

- maximum concurrency: 4;
- maximum model dispatches: 30;
- maximum wall time: 1,800 seconds.

Timeout or child failure cancels and awaits siblings. Result validation requires
exact selected-specialist coverage with no missing, duplicate, or unexpected
result. Atlas has no approval, signing, execution, raw-data, or credential
capability.

### Important files

- `agent_runtime/collaboration/profiles.py`
- `agent_runtime/collaboration/models.py`
- `agent_runtime/collaboration/intake.py`
- `agent_runtime/collaboration/planning.py`
- `agent_runtime/collaboration/runtime.py`
- `agent_runtime/collaboration/adk_adapter.py`
- `tests/agent_runtime/test_collaboration_*.py`

## 3. Bounded dynamic source fan-out and Maven research

### What changed

`agent_runtime/dynamic/` implements deterministic, runtime-sized scheduling for
source profiling and recursive research. It accepts only immutable validated
`ContractDocument` requests and only the frozen seven-family cartridge catalog.

Source work accepts one through seven unique source instances. Maven accepts
three through seven top-level research roots, at most three child proposals per
node, and maximum depth two. A single run-wide semaphore and budget enforce:

- maximum concurrency: 4;
- maximum real model calls, including retries and repairs: 30;
- maximum transient retries: 3 (default 2);
- maximum schema repairs: 3;
- maximum wall time: 180 seconds;
- exponential retry delays bounded at 10 seconds.

Outcomes preserve input and tree order even when completion order differs.
Every source/tree branch has a distinct isolation scope. One incomplete child
makes its parent incomplete, and any incomplete root blocks the aggregate.

### Exact timeout-accounting example

The regression suite schedules seven logical source branches with concurrency
four and an intentionally short timeout. Exactly four branches enter the
adapter, so usage reports four model calls—not seven. The three tasks still
queued behind the semaphore consume neither call budget nor model-call usage.
All four active tasks are cancelled and awaited, leaving zero pending tasks.

### Concrete public-ADK seam

`ContextRunNodeAdapter` calls public ADK 2.7.1
`Context.run_node(node, node_input=..., use_sub_branch=True,
override_isolation_scope=...)`. It maps only allowlisted transient and schema
failures into scheduler errors, fails closed on any unknown result, and receives
no `RuntimePorts`, approval, signing, execution, credential, or raw-data
authority.

### Important files

- `agent_runtime/dynamic/types.py`
- `agent_runtime/dynamic/engine.py`
- `agent_runtime/dynamic/adapter.py`
- `tests/agent_runtime/test_dynamic_engine.py`
- `tests/agent_runtime/test_dynamic_adapter.py`

## 4. Typed pattern joins, ADK application assembly, and telemetry

### What changed

`agent_runtime/integration.py` joins the independent patterns without an
untyped dictionary boundary. `portfolio_to_dynamic_sources()` requires exact
request coverage: missing or extra IDs fail, and successful conversion preserves
portfolio order. `build_atlas_team()` and `build_fleet_application()` both use
the central compatibility gate.

The complete application path constructs:

```text
reviewed public ADK Workflow -> reviewed public ADK App -> RuntimeApplication
```

The Python 3.12 smoke suite builds the actual 11-node/12-edge catalog workflow
and a full ADK `App`. These are construction tests, not model invocations or a
deployment.

`TraceAccountant` accepts contiguous `NodeObservation` values and derives exact
model-call, deterministic-node, retry, repair, depth, and concurrency totals.
`SanitizedEventBridge` converts validated contract documents to v2 A2A events
containing only canonical identifiers, orchestration metadata, payload kind,
and a SHA-256 digest. It never publishes the source payload body. The projected
document is validated against the closed v2 A2A event schema in tests.

### Important files

- `agent_runtime/adk_compat.py`
- `agent_runtime/integration.py`
- `agent_runtime/telemetry.py`
- `agent_runtime/application.py`
- `tests/agent_runtime/test_adk_compat.py`
- `tests/agent_runtime/test_integration.py`
- `tests/agent_runtime/test_telemetry.py`

## 5. Injectable production authority and test-only in-memory behavior

Milestone 1's six explicit ports remain the only production authority surface:
state, artifact, model, event, approval, and executor. The Milestone 2 graph and
dynamic adapters do not create hidden clients or ambient credentials.

Production runner construction still requires a caller-owned ADK session
service and sets `auto_create_session=False`. In-memory services and fakes are
restricted to tests. No Vertex, Agent Engine, Cloud SQL, GCS, Pub/Sub, approval,
or executor adapter was added or implied.

The compatibility gate checks CPython 3.12 and exactly `google-adk==2.7.1`
before importing the reviewed public modules. No private underscore module is
imported. The public surface was independently checked against the actual 2.7.1
wheel as well as constructed in the isolated smoke environment.

## 6. v1 compatibility wrapper

The original legacy Antigravity implementation moved to
`agent_runtime/v1_compat.py`. Root `main.py` is now a thin wrapper that keeps
the exact ordered `jde`, `maxdb`, and `btrieve` source portfolio and rejects any
terminal response other than `awaiting_approval`.

This avoids maintaining two root orchestrators while preserving the frozen v1
entry-point behavior. Existing `/api/v1` and `/api/web/v1` contracts remain
unchanged; all new orchestration contracts remain additive under v2.

## 7. Documentation and execution evidence

`agent_runtime/README.md` now describes implemented Milestone 2 behavior,
verified ADK APIs, security boundaries, and deferred cloud work. The new
`docs/execution/ENTERPRISE_FLEET_MILESTONE_2.md` is the enterprise-plan gate
record. The pre-existing `docs/execution/MILESTONE_2_GATE.md` refers to an older
v1 edge-migration history and was intentionally not overwritten.

### Multi-agent implementation pattern

Milestone 2 used a collaborative specialist team behind a fixed integration
graph:

- Graph/Resume Engineer: isolated Codex specialist lane for graph, routing,
  checkpoints, interruption, replay behavior, and focused remediation.
- Collaboration Engineer: isolated Codex specialist lane for Atlas, intake,
  analyst planning, synthesis, and bounded execution.
- Dynamic Workflow Engineer: isolated Codex specialist lane for bounded source
  and research scheduling, ADK invocation, and focused remediation.
- Kernel Integrator: Codex/GPT-5.6 Sol for typed joins, ADK App construction,
  telemetry, v1 isolation, integration tests, and final gate.
- Independent reviewers: Gemini Antigravity and Claude Opus 5, with Opus used
  for the deep full-diff coding audit and final blocker verification.

Only tracked source, tests, contracts, and documentation were shared with
build-time assistants. No `.env`, credentials, customer data, raw PII,
proprietary binaries, local databases, or untracked runtime state was provided.

## Security and compatibility decisions

- Deterministic routers make zero model calls and have an explicit default
  fail-closed path.
- Agent output crosses typed, closed boundaries; invalid types and unauthorized
  capabilities reject the run.
- Approval interrupts and clarification inputs use separate channels. Resume is
  not approval evidence.
- Every concurrency, recursion, retry, repair, intake, and call dimension has a
  hard ceiling in its owning pattern.
- Failure and timeout paths use structured cancellation and await siblings.
- Model-call counts represent actual adapter-boundary entries, including failed
  entries, and exclude work cancelled before entry.
- Dynamic branches receive sanitized documents and least-authority capability
  tuples only.
- Event projection is digest-only and validated against the canonical v2
  schema.
- The ADK/Python compatibility gate fails before importing an unreviewed
  version.
- v1 remains the compatibility baseline and was not rewritten to consume v2
  contracts.

## Exact verification results

### Full compatibility gate

Command:

```bash
venv/bin/python -m scripts.verify_v1_baseline
```

Result: **passed**.

- Frozen v1 compatibility invariants: 3 passed
- Full local Python suite: 412 passed, 3 skipped
- Focused trusted-cloud suite: 36 passed
- Go tests: passed
- Go race tests: passed
- Go vet: passed
- Frontend production build: passed
- Frontend lint: passed
- Frontend tests: 44 passed across 11 files
- Git whitespace validation: passed

The three Python skips in the repository's CPython 3.13 environment are the
tests requiring the exact CPython 3.12/ADK runtime. One pre-existing Pydantic
settings forward-reference warning remains non-fatal.

### Exact CPython 3.12 / ADK 2.7.1 gate

Command:

```bash
/private/tmp/ztm-m2-adk-venv/bin/python -m pytest -q \
  tests/agent_runtime --ignore=tests/agent_runtime/test_v1_wrapper.py
```

Result: **136 passed**. The actual ADK workflow and full App construction tests
ran. One upstream ADK `BaseAgentConfig` deprecation warning was emitted. The v1
wrapper test is excluded only because this isolated environment intentionally
contains `google-adk` but not the legacy `google.antigravity` package; it passes
in the repository environment.

### Focused runtime and contract gates

```bash
venv/bin/python -m pytest -q \
  tests/agent_runtime tests/baseline/test_v1_compatibility.py
# 138 passed, 3 skipped

venv/bin/python -m pytest -q contracts/v2/tests
# 10 passed

git diff --check
# passed
```

### Independent reviews

- Gemini Antigravity post-fix review: **PASS**, no blockers. It confirmed
  structured cancellation, fair 30-call quotas, exact accounting, bounds,
  isolation, the central ADK gate, typed converter, digest-only telemetry, and
  cross-pattern composition.
- Claude Opus 5 first full audit: **FAIL**, identifying phantom timeout call
  accounting and unobserved catalog probe siblings.
- Both findings were repaired with dedicated regression tests.
- Claude Opus 5 narrow re-review of the remediation commits: **PASS**, blocking
  findings: none. It also verified the claimed public API surface against the
  real `google_adk-2.7.1` wheel.

## Commits and merge

Milestone 2 was assembled on `agent/v2-m2-integration` from isolated lanes:

- `b13305a` — add resumable catalog graph kernel
- `d5f0778` — add Atlas collaboration kernel
- `da5c934` — add bounded dynamic workflow kernel
- `d753a63` — bound collaboration lifecycle and exact usage
- `57ef1f9` — harden dynamic scheduling and add public ADK adapter
- `b94154b` — harden graph lifecycle, route repair, and accounting
- `919b438` — integrate the enterprise orchestration kernel
- `75f5661` — cancel and await failed catalog probe siblings
- `7bca1af` — count only entered dynamic model calls
- `3102a28` — document the Milestone 2 runtime and execution gate
- `87ebf20` — add the mandatory detailed Milestone 2 delivery report

Milestone 2 was merged into local `main` as `b0a24f8` (`merge: deliver
enterprise fleet milestone 2`). The report metadata was finalized immediately
after that merge and before the remote push.

## Known limitations and deliberately deferred work

- The graph clarification receipt proves an input was accepted, but the generic
  graph kernel does not interpret free text or mutate catalog facts. The bounded
  typed intake state is implemented in the collaboration lane; a production
  adapter joining accepted typed intake back into catalog facts is deferred.
- Simulation and production approval interrupts are intentionally not resumable
  through the input method. Authenticated, digest-bound approval resolution is
  Milestone 3 work.
- Pattern-local ceilings are enforced, and `TraceAccountant` can aggregate an
  exact trace, but a production cross-lane run coordinator is not yet wired.
- The collaboration identifier domain is wider than the dynamic scheduler's
  deliberately restricted identifier domain. An incompatible ID fails closed;
  normalization policy is deferred to the production adapter boundary.
- The telemetry bridge returns immutable `ContractDocument` data. Concrete
  event-sink serialization and canonical-schema validation at the production
  adapter are deferred; tests validate a thawed projection against the schema.
- No live Gemini model, Vertex AI endpoint, Agent Engine runtime, Session
  Service, Memory Bank, Cloud SQL, GCS, Pub/Sub, Dataflow, BigQuery, approval,
  execution, reconciliation, or cloud trace was used.
- No production source cartridge, plugin package, UI workflow inspector,
  deployment, or canary is claimed by this milestone.
- The strict ADK 2.7.1 pin is intentional. ADK 2.8 or later remains blocked
  until a separate compatibility milestone passes the complete suite.

Milestone 3 should begin only after the user reviews this report and checks out
the merged Milestone 2 result.
