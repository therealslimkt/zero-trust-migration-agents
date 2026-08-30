# M1 architecture record: ADK v2 authority and compatibility boundaries

Status: accepted

Date: 2026-08-30

Decision owners: product runtime, control plane, and security maintainers

## Context

The repository has a working three-source v1 control plane, browser BFF,
contract suite, edge adapters, trusted interpreter, cloud orchestration, and
recorded/live Mission Control paths. The next product runtime adds ADK graph,
collaborative, and bounded dynamic workflows plus seven source cartridges.
Without explicit authority boundaries, ADK session state, the Go lifecycle
store, and browser projections could each appear to be the run authority, and
the new runtime could accidentally break the demonstrated v1 path.

This record freezes the boundary. The detailed observable compatibility rules
are in [the v1 compatibility matrix](V1_COMPATIBILITY_MATRIX.md).

## Decision

### Runtime and state ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| ADK application (`agent_runtime`) | Workflow topology, typed node state, selected team, pending interrupt, bounded budgets, checkpoint references, and sanitized event production | Approval truth, release authority, business lifecycle truth, raw rows, credentials, proprietary binaries, or private reasoning |
| ADK Session Service | Resumable working state and ADK events for production runs | A competing approval, idempotency, lease, or release ledger |
| Go control plane | Authenticated lifecycle transitions, approval records, idempotency, leases, release authority, and the durable outbox | Model reasoning or hidden workflow state |
| Cloud SQL target adapter | Authoritative v2 business-state persistence for the Go control plane | Large evidence bodies or semantic memory |
| GCS artifact store | Content-addressed fixtures, plans, reports, lineage, and evidence bodies | Lifecycle or approval decisions |
| Memory Bank | Verified, tenant-scoped, expiring operational lessons promoted after deterministic reconciliation or authenticated human review | Authority, raw data, credentials, executable procedures, unverified model claims, or chain-of-thought |
| Mission Control | Authenticated commands and event-derived projections for live/replay inspection | Optimistic lifecycle truth or approval fabrication |
| Build-time TypeScript provider broker | Engineering task coordination using source, schemas, tests, and synthetic fixtures | Customer migration orchestration or access to customer/runtime secrets |

The current hosted v1 implementation uses Firestore-backed opaque state
objects. That is a current-state fact, not the v2 authority design. Moving v2
authority to Cloud SQL requires explicit migration and replay tests; it does
not authorize deleting or silently translating v1 state.

### Interface and versioning rules

- `contracts/` and `/api/v1` remain version `1.0.0`; `contracts/web/v1` and
  `/api/web/v1` remain the browser compatibility surface.
- New workflow, node, trace, budget, interrupt, specialist, cartridge, and
  release types live in a separate v2 namespace. v2 fields are not inserted
  into v1 closed schemas.
- `/api/v2` is additive. The clarification input endpoint cannot record an
  approval; simulation and production approvals remain separate authenticated
  control-plane operations.
- `main.py` remains the v1 entry point until its wrapper equivalence gate
  passes. It continues to stop at `awaiting_approval` and never reports a
  pipeline execution.
- The ADK event adapter emits only schema-valid, sanitized projections. It
  includes references and counts rather than artifact bodies, credentials,
  row values, prompts, or private reasoning.
- In-memory session, persistence, and artifact implementations are test-only.
  Production startup fails closed when production adapters are absent.

### Agent and function authority

The product runtime uses the rule **reasoning is an agent node; predictable
work is a function node**.

Agent nodes may interpret sanitized metadata, ask bounded intake questions,
research public technical documentation, and propose closed typed plans.
Function nodes exclusively perform validation, routing, decoding, policy,
approval verification, launch, reconciliation, publication, provenance, and
signing. A resume input wakes an approval node; the node then re-reads the Go
control plane. It never treats ADK `author=user`, A2A content, or the resume
payload as authorization.

Every work packet records its model, permitted files and tools, schemas, call
budget, concurrency/depth limits, and expected trace. Build-time providers may
receive task-relevant source and synthetic fixtures only. They do not receive
environment files, tokens, production data, raw PII, runtime databases, or
private logs.

## Integration sequence

1. Freeze v1 with the compatibility matrix and
   `python -m scripts.verify_v1_baseline`.
2. Add closed v2 contracts and adapters without changing v1 schemas or mounts.
3. Implement the ADK runtime behind fakes and an explicit compatibility
   wrapper; compare the wrapper to golden v1 envelopes.
4. Connect the sanitized event adapter and Cloud SQL interfaces. Dual-read and
   replay tests must reconcile before any authority switch.
5. Enable v2 routes independently. Keep v1 gates mandatory until the complete
   v2 demo and clean-checkout compatibility run pass.

## Consequences and rejected alternatives

- Dual versioning adds adapter work, but prevents seven-source semantics from
  weakening the closed three-source contract.
- Cloud SQL and ADK Session Service intentionally duplicate some references;
  on disagreement, Cloud SQL wins and execution fails closed.
- We reject using ADK session state as approval evidence, routing approvals
  through conversational agents, sharing mutable agent instances across
  teams, model-based deterministic routing, and browser-local run authority.
- We reject reviving `/api/status` or `/ws`; authenticated REST and persisted,
  resumable SSE remain the supported v1 transport.

## M1 verification boundary

The M1 verifier is offline and non-deploying. It checks frozen contract and
entry-point invariants, then runs the existing Python, Go, and frontend gates
in fail-closed order. It does not call Vertex AI, mutate Google Cloud, inspect
credentials, or claim that target ADK/Cloud SQL functionality is implemented.
