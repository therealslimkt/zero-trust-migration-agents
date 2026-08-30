# Milestone 1 Delivery Report

Milestone 1 establishes the compatibility, contract, and runtime foundation for
the Enterprise Agent Fleet. It is intentionally additive: the demonstrated
three-source v1 workflow remains operational while the new ADK-based v2 runtime
is introduced behind strict boundaries.

## 1. Frozen v1 compatibility matrix and authority ADR

### What changed

Two architecture documents now define what later milestones are allowed to
change and which system remains authoritative for each kind of state:

- `docs/architecture/V1_COMPATIBILITY_MATRIX.md`
- `docs/architecture/M1_ADK_V2_BOUNDARY_RECORD.md`

The compatibility matrix freezes observable v1 behavior rather than its
internal implementation. It records the existing API routes, three-source
portfolio, lifecycle, approval semantics, event ordering, browser behavior,
declarative execution boundary, persistence behavior, and evidence rules.

The authority record separates responsibilities across the product runtime:

- ADK owns workflow topology, typed node state, selected specialists,
  interrupts, budgets, and checkpoint references.
- The Go control plane owns authenticated lifecycle transitions, approvals,
  idempotency, leases, and release authority.
- Cloud SQL is the target authoritative v2 business-state store.
- GCS owns large content-addressed evidence and artifacts.
- Memory Bank may contain only verified, tenant-scoped operational lessons.
- Mission Control renders event-derived projections and does not invent state.

### Examples

- `/api/v1` and `/api/web/v1` remain unchanged. New orchestration fields are
  introduced only under `contracts/v2` and `/api/v2`.
- A seven-source v2 portfolio cannot be silently truncated into the existing
  three-source v1 shape. A future adapter must reject an unrepresentable
  portfolio.
- An ADK resume input may wake an interrupted node, but it cannot serve as
  approval evidence. The resumed node must re-read the authenticated control
  plane record.
- Firestore is documented as the current hosted v1 implementation, while
  Cloud SQL is the planned v2 authority. No migration or authority switch was
  claimed in this milestone.
- Model agents may interpret sanitized metadata and propose typed plans. They
  may not route approvals, launch execution, reconcile data, or sign releases.

### Why it matters

These documents prevent later parallel work from accidentally creating a
second approval ledger, weakening v1 contracts, confusing replay with live
execution, or treating conversational content as authorization.

## 2. ADK 2.7.1 and Python 3.12 runtime scaffold

### What changed

The previously documentation-only `agent_runtime` directory now contains an
inert, production-oriented composition boundary:

- `agent_runtime/adk_compat.py`
- `agent_runtime/application.py`
- `agent_runtime/ports.py`
- `agent_runtime/__init__.py`
- `requirements-agent-runtime.txt`

The runtime is pinned to CPython 3.12 and `google-adk==2.7.1`. Startup fails
closed if a different Python or ADK version is present. The release-tagged
Google constraints file bounds the transitive dependency graph.

Six asynchronous dependency-inversion ports define every authority available
to future workflows:

1. `StateStore`
2. `ArtifactStore`
3. `ModelProvider`
4. `EventSink`
5. `ApprovalAuthority`
6. `Executor`

No production adapters, credentials, cloud clients, in-memory defaults, model
calls, or execution side effects are created in Milestone 1.

### Examples

The application is assembled from explicit settings, explicit ports, and a
root factory:

```python
application = build_application(
    settings=RuntimeSettings(
        app_name="zero_trust_migration_fleet",
        environment="production",
    ),
    ports=runtime_ports,
    root_factory=build_root_workflow,
)
```

Runner construction requires the caller to supply a session service. There is
no production fallback to an in-memory service:

```python
runner = build_runner(
    application,
    session_service=vertex_session_service,
    artifact_service=gcs_artifact_service,
    memory_service=memory_bank_service,
)
```

Documents cross runtime ports as immutable `ContractDocument` objects carrying
a canonical schema identifier. This avoids creating competing Python wire
models before the v2 contracts are generated into language-specific types.

### Why it matters

Later graph, collaboration, and dynamic-workflow code can be tested without
ambient cloud authority. A workflow receives only the capabilities explicitly
injected into it, and production startup cannot quietly fall back to ephemeral
state.

## 3. Closed v2 schemas, OpenAPI, fixtures, and integrity verification

### What changed

A new additive `contracts/v2` package contains:

