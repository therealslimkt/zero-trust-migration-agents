# Gemini Agent Runtime Specification

## Scope

`agent_runtime` will contain the production multi-agent control plane for the Zero-Trust Migration Fleet. Codex and Claude remain build-time engineering tools. All product-runtime planning and semantic profiling use Gemini 3.5 Flash or newer through Vertex AI.

## Target Package Layout

```text
agent_runtime/
  orchestrator.py
  models.py
  vertex_client.py
  profilers/
    jde.py
    maxdb.py
    btrieve.py
  planner.py
  auditor.py
```

Canonical JSON Schemas live under `contracts/`; runtime models must be generated from or validate against those schemas rather than defining a competing contract.

## Runtime Responsibilities

- Validate sanitized edge input before any model request.
- Dispatch the three source profilers concurrently.
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
