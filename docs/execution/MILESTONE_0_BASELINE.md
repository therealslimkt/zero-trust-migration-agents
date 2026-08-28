# Milestone 0 Baseline

Date: 2026-08-26

Branch: `integration/hackathon-completion`

Checkpoint: `265e945` (`chore: checkpoint hackathon implementation baseline`)

## Provider readiness

| Provider | Status | Milestone 0 use |
| --- | --- | --- |
| Codex CLI 0.149.1 | Authenticated | Repository inventory and integration lead |
| Claude Code 2.1.228 | Authenticated | Bounded read-only security audit |
| Antigravity CLI 1.1.19 | Available | Brokered Gemini architecture audit |

External providers may receive only task-relevant source, tests, schemas,
documentation, sanitized fixtures, and diffs. They must not receive `.env`,
credentials, tokens, runtime state, local databases, logs, Git metadata,
production data, or raw PII.

## Active implementation

- The active frontend is `studio/src/main.tsx` -> `studio/src/App.tsx`.
- The active frontend uses timers and random values and is a simulation, not
  acceptable final evidence.
- `main.py` is the current Gemini/Antigravity orchestration prototype.
- At this baseline checkpoint, `studio-backend/main.go` still contained the
  legacy status/WebSocket implementation. It is superseded: the current mux
  explicitly leaves `/api/status` and `/ws` unmounted, while the supported
  browser surface is REST plus bounded SSE. See
  [`docs/GOLANG_MISSION_CONTROL_ARCHITECTURE.md`](../GOLANG_MISSION_CONTROL_ARCHITECTURE.md).
- `studio/src/studio/` and `studio/src/orchestrator/` are checkpointed WIP and
  are not wired into the active application.

## Verification baseline

| Check | Command | Result |
| --- | --- | --- |
| Frontend lint | `cd studio && npm run lint` | Pass |
| Frontend build | `cd studio && npm run build` | Fail: WIP control-plane dependencies and TypeScript configuration are incomplete |
| Active Vite bundle | `cd studio && ./node_modules/.bin/vite build` | Pass, but Tailwind output is effectively missing |
| Go compile | `cd studio-backend && GOCACHE=/tmp/ztm-gocache go test ./...` | Pass; no tests exist |
| Python compile | `PYTHONPYCACHEPREFIX=/tmp/ztm-pycache ./venv/bin/python -m compileall -q .` | Pass |
| Python tests | `./venv/bin/python -m pytest -q` | Blocked: pytest is not declared or installed |
| Compose validation | `docker compose config --quiet` | Pass with obsolete-version warning |

`requirements.txt` is empty, so Python installation is not reproducible.

## Live infrastructure evidence

- GCP project: `ztm-agent-9049c3`.
- `legacy-btrieve-db`, `legacy-jde-db`, and `legacy-maxdb` are running.
- Tailscale MagicDNS is enabled and all three legacy peers plus
  `sparky-sid-411116` report online.
- Canonical source names are `legacy-btrieve-db`, `legacy-jde-db`, and
  `legacy-maxdb`; application code must not depend on their `100.x` addresses.
- BigQuery currently has no dataset for the migration output.
- At audit time, Cloud Run service `execution-sandbox` was publicly invokable
  and ran as the default Compute Engine service account. Milestone 0 removed
  the `allUsers` invoker binding, re-enabled the Invoker IAM check, and changed
  ingress to `internal`. Replacing the service identity and removing arbitrary
  execution remain release blockers.
- `legacy-maxdb` still has a public IP. Remove it only after the private
  Tailscale data path is proven from Sparky.

## Release-blocking findings

1. Disable public arbitrary code execution in `sandbox_mcp.py`,
   `tools/mcp_sandbox.py`, and the deployed Cloud Run service.
2. Replace the default Compute Editor identity with least-privilege service
   accounts.
3. Implement actual local edge redaction. The current so-called local agent
   sends raw input to Vertex AI and therefore contradicts the zero-trust claim.
4. Replace simulated agent tool calls, file transfers, Dataflow writes, UI
   events, and BigQuery rows with verifiable actions.
5. Align runtime resources on `us-central1` unless a verified Gemini model
   availability constraint requires a documented exception.
6. Replace hard-coded workstation paths and provide reproducible dependency
   manifests.
7. Use an explicit Cloud Build configuration; do not rename Dockerfiles during
   deployment.

Milestone 1 must freeze contracts and remove architectural contradictions
before feature branches begin.

## Emergency containment completed

The live `execution-sandbox` presented unauthenticated in-process Python
execution. Before closing this milestone, its public invoker binding was
removed, its Invoker IAM check was enabled, and ingress was changed from `all`
to `internal`. The resulting service IAM policy has no bindings and the service
reports `run.googleapis.com/ingress: internal`.

This containment is not an endorsement of the service. The arbitrary `exec()`
implementation must not be redeployed. Milestone 3 replaces it with signed,
pre-registered Dataflow templates and typed parameters.