- Ten closed JSON Schema Draft 2020-12 documents
- An OpenAPI 3.1 document with exactly three orchestration routes
- Eleven valid examples
- Eleven invalid mutation fixtures
- A content-addressed manifest
- An offline integrity verifier and contract test suite

The package defines workflow identifiers and versions, graph/collaborative/
dynamic patterns, node kinds, node executions, checkpoints, orchestration
budgets, traces, interrupts, specialist invocations, task envelopes, A2A event
metadata, cartridge manifests, artifact records, reconciliation, lineage, and
memory-promotion records.

Object schemas are closed with `additionalProperties: false`. Runtime bounds
are encoded directly in the schemas:

- Maximum concurrent nodes: 4
- Maximum model calls: 30
- Maximum dynamic depth: 2
- Maximum retries per node: 3
- Maximum source instances: 7

### API examples

The additive v2 API exposes only:

```text
GET  /api/v2/runs/{run_id}/orchestration
GET  /api/v2/runs/{run_id}/events
POST /api/v2/runs/{run_id}/inputs/{interrupt_id}
```

The input route accepts only `clarification` and `task_input` interrupts. Its
schema has no actor, approval, authorization, or decision field. Simulation and
production approvals remain separate authenticated control-plane operations.

### Contract examples

- A node identified as deterministic cannot set `modelCall: true`.
- An unknown cartridge such as an unregistered source family is rejected.
- Unknown readiness and distribution labels are rejected rather than displayed
  as production-ready.
- Artifact records carry URI, media type, size, version, and SHA-256 digest
  rather than embedding evidence bodies.
- Memory promotion requires verified evidence and scoped region, tenant,
  purpose, source, cartridge, fidelity, and fingerprint metadata.
- A cartridge manifest with a changed field but an unchanged embedded digest
  fails the integrity check.

### Integrity behavior

`contracts/v2/manifest.json` lists every schema, OpenAPI document, and fixture.
The verifier canonicalizes the package's supported JSON subset and checks the
recorded contract-set digest. It also verifies embedded content digests used by
fixtures such as the JDE cartridge manifest.

### Why it matters

Parallel runtime, Go API, frontend, cartridge, and cloud work now share one
closed interface boundary. Invalid agent output is rejected before it can
reach deterministic execution or be rendered as trusted evidence.

## 4. Consolidated fail-closed baseline verification

### What changed

`scripts/verify_v1_baseline.py` is the single offline milestone gate. It runs
the existing and new checks in deterministic order and stops immediately on
the first failure.

The gate runs:

1. Frozen v1 compatibility invariants
2. Complete Python regression suite
3. Focused trusted-cloud suite
4. Go tests
5. Go race tests
6. Go vet
7. Frontend production build
8. Frontend lint
9. Frontend tests
10. Git whitespace validation

The implementation avoids shell command strings, places Python and Go caches
under a bounded temporary directory, and performs no deployment or live cloud
mutation.

### Example

Run the complete compatibility gate from the repository root:

```bash
python -m scripts.verify_v1_baseline
```

If, for example, the Go race suite fails, frontend checks are not run and the
command exits nonzero with the failed gate named explicitly.

### Milestone 1 verification results

- Python: 288 passed, 1 optional ADK smoke test skipped under Python 3.13
- Focused trusted-cloud suite: 36 passed
- ADK 2.7.1 smoke suite: passed in a disposable Python 3.12.13 environment
- Go tests: passed
- Go race tests: passed
- Go vet: passed
- Frontend build and lint: passed
- Frontend tests: 44 passed
- v2 contract tests: 10 passed
- Legacy contract tests: 15 passed
- Independent full Draft 2020-12 validation: all valid and invalid fixtures
  behaved as expected
- Contract integrity and whitespace checks: passed

## Commits and merge

Milestone 1 was integrated from three isolated work lanes:

- `6e288e3` — scaffold pinned ADK runtime boundary
- `22b0969` — freeze the v1 compatibility baseline
- `ec3d214` — define enterprise fleet v2 contracts
- `5dcac79` — merge Milestone 1 into `main`

## Deliberately deferred

Milestone 1 does not claim that the ADK workflow, Cloud SQL authority, Vertex
AI adapters, Memory Bank, live `/api/v2` handlers, seven cartridges, plugin
factory, or cloud deployment are implemented. Those remain gated work for
later milestones.
