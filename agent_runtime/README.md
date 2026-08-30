# Gemini Agent Runtime Kernel

## Scope and capability label

`agent_runtime` is the production composition boundary for the Zero-Trust
Migration Fleet. Milestone 2 implements and tests the orchestration kernel:

- a catalog-first fixed graph with deterministic joins and routes;
- same-session, checkpoint-bound clarification interrupts and resume;
- Atlas collaboration planning, bounded task intake, and typed specialist
  delegation;
- bounded dynamic source profiling and recursive Maven research;
- exact runtime-observed usage accounting and digest-only event projection;
- real construction of public Google ADK 2.7.1 `Workflow`, `Agent`, and `App`
  objects in an isolated CPython 3.12 verification environment.

This is a **local orchestration-kernel implementation**, not live cloud proof.
It does not ship production Vertex AI, Agent Engine, Session Service, Memory
Bank, Cloud SQL, GCS, approval, or executor adapters, and it makes no live model
or Google Cloud calls. Codex, Claude, and Antigravity are build-time engineering
tools only. Product-runtime model calls will use an approved Gemini model
through an explicitly injected Vertex AI adapter.

## Reviewed runtime baseline

- CPython **3.12** is the reviewed interpreter.
- `google-adk==2.7.1` is the exact reviewed ADK release.
- `requirements-agent-runtime.txt` references Google's release-tagged Python
  3.12 constraints file, bounding both the direct dependency and transitive
  graph.
- The compatibility gate rejects any other Python or ADK version before it
  imports the reviewed ADK modules.

For hermetic CI, mirror the tagged constraints document and wheels in an
internal artifact registry, retain SHA-256 digests in build provenance, and
replace only the remote constraint URL with the immutable mirror URL.

```bash
python3.12 -m venv .venv-agent-runtime
.venv-agent-runtime/bin/python -m pip install --upgrade pip
.venv-agent-runtime/bin/python -m pip install -r requirements-agent-runtime.txt
.venv-agent-runtime/bin/python -m pip check
.venv-agent-runtime/bin/python -m pytest -q tests/agent_runtime
```

An ADK upgrade is a deliberate compatibility milestone, not an ambient
dependency update.

## Package layout

```text
agent_runtime/
  adk_compat.py       # exact Python/ADK gate and reviewed public imports
  application.py      # App and Runner factories with no implicit services
  ports.py            # state/artifact/model/event/approval/executor protocols
  graph/              # resumable catalog graph, routes, checkpoints, journal
  workflows/          # actual public-ADK catalog Workflow construction
  collaboration/      # Atlas profiles, intake, selection, dispatch, synthesis
  dynamic/            # bounded source/research scheduler and ADK Context adapter
  integration.py      # typed cross-pattern joins and complete App assembly
  telemetry.py        # exact trace accounting and sanitized A2A projection
  v1_compat.py        # unchanged legacy three-source implementation
```

Canonical JSON Schemas remain under `contracts/`. Runtime adapters validate
wire documents before wrapping them in immutable `ContractDocument` values.
The records in this package are private adapter SPI and do not replace the
canonical contracts.

## Orchestration behavior

### Catalog-first fixed graph

The ADK graph validates intent, fans out three deterministic catalog probes,
joins them, and routes exhaustively to existing asset, needs input, migration,
or an explicit fail-closed default. The workflow cap is four concurrent nodes.

The persistence-independent graph kernel journals contiguous operations and
checkpoints every revision. Checkpoint IDs bind the full tenant, run, and
revision. Clarification resumes require the matching interrupt, checkpoint,
idempotency key, and input endpoint. Terminal states cannot be interrupted or
resumed. Planning allows at most three research repair cycles; the fourth
request rejects the run. A failing catalog probe cancels and awaits its sibling
probes before the error propagates.

### Atlas collaboration

Atlas is the only final speaker. It selects a typed subset from seven registered
analysts (SAP, JDE, Oracle, COBOL, IBM i, Sage, and AX), creates fresh ADK child
instances, and validates complete result coverage before synthesis. Task-mode
intake is bound to one session and fails closed after three incomplete rounds.

