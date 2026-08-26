# Hackathon Judging and Verification Traceability

This matrix maps the official scoring dimensions to product behavior and durable evidence. It distinguishes implemented proof from target behavior so the submission never overstates progress.

| Official dimension | Target product behavior | Required proof |
| --- | --- | --- |
| Innovation and Operational Utility (40%) | One autonomous portfolio run reverse-engineers JDE/AS400, SAP MaxDB, and Accpac/Btrieve in parallel, replacing three bespoke middleware paths while preserving a human governance gate. | Three real source inventories, parallel agent events, normalized outputs, reconciliation totals, elapsed time, and a defensible middleware/licensing cost comparison. |
| Architectural Discipline (30%) | Gemini 3.5+ on Vertex AI produces typed declarative plans; true local edge controls block PII; least-privilege identities and signed plan approval separate planning from execution. | Architecture diagram, schema validation failures, edge leak test, IAM policy export, plan digest and approval record, and proof that arbitrary code execution is absent. |
| Demo and Production Readiness (30%) | A continuous demo starts one portfolio, shows three live lanes, pauses once for approval, launches trusted Dataflow work, and verifies BigQuery output. | Real SSE events, Vertex trace IDs, Dataflow job IDs, BigQuery queries, audit rows, retry/failure behavior, and reproducible deployment instructions. |

## Mandatory technology traceability

- **Gemini 3.5 or newer:** runtime orchestration, source profiling, planning, and audit assistance through Vertex AI.
- **Google agent framework:** runtime agent definitions, subagent delegation, and structured tool boundaries.
- **Google Cloud:** Vertex AI, Dataflow, BigQuery, Cloud Storage/Artifact Registry as required by the final implementation, and Cloud Logging evidence.

## Proof catalog

1. **Zero-trust edge:** compare an authorized local test fixture with the sanitized outbound packet and show deterministic PII leak tests fail closed. Raw values never enter cloud logs or the video.
2. **Declarative planning:** retain the schema-valid TransformPlan and show executable keys are rejected.
3. **Approval:** retain the portfolio digest, approval actor, timestamp, and state transition.
4. **Execution:** show the trusted template version, typed job parameters, Dataflow job ID, and terminal state.
5. **Integrity:** reconcile per-source input, accepted, rejected, and BigQuery row totals with checksums.
6. **Security:** export least-privilege IAM and show anonymous sandbox invocation is unavailable.

## Current gaps that must not be presented as complete

- The active UI still uses timers and random values.
- Current source pulling and edge redaction are mocked.
- The current Gemini flow has no functional tools and reports simulated execution.
- No migration BigQuery dataset or Dataflow job currently exists.
- The old Cloud Run service is contained but still runs the unsafe image.
- The MaxDB VM retains a public IP until the private path is proven.

## Demo acceptance

The final recording must be one continuous run. Uniform speed-up is acceptable only if permitted by the rules and applied to the whole uncut recording. Every visible success claim must resolve to a trace ID, job ID, query, audit record, or deterministic test result.
