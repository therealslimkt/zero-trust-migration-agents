# Gemini Agent Runtime Foundation

## Scope

`agent_runtime` contains the production composition boundary for the Zero-Trust
Migration Fleet. Codex and Claude remain build-time engineering tools. All
product-runtime planning and semantic profiling use an approved Gemini model
through a future Vertex AI adapter.

Milestone 1 is intentionally inert: it defines ports and constructs ADK objects,
but it ships no credentials, clients, in-memory production services, live model
calls, or cloud side effects.

## Runtime baseline

- CPython **3.12** is the reviewed interpreter.
- `google-adk==2.7.1` is the exact reviewed ADK release.
- `requirements-agent-runtime.txt` references Google's release-tagged Python
  3.12 constraints file, so both the direct dependency and transitive graph are
  bounded independently of the repository's legacy requirements.
- For hermetic CI, mirror the tagged `constraints-3.12.txt` and the wheels in an
  internal artifact registry, retain their SHA-256 digests in build provenance,
  then replace only the remote constraint URL with that immutable mirror URL.

```bash
python3.12 -m venv .venv-agent-runtime
.venv-agent-runtime/bin/python -m pip install --upgrade pip
.venv-agent-runtime/bin/python -m pip install -r requirements-agent-runtime.txt
.venv-agent-runtime/bin/python -m pip check
```

The compatibility gate rejects Python versions other than 3.12 and ADK versions
other than 2.7.1. An upgrade is a deliberate compatibility milestone, not an
ambient dependency update.

## Foundation package layout

```text
agent_runtime/
  adk_compat.py   # exact-version import gate for App and Runner
  application.py  # inert composition and runner factories
  ports.py        # state/artifact/model/event/approval/executor protocols
```

Canonical JSON Schemas live under `contracts/`. Runtime adapters must validate
against generated canonical types before wrapping data in `ContractDocument`.
The small records in `ports.py` are private adapter SPI and must never become a
second wire schema.

## Composition

Production startup must create concrete adapters outside this package and pass a
complete `RuntimePorts` object to `build_application`. The root factory receives
that explicit context; it has no ambient cloud or approval authority.

`build_runner` additionally requires a caller-supplied ADK session service and
accepts optional ADK artifact, memory, and credential services. It deliberately
sets `auto_create_session=False` and does not provide in-memory defaults. ADK's
in-memory services are permitted only inside tests.

This foundation uses only APIs verified in the 2.7.1 source:

- `google.adk.apps.app.App(name=..., root_agent=...)`
- `google.adk.runners.Runner(app=..., session_service=...,
  auto_create_session=False)`
- `Runner.run_async(...)` as the later production execution entry point

Graph, workflow, resumability, Session Service, and Memory Bank behavior remain
for later milestones; this package does not guess at unverified deployment APIs.

### Verification provenance

The implementation was reviewed against Google's public `google/adk-python`
v2.7.1 source and release metadata. The requested Antigravity/Gemini assistant
invocation was attempted, but the managed workspace policy rejected transmitting
repository context to the external service. No assistant-generated code was used
and no repository data was routed around that control.

## Runtime Responsibilities

- Validate sanitized edge input before any model request.
- Dispatch only catalog-selected source profilers within explicit concurrency
  and call budgets.
- Require structured model output and reject unknown fields.
- Produce only allowlisted declarative transform operations.
- Run deterministic audit checks before presenting a plan.
- Bind the portfolio approval to the exact plan digest.
- Dispatch only a registered Dataflow template with typed parameters.
- Persist sanitized event and evidence references for the UI.

## Prohibited Behavior

- Sending raw PII or database pages to Vertex AI.
- Generating or evaluating Python, shell, Beam source, SQL expressions, or arbitrary code.
- Continuing after schema-validation or deterministic redaction failure.
- Launching Dataflow without portfolio approval.
- Reporting completion before BigQuery reconciliation passes.

## Retry Policy

- Retry only transient Vertex AI errors with exponential backoff and jitter.
- Allow at most three schema-repair attempts for invalid structured output.
- Do not retry policy denial, PII detection, approval rejection, or incompatible schema drift automatically.
- Preserve source-level failure while keeping other profiling branches observable; the complete portfolio remains unapproved.

## Baseline Gap

The current `main.py` is a prototype: it uses loose chat strings, empty tools, mixed regions, simulated payloads, and a simulated execution claim. Later milestones replace it incrementally; this README describes target behavior and is not deployment evidence.
