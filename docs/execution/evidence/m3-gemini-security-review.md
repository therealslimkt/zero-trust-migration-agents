# Milestone 3 Gemini security review

Reviewer: Gemini 3.1 Pro, read-only bounded review

Reviewed surface: canonical digests, edge artifacts, Gemini planner, portfolio
workflow, approval policy, trusted interpreter, durable Go API, related schemas,
tests, and sanitized live evidence. The reviewer was prohibited from reading
`.env`, credentials, runtime snapshots, logs, caches, raw fixtures, `data/`, or
Git metadata.

## Initial decision: FAIL

The initial independent review identified two accepted blocking issues:

1. Approval and execution calls did not require an explicit set of external
   policy findings. The default empty set could conceal a caller's failure to
   evaluate non-overridable denials.
2. The legacy `/api/status` and `/ws` paths were reachable outside the new
   authenticated control plane.

The reviewer also questioned the bounded SSE replay design. That item was
evaluated separately because the endpoint deliberately closes after a bounded
replay, emits `retry: 2000`, and resumes only after an exact stored
`Last-Event-ID`.

## Repairs

- `policy_categories` is mandatory in approval, workflow, and trusted
  execution APIs.
- Category collections are validated before prepared-snapshot or record work.
- `raw_pii`, `arbitrary_execution`, `public_source_database`, and
  `unapproved_run` remain non-overridable even with a matching approval.
- The live canary passes an explicit empty finding set only after the bound
  redaction artifacts have passed.
- The legacy broadcast and WebSocket handlers are no longer mounted. Only the
  bearer-authenticated `/api/v1/` control plane is reachable.
- Tests cover missing, malformed, and non-overridable policy findings, plus
  unreachable legacy routes.

The exact user-approved live snapshot was re-executed after the repairs. All
three row counts and output digests remained identical.

## Final decision: PASS

Gemini's read-only re-review found no remaining blocking issue. It accepted
the bounded SSE design as lossless ordered replay with standard EventSource
reconnection and bounded server resource use.
