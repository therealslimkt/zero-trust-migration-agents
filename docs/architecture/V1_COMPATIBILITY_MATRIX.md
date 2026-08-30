# v1 compatibility matrix for the ADK v2 migration

Status: accepted M1 baseline

Baseline commit: `b232296`

Contract version: `1.0.0`

This matrix defines what "retain v1 compatibility" means while the ADK product
runtime and `/api/v2` surfaces are introduced. It describes observable behavior,
not an obligation to retain today's internal implementation. The v2 runtime is
additive until every row marked **preserve** has automated compatibility evidence.

| Surface | v1 behavior at the baseline | v2 compatibility rule | Evidence |
| --- | --- | --- | --- |
| Domain contract | JSON Schema draft 2020-12 under `contracts/schemas`, with `contractVersion` and every wire `schemaVersion` fixed at `1.0.0` | **Preserve.** Do not add v2 fields to v1 schemas or reinterpret existing fields. Put new orchestration types in a separate v2 namespace. | `tests/contracts/test_contracts.py`; `tests/baseline/test_v1_compatibility.py` |
| Portfolio membership | A migration contains exactly `jde`, `maxdb`, and `btrieve`, once each, with their canonical MagicDNS hostnames | **Preserve for v1.** Seven-source, one-to-seven fan-out belongs only to v2. A v2-to-v1 adapter must reject portfolios that cannot be represented, rather than truncate them. | Common-schema invariants in the baseline suite |
| Service-token API | `POST /api/v1/migrations`; `GET /api/v1/migrations/{run_id}`; `GET .../events`; `POST .../approval` | **Preserve.** Keep methods, paths, strict JSON bodies, response shapes, status semantics, bearer authentication, and fail-closed unknown-path behavior. `/api/v2` is mounted separately. | `contracts/openapi.json`; Go control-plane tests; baseline route check |
| Browser BFF API | `/api/web/v1` session, immutable demos, publications, runs, source details/terminal, live events and approval, cloud setup, and driver research | **Preserve.** Keep v1 browser clients functional. Add workflow inspection endpoints under `/api/v2`; do not overload v1 run or event documents with v2-only fields. | `contracts/web/v1/openapi.json`; `contracts/web/v1/tests`; Go web tests; baseline route check |
| Internal bridge | A distinct loopback-only, separately authenticated `/internal/v1/orchestration` bridge drives the v1 run and reads approval at `/internal/v1/approvals/{run_id}` | **Preserve while the wrapper exists.** ADK integration cannot reuse browser identity or treat an internal message as approval authority. | `studio-backend/orchestrator_bridge_test.go` |
| Event stream | Persisted, immutable, ordered SSE events; source and portfolio event vocabularies are closed; `Last-Event-ID` resumes strictly after a known cursor; replay is bounded | **Preserve.** A sanitized ADK event adapter may project additional v2 events, but must not alter, synthesize success into, or reorder the v1 stream. Unknown cursors continue to fail closed. | `tests/contracts/test_contracts.py`; `studio-backend/control_plane_test.go` |
| Lifecycle | `created → inventorying → redacting → planning → awaiting_approval → approved → executing → verifying → completed`, with terminal `failed` and `cancelled` alternatives | **Preserve v1 transitions.** ADK node/checkpoint state is not a second lifecycle ledger. The control plane remains authoritative and rejects invalid transitions. | Migration schemas; Go orchestration transition tests |
| Approval | One immutable portfolio decision is bound to the exact `portfolioPlanDigest`; browser approval derives the actor from verified identity | **Preserve and strengthen.** Clarification resumes use v2 input endpoints, but simulation and production approvals remain separate authenticated control-plane records. ADK/A2A/user content can wake a node but cannot prove approval. | Approval schemas; Python approval-policy tests; Go approval tests |
| Python entry point | `main.py` profiles the three sanitized source descriptors concurrently, requests one declarative portfolio plan, audits it, and returns `state=awaiting_approval` | **Preserve observable v1 behavior.** Convert it to a compatibility wrapper only after equivalent ADK tests exist. It must keep the source order/identity, output envelope, environment guard, and approval stop. | Baseline AST check; future wrapper compatibility tests |
| Model authority | Model tools are empty; prompts prohibit raw data and executable content; the prototype plans and audits but does not approve, launch, reconcile, or report completion | **Preserve.** Model nodes may interpret or synthesize only. Routing, validation, approval verification, execution, reconciliation, and signing are deterministic function nodes with exact call accounting. | Security suite; trusted-runtime suite; future ADK call-count tests |
| Declarative execution | Only the closed TransformPlan operation set is accepted; generated code, commands, SQL, and arbitrary expressions fail validation | **Preserve.** New cartridges may add versioned v2 operations only through closed schemas and deterministic interpreters. Never widen the v1 operation set in place. | Contract invalid examples; `tests/security`; `tests/trusted_runtime` |
| Browser application | `studio/src/main.tsx` mounts `WebApplication`; public recorded replay is separate from authenticated live runs; legacy HITL is development-only and opt-in | **Preserve routes and truth labels.** Workflow views are reconstructed from persisted events, not optimistic browser state. Synthetic replay must never be presented as live cloud execution. | Vitest and Playwright suites; Go publication tests |
| Persistence | v1 local mode uses owner-only atomic files; the hosted draft stores opaque state objects in Firestore; events and approvals are immutable within that model | **Migrate internally, preserve externally.** Cloud SQL is the v2 lifecycle/approval/idempotency authority. A migration or adapter must preserve v1 identifiers, decisions, event order, and replay before hosted authority changes. Firestore may remain only a web projection. | Go restart/corruption/hosted-store tests; future Cloud SQL migration tests |
| Evidence and artifacts | Contracts expose identifiers, categories, counts, and SHA-256 digests, never raw records, credentials, approver secrets, or private reasoning | **Preserve.** ADK sessions carry typed state and artifact references only; GCS remains the large-artifact authority. | Contract tests; security tests; future session-content tests |
| Legacy status channels | `/api/status` and `/ws` handlers remain historical code but are not mounted by the supported server mux | **Do not revive.** Supported browser updates are authenticated REST plus bounded SSE. | `studio-backend/origin_test.go`; server-mux tests |

## Compatibility exit rule

The wrapper may stop being the default only when the same clean checkout passes:

1. all v1 contract, Python, Go, frontend, and replay tests;
2. the ADK graph/collaboration/dynamic/resume compatibility suite;
3. a golden comparison proving the v1 wrapper still emits the three-source
   `awaiting_approval` envelope; and
4. crash/restart tests proving zero duplicate side effects and zero
   post-production-approval model calls.

Until then, documentation and UI labels must distinguish current v1 behavior,
implemented v2 behavior, and target architecture.
