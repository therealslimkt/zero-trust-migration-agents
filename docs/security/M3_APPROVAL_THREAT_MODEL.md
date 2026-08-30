# Milestone 3 Approval Threat Model

## Scope and security objective

Milestone 3 separates simulation approval from production approval. Its security objective is narrow: a production action may proceed only after an authenticated, authorized human decision is immutably bound to the exact tenant, run, stage, plan, release, artifact, interrupt, checkpoint, and preceding approved simulation. Approval verification is deterministic and makes zero model calls.

The local Python kernel and the self-contained Go handlers are reference boundaries. Cloud SQL/PostgreSQL is the production transactional authority. BigQuery receives downstream, sanitized analytics only and is never queried to authorize a decision. SQLite and in-memory stores are not production authorities.

## Assets and trust boundaries

Protected assets are production execution authority, approval identities, single-use nonces, canonical plan/release/artifact digests, approval records, stage progression, and tenant/run isolation.

Untrusted inputs include HTTP bodies, resume text, A2A messages and metadata, model output, browser-supplied identity or role fields, client clocks, analytics data, and arbitrary content claiming approval. A request body carries only an opaque request ID, nonce, and a stage-specific decision. Authentication credentials travel through the transport/authentication layer, not the approval JSON.

The trusted boundary contains:

- the transport authenticator that derives a principal server-side;
- the authority read that obtains canonical tenant/run/stage/audience/quorum and plan/release/artifact/interrupt/checkpoint state;
- Cloud SQL's pending request, nonce, simulation record, and production record transaction;
- the injected UTC clock and deterministic binding verifier.

The artifact store is trusted only for immutable digest-addressed bytes and presence. It cannot grant approval. ADK workflow state can request an approval interrupt but cannot resolve one. A mismatch between ADK-derived context and the transactional authority rejects the request.

## Binding model

All digests use SHA-256 over a domain-separated, length-framed encoding. Field names and values are both framed, ordering is fixed, and stage-specific domains prevent a digest from being reinterpreted. A pending request binds:

- request ID, tenant ID, run ID, and stage;
- plan, release, and artifact SHA-256 digests;
- approval interrupt and checkpoint IDs;
- the digest of the one-time nonce;
- issued-at and expires-at instants;
- required audience and approver quorum;
- for production, the approved simulation record digest.

Approval interrupt IDs are derived from the tenant, stage/kind, and full approval subject. Thus an interrupt from another tenant or subject is not portable. The stored immutable decision record binds the pending request digest, authenticated actor, normalized decision, server time, and every subject digest.

The authority context is read server-side and repeats canonical bindings intentionally. Every value must agree with the stored pending request. This fails closed on stale plan data, release changes, missing or replaced artifacts, wrong interrupt/checkpoint, cross-tenant/run access, wrong audience, approver shortfall, and ADK/database disagreement.

## Stage progression

Simulation and production have different input types, decision vocabularies, handlers, and pending request kinds. A production request can be issued only after an immutable simulation `approve` record exists for the same tenant, run, plan, release, and artifact. The production request binds that exact simulation record digest. A simulation rejection is a valid immutable human decision but cannot satisfy production progression.

Changing the plan, release, artifact, run, tenant, stage, simulation record, or interrupt requires a new server-issued request and nonce. Frozen v1 request and `ResumeInput` shapes are not widened. Existing `resume()` rejection of approval content remains in force; approval resolution is a separate authority read and record operation. Snapshot idempotency receipts concern resume delivery only and do not prove or de-duplicate production side effects.

## Replay, time, and concurrency

A nonce is stored only as a domain-separated digest and is consumed in the same transaction that inserts the immutable decision. It is globally one-time within the approval authority. Verification uses an injected UTC clock with the interval `issued_at <= now < expires_at`; an expiry-boundary request is rejected.

The production Cloud SQL adapter must execute pending-row lock/read, binding checks, nonce uniqueness, stage-record uniqueness, prior simulation lookup, and decision insertion in one PostgreSQL transaction. Unique constraints should cover nonce digest and `(tenant_id, run_id, stage)`. Serializable isolation or explicit `SELECT ... FOR UPDATE` locking must preserve the reference `compare-and-record` semantics. A lost race rejects without mutation. Side-effect idempotency belongs in Cloud SQL, not the workflow snapshot or BigQuery.

## Deterministic adversarial evaluator/optimizer

Before recording, a fixed battery checks authentication, authorization, tenant/run/stage, plan/release/artifact and presence, interrupt/checkpoint, audience/quorum, nonce, time window, and simulation progression. The optimizer verifies that the required threat set is complete, normalizes its ordering, and repeats it. Acceptance requires identical all-true results on both passes. There are no extension hooks, models, tools, network calls, or user-authored rules.

Packet limits are model-call budget `0`, approval-record concurrency `1`, and graph depth `0`. A success trace is exactly:

1. `request_observed`
2. `authenticated_authority_read`
3. `bindings_verified`
4. `immutable_decision_recorded`

Any failure produces only `fail_closed_rejection`; no partial success trace and no approval-state mutation are emitted. Public errors are stable and omit secrets and internal mismatch details.

## Explicitly rejected proof sources

The following never prove approval: resume text or receipts, A2A events, user content saying “approved,” model messages, browser-supplied actor/role/auth fields, an unverified artifact, a BigQuery row, or possession of an interrupt/checkpoint ID without the current nonce and authenticated authority. Closed JSON decoding rejects extra fields, trailing documents, oversized bodies, wrong content types, wrong methods, and stage vocabulary swaps.

## Integration seams

- Implement `ApprovalStore.compare_and_record` / `M3ApprovalRepository.CompareAndRecordM3` with Cloud SQL transactional semantics and immutable append-only records.
- Implement the Go authenticator with the existing verified identity middleware; do not accept identity claims from JSON.
- Implement the authority read from policy plus Cloud SQL canonical run state. It must validate audience/quorum and artifact presence and return only bounded identifiers/digests.
- Route simulation and production handlers separately. Do not wire the generic resume or A2A endpoints to them.
- Keep secrets/nonces out of logs, traces, metrics, BigQuery, and error text. Export only sanitized record IDs, digest bindings, stage, result, latency, and rejection category where policy permits.
- Gate execution on a freshly loaded immutable production approval record and enforce Cloud SQL side-effect idempotency in the same operational boundary.

## Residual risks and operations

Compromised identity providers, authority policy, Cloud SQL administrators, signing keys, or artifact writers remain privileged threats. Mitigations include phishing-resistant authentication, short request lifetimes, least-privilege database roles, row-level tenant controls, append-only audit export, key rotation, artifact immutability, clock monitoring, and alerts on replay or binding failures. The reference memory stores do not survive restarts and provide no distributed transaction; they must never be selected in production configuration.
