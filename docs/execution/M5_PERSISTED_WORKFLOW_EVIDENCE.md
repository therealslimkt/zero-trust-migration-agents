# M5 persisted workflow-evidence extension

`GET /api/web/v1/runs/{run_id}/workflow-evidence` is an optional,
authenticated browser-BFF extension. It is deliberately not added to either
frozen v1 control-plane contract or the three-route v2 orchestration contract.

The handler first verifies the browser identity and resolves the run through
the existing owner binding. It then calls only an injected
`WebPersistedWorkflowEvidenceReader`. No reader, a foreign run, a missing
record, or an absent endpoint produces no projection; the browser renders the
existing **Workflow evidence unavailable** state.

The reader must project facts persisted by the orchestration authority. Each
entry is closed and ordered: sequence, event ID, persisted flag, workflow-node
state, evidence digest, and either model/deterministic-node identity or a
separate approval-endpoint interrupt. The BFF rejects malformed output before
it reaches the browser. It does not derive entries from timestamps, prose,
SSE narration, browser state, prompts, raw rows, or approval input.

This M5 slice supplies the BFF boundary and browser parser. Wiring an M3
Cloud SQL repository into a hosted deployment remains a separately evidenced
deployment task; local demo intentionally leaves the reader absent and makes
no orchestration-evidence claim.
