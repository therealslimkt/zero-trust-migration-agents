# Enterprise Fleet Milestone 3 independent reviews

Status: **PASS after remediation**

This record concerns the enterprise-fleet M3 trust spine added after commit
`36982fa`. It is separate from the older v1 M3 review retained elsewhere in
this directory.

## Reviewers

- Claude Opus 5, max effort, read-only code and security audit.
- Gemini 3.1 Pro High through Antigravity, read-only Google Cloud authority
  and claim-truthfulness audit.

Both reviewers inspected the joined implementation rather than reviewing the
three implementation lanes in isolation. Neither review changed source files
or cloud resources.

## Initial result: FAIL

Both reviewers found the same blocking integration defect: the Python trust
spine required an atomic
`commit_production_approval(expected_checkpoint, approval, sealed_checkpoint)`
operation, but the PostgreSQL schema supported only one stage-less approval
per run and had no durable workflow checkpoint. Consequently the first joined
build proved the seal only with Python test fakes.

Opus also required the join to close these related gaps:

- make simulation and production distinct durable decisions;
- compose the authenticated approval handlers without widening frozen v1 or
  the exactly-three-path v2 contract;
- use one strict tenant/run identifier domain;
- replace source-order inspection with behavioral PostgreSQL evidence;
- join M2 identities and event projection to the separate M3 trust spine; and
- align nonce uniqueness with the threat model.

No milestone pass was claimed while these findings remained open.

## Remediation

- `2ca76e0` hardens the approval composition, derives the actor from the
  existing verified identity path, enforces stage authorization, preserves
  frozen v1 bodies, and rejects approval-shaped v2 resume/A2A input before it
  can reach a generic resume handler.
- `e3ffad6` joins the immutable M2 plan to the separate trust spine, binds
  identities to tenant and subject, fixes deterministic event projection,
  strengthens the post-seal model-surface check, and revalidates immutable
  production approval facts on sealed resume.
- `3167bc2` adds staged authority decisions, durable checkpoints and approval
  journal entries, tenant-scoped one-time nonces, and one serializable exact-CAS
  transaction covering the production journal entry, checkpoint seal/model
  freeze, run transition, idempotency result, and sanitized outbox event.

The live PostgreSQL suite drives the real repository for missing or mismatched
simulation, stale CAS, injected rollback, success, exact replay, row/event
counts, pending sanitized outbox evidence, and tenant nonce reuse. It is
opt-in so a clean offline checkout does not require PostgreSQL.

## Final result: PASS

Gemini 3.1 Pro High found no remaining blocker and stated that the local M3
exit gate is met. Claude Opus 5 independently found no remaining blocker and
also stated that the local M3 exit gate is met.

The reviewers accepted these truthful deferrals:

- M5 owns the final Python-to-Go production API/UI/plugin composition.
- M6 owns Cloud SQL deployment, WIF/IAM, KMS, Pub/Sub or Datastream relay,
  BigQuery projection, VPC-SC, Model Armor, and live cloud evidence.

Local PostgreSQL 18 is evidence for the repository contract, not evidence of
a deployed Cloud SQL instance. BigQuery remains downstream analytics only.