In ADK 2.7.1, child delegation tools use the child agent names themselves—for
example `source_analyst_jde`—rather than a `request_task_*` naming convention.
The task child completes with `finish_task`; single-turn specialists return
their structured node output.

Collaboration dispatch is bounded by four concurrent calls, 30 total calls,
and 1,800 seconds. Timeout or child failure cancels and awaits sibling tasks.
Agents receive no approval, signing, execution, raw-data, or credential
capability.

### Dynamic source and research work

Source profiling accepts one to seven catalog-selected instances. Maven
research accepts three to seven roots, at most three children per result, and
depth two. The scheduler enforces a global concurrency ceiling of four, a
30-model-call budget, bounded transient retries, at most three schema repairs,
and a 180-second wall-time ceiling. Results retain deterministic input/tree
order even when branches complete out of order. Failure or timeout cancels and
awaits all live siblings, and incomplete trees cannot be approved. Calls queued
behind the concurrency semaphore consume neither call budget nor model-call
usage if the run times out before the adapter boundary is entered.

`ContextRunNodeAdapter` is the concrete public-ADK invocation seam. It calls
`Context.run_node(..., use_sub_branch=True,
override_isolation_scope=...)`; it does not use private APIs and is deliberately
not granted any `RuntimePorts` authority.

### Integration and telemetry

`portfolio_to_dynamic_sources` rejects missing, extra, or reordered source
coverage. `build_fleet_application` constructs the catalog workflow and wraps
it in the pinned ADK `App` through the same compatibility gate.

`TraceAccountant` requires contiguous node observations and accounts exact
model versus deterministic boundaries. `SanitizedEventBridge` publishes only
canonical identifiers, orchestration metadata, and a SHA-256 digest of the
validated document; it never embeds the source payload.

## Composition and authority

Production startup must construct concrete adapters outside this package and
pass a complete `RuntimePorts` object to `build_fleet_application`. The root
factory receives only that explicit context. `build_runner` additionally
requires a caller-owned ADK session service and sets
`auto_create_session=False`; in-memory services are test-only.

ADK owns orchestration topology and runtime node state. It does not own
authenticated approvals or deterministic execution authority. Those remain
separate control-plane capabilities and are implemented in later milestones.
A resume message can wake a clarification node; it is never approval evidence.

## Verified public ADK surface

Milestone 2 uses only public exports verified against `google-adk==2.7.1`:

- `google.adk.apps.app.App`
- `google.adk.runners.Runner`
- `google.adk.agents.Agent`
- `google.adk.workflow.Workflow`, `JoinNode`, `START`, `DEFAULT_ROUTE`, and
  `node`
- `Context.run_node` with public sub-branch and isolation parameters

The Python 3.12 smoke suite constructs the real catalog graph and full ADK App.
It does not invoke a live model or deploy the application.

## Prohibited behavior

- Sending raw PII, source records, credentials, or proprietary binaries to a
  model or build-time assistant.
- Generating or evaluating Python, shell, Beam source, SQL expressions, or
  arbitrary executable content.
- Continuing after schema, policy, capability, checkpoint, or tenant binding
  failure.
- Treating an interrupt resume as simulation or production approval.
- Launching execution without a separately authenticated, digest-bound
  control-plane approval.
- Reporting cloud deployment, reconciliation, or production readiness from
  local kernel tests.

## Compatibility

`main.py` is now a thin v1 wrapper. The original three-source Antigravity
implementation lives in `agent_runtime/v1_compat.py`; the wrapper preserves the
ordered `jde`, `maxdb`, `btrieve` portfolio and requires the exact
`awaiting_approval` terminal handoff. Existing `/api/v1` behavior remains the
compatibility baseline while v2 capabilities stay additive.

## Deliberately deferred

Milestone 3 supplies authenticated approval, deterministic post-approval
execution, authoritative persistence, outbox/replay, and crash-safe side-effect
deduplication. Later milestones supply seven source cartridges, plugin factory,
Mission Control v2, live Google Cloud adapters, deployment, and canary evidence.
