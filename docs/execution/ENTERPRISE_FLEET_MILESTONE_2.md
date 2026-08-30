# Enterprise Fleet Milestone 2 — Orchestration Kernel

## Gate purpose

Milestone 2 turns the inert Milestone 1 runtime boundary into a locally
executable, fail-closed orchestration kernel. It proves the three required
agentic patterns independently and joins them through typed interfaces:

```text
fixed catalog graph
  -> eligible Atlas specialist team
  -> bounded dynamic source/research work
  -> digest-only event projection
```

The implementation constructs real public Google ADK 2.7.1 objects under
CPython 3.12, but does not deploy or call Google Cloud services. Production
state, model, approval, artifact, event, and execution adapters remain injected
ports.

## Pattern 1: fixed graph with deterministic routing

The catalog graph contains one intent validator, three parallel deterministic
probes, an explicit join, and an exhaustive router. Unknown, incomplete, or
inconsistent facts reach a named fail-closed edge. A separate persistence-
independent kernel makes each transition revisioned and crash-observable.

Implemented invariants include:

- full tenant/run/revision checkpoint binding;
- contiguous journal sequences and unique operation IDs;
- terminal-state non-resurrection;
- exact pre-pause phase restoration;
- idempotent same-answer resume and rejection of key reuse with different data;
- clarification and approval resume-channel separation;
- atomic NEEDS_INPUT route-and-pause behavior;
- at most three planning repair cycles;
- exact, allowlisted model-boundary accounting;
- structured cancellation and awaiting of sibling probes on failure.

## Pattern 2: collaborative specialist team

Atlas plans a least-authority team from seven frozen source analyst profiles.
Only analysts required by the selected source instances are instantiated.
Every child is fresh, single turn, structured-output only, and unable to approve
or execute. Atlas validates complete result coverage and remains the final
speaker.

Task-mode source intake asks only for missing typed fields, stays in one
session, and stops after three incomplete rounds. Collaboration execution is
bounded at four concurrent dispatches, 30 calls, and 1,800 seconds. Timeout or
failure cancels and awaits all siblings.

## Pattern 3: bounded dynamic work

The dynamic engine schedules one to seven source workers or three to seven
Maven research roots. Research has width three per node and depth two. One
global semaphore, one fair call budget, and one wall-time boundary govern the
entire run. Retry and schema-repair attempts consume real model-call budget;
queued calls cancelled before adapter entry consume none.

Each invocation carries a unique isolation scope and only its exact sanitized
request. The concrete ADK adapter uses public `Context.run_node` sub-branches;
it has no approval, execution, signing, credential, or raw-data port. Any
incomplete branch blocks aggregation.

## Integration boundaries

- `portfolio_to_dynamic_sources` requires exact source/request coverage and
  preserves portfolio order.
- `build_atlas_team` and `build_fleet_application` pass through the central
  Python 3.12 / ADK 2.7.1 compatibility gate.
- `TraceAccountant` records contiguous deterministic and model observations.
- `SanitizedEventBridge` emits schema-valid A2A metadata plus a content digest,
  never the document body.
- `main.py` delegates to the isolated v1 implementation and retains the exact
  three-source, awaiting-approval compatibility stop.

## Security and authority boundaries

The kernel may interpret sanitized metadata and propose typed results. It may
not authenticate approvals, authorize execution, launch a pipeline, reconcile
data, sign a release, or promote memory. In-memory ADK services are test-only.
No module imports a private ADK API, and no production adapter or credential is
created implicitly.

## Truthful status

Implemented and tested here:

- local deterministic kernels and adapters;
- real ADK Workflow, Agent, and App construction;
- bounded scheduling, retries, cancellation, interruption, resume, and usage
  accounting;
- closed typed joins and digest-only telemetry projection;
- v1 wrapper compatibility.

Not implemented or proven here:

- live Gemini or Vertex AI calls;
- Agent Engine deployment;
- managed Session Service or Memory Bank behavior;
- Cloud SQL, GCS, Pub/Sub, or production event adapters;
- authenticated approval and deterministic execution spine;
- live Google Cloud traces or canaries.

The pre-existing `docs/execution/MILESTONE_2_GATE.md` documents an older v1
edge-migration milestone and is retained as repository history. This file is
the gate description for the Enterprise Fleet Milestone 2 plan.
