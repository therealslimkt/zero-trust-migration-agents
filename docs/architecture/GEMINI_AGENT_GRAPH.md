# Production Gemini Agent Graph Architecture

## 1. Overview & Operational Model

The Zero-Trust Migration Fleet executes autonomous schema discovery, reverse-engineering, and migration planning for legacy enterprise databases into Google Cloud BigQuery. The runtime fleet processes a single migration portfolio containing three parallel legacy sources:

- `legacy-jde-db` (JD Edwards / AS400 EBCDIC binary streams)
- `legacy-maxdb` (SAP MaxDB relational catalog and data)
- `legacy-btrieve-db` (ACCPAC Btrieve record files)

### Role Separation: Build-Time vs. Product Runtime

- **Build-Time Engineering & Review:** OpenAI Codex and Anthropic Claude act exclusively as developer tooling, static analysis checkers, and code reviewers during development. They have zero presence in production runtime.
- **Product Runtime Engine:** Production runtime is powered exclusively by **Gemini 3.5 Flash** hosted on Google Cloud Vertex AI in `us-central1`.

## 2. Edge Privacy Firewall & Ingestion Boundary

Legacy data sources communicate across Tailscale MagicDNS from the edge host `sparky-sid-411116`. Raw database bytes and PII never reach cloud services.

1. **Deterministic Filter:** Regex tokenizers and rule sets mask known PII patterns and extract record structural delimiters.
2. **Local Gemma Filter:** A lightweight local Gemma model runs directly on Sparky to identify and redact unstructured sensitive tokens.
3. **Cloud Egress:** Only sanitized structural metadata, obfuscated field headers, and synthetic data samples are transmitted to Vertex AI over TLS.

## 3. Agent Graph

```text
Edge sources -> Sparky privacy firewall -> Orchestrator
                                             |
                              +--------------+--------------+
                              |              |              |
                         JDE profiler   MaxDB profiler   Btrieve profiler
                              +--------------+--------------+
                                             |
                                      Transform planner
                                             |
                                         Plan auditor
                                             |
                                  Portfolio human approval
                                             |
                                  Trusted Dataflow template
```

### Agent Roles and Contracts

1. **Orchestrator**
   - Input: sanitized metadata bundle for all three portfolio sources.
   - Output: orchestration state, task delegations, and aggregated status.
   - Responsibility: lifecycle, parallel branches, bounded retry, and UI status.
2. **JDE, MaxDB, and Btrieve Profilers**
   - Input: source-specific sanitized samples, layouts, and dialect hints.
   - Output: typed `SourceProfile` with fields, encodings, nullability, and evidence.
   - Responsibility: infer structure without executing code or observing raw PII.
3. **Transform Planner**
   - Input: three profiles and the approved target schemas.
   - Output: declarative, schema-validated `TransformPlan` operations.
   - Rule: never emit code, scripts, commands, or arbitrary expressions.
4. **Plan Auditor**
   - Input: `TransformPlan` plus target schemas.
   - Output: validation report with compatibility, lineage, and evidence.
   - Responsibility: reject unsafe operations, narrowing, and unmapped keys.

## 4. State Transitions, Retries, and Approval

- Transient Vertex AI calls use bounded exponential backoff.
- Schema-invalid structured output receives at most three repair attempts.
- A source failure is isolated and visible; it does not silently disappear or cause a partial portfolio to be approved.
- Once all three source plans pass deterministic validation, the Orchestrator enters `awaiting_approval` and presents one immutable portfolio plan digest.
- Approval binds the run, approver, timestamp, and digest. Dataflow cannot launch without it.

## 5. Baseline vs. Target

| Dimension | Milestone 0 baseline | Target behavior |
| --- | --- | --- |
| Agent output | Loose chat and generated Python | Declarative schema-validated JSON only |
| Region | Prototype uses `asia-northeast1` | Verified Vertex AI runtime in `us-central1` |
| Edge privacy | Mock payload and cloud-based redaction | Deterministic rules plus true local Gemma |
| Execution | Cloud Run arbitrary `exec()` | Trusted pre-registered Dataflow template |
| Approval | Simulated automatic continuation | Blocking portfolio approval bound to digest |
