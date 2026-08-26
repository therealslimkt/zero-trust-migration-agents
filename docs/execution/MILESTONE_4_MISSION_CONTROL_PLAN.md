# Milestone 4 Plan: Real Mission Control

Status: **queued after Milestone 3**

## Outcome

Replace the current simulated dashboard with one event-driven Mission Control
screen that tells the complete three-source migration story. Preserve the
existing dark, terminal-inspired theme while simplifying the interface around
three horizontal swim lanes, a compact private-hardware rail, one portfolio
approval gate, and truthful BigQuery destination states.

Milestone 4 begins only after Milestone 3 has passed its artifact, planner,
state-machine, and digest-bound approval gate. It consumes those frozen
contracts and does not redefine them.

## Primary screen

The main view reads left to right:

```text
Private legacy VM -> Edge translation and protection -> Portfolio approval -> BigQuery
```

All three migrations remain visible simultaneously:

| Lane | Source VM | Translation stages | BigQuery target |
| --- | --- | --- | --- |
| JDE / AS400 | `legacy-jde-db` | EBCDIC/COMP-3 decode, deterministic protection, local Gemma verification, plan | `jde_f0101` |
| SAP MaxDB | `legacy-maxdb` | KNA1 decompress/decode, deterministic protection, local Gemma verification, plan | `sap_kna1` |
| Accpac / Btrieve | `legacy-btrieve-db` | MKD page decode, deterministic protection, local Gemma verification, plan | `accpac_arcus` |

A compact infrastructure rail sits above the lanes:

- Tailscale private-network status
- Sparky (`sparky-sid-411116`): Ollama and `gemma2:2b`, edge-local
- Jetty: optional worker shown only when configured and reporting real status
- Google Cloud and BigQuery connectivity

Sparky and Jetty are infrastructure, not additional migration lanes.

## Frozen UI event progression

The UI maps real control-plane events onto this progression; it does not
advance state with timers:

```text
connecting
-> source_verified
-> export_read
-> decoded
-> deterministic_redaction_passed
-> local_gemma_passed
-> plan_ready
-> awaiting_portfolio_approval
-> approved
-> executing
-> bigquery_verified
-> completed
```

Milestone 4 must use the canonical Milestone 3 state and SSE contracts as the
source of truth. The names above are presentation states; the integration task
must document the exact mapping rather than silently introducing a second
state machine.

## Portfolio approval

One approval control spans all three lanes. It remains disabled until every
source has a validated plan and the backend reports the canonical portfolio as
`awaiting_approval`. The decision shown in the UI is bound to the immutable
portfolio digest. A source failure, redaction block, stale digest, or missing
lane keeps the complete portfolio blocked.

## Evidence and data boundary

The screen may display:

- MagicDNS hostname and connectivity status
- Export byte count and digest
- Decoded, accepted, rejected, and destination row counts
- Redaction and local-Gemma status with evidence digests
- Plan digest, approval actor/time, trusted job ID, and verification state

The screen and its event channel must never contain raw legacy bytes, decoded
PII, tokenization keys, credentials, model prompts/responses, or production
records. Database imagery is limited to code-native, brand-neutral source
icons and format labels; the interface does not render raw binary or hex as a
decorative effect.

## Concurrent provider lanes

After an inventory freezes exact non-overlapping paths:

1. **Codex: event model and integration lead**
   - Map canonical Milestone 3 events into the presentation model.
   - Enforce portfolio approval and reconciliation invariants in UI state.
   - Own integration tests and accept provider commits after cross-review.
2. **Claude Code: frontend reconstruction**
   - Preserve the established theme while building the swim lanes,
     infrastructure rail, approval control, evidence drawer, failure states,
     responsive layout, and accessible interactions.
   - Write only the assigned `studio/` component and style paths.
3. **Gemini/Antigravity: Mission Control backend evidence**
   - Connect the Go backend to real portfolio events and expose hardware,
     Dataflow, BigQuery, and reconciliation evidence without synthetic data.
   - Write only the assigned `studio-backend/` paths.

No provider approves its own work. External-provider context retains the
repository boundary in `AGENT_EXECUTION_PROTOCOL.md`.

## Acceptance criteria

1. JDE, MaxDB, and Btrieve remain visible together on one primary screen.
2. Every progress change comes from a real backend event; random values,
   simulated activity, and timer-driven completion are removed.
3. Sparky is identified truthfully as the edge-local Gemma node. Jetty is
   absent unless configured and connected.
4. The portfolio approval control cannot activate early or approve a stale
   digest.
5. Source, accepted, rejected, and BigQuery row totals reconcile per lane.
6. Disconnected VM, decode failure, redaction block, Gemma error, approval
   rejection, execution failure, and reconciliation mismatch are distinct,
   understandable states.
7. BigQuery remains `pending` until real trusted-execution evidence arrives;
   the UI never fabricates a table write or job ID.
8. The primary demo is clear at 1440x900 and usable at 1280x720, with keyboard
   navigation, visible focus, semantic status text, and reduced-motion support.
9. Frontend lint/build/tests, Go tests, contract tests, and an event-driven
   end-to-end Mission Control test pass.
10. A reviewer can follow one continuous demo from three private sources,
    through edge protection and shared approval, to verified BigQuery results
    without opening another primary view.

## Gate evidence

The milestone closes only with:

- Screenshots at both required viewport sizes
- Recorded event-to-view-model mapping
- Proof that simulated timers/random metrics are absent
- Approval enablement and stale-digest rejection tests
- Failure-state and reconnection tests
- Frontend build/lint/test output and Go test output
- One sanitized end-to-end event trace containing no raw values

## Stop conditions

- Milestone 3 contracts or approval semantics are not frozen.
- The backend would need to expose raw values to reproduce a visual effect.
- Concurrent task write paths overlap.
- A destination state would need to claim Dataflow or BigQuery work that has
  not actually occurred.
