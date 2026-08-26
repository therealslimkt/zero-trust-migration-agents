# Milestone 1 Gate

Date: 2026-08-26

## Integrated work

- Codex: canonical JSON Schemas, OpenAPI REST/SSE contract, sanitized and
  forbidden examples, and offline conformance tests.
- Claude Code: approval and denial policy, validation-only MCP compatibility
  service, authenticated/internal Cloud Run configuration, Secret Manager
  Tailscale bootstrap, private-path preflight, and restricted browser origins.
- Gemini: production agent graph, Google Cloud trust boundaries, and judging
  evidence traceability.
- Codex integration fix: the active Gemini prototype now produces three-source
  declarative plans and stops at `awaiting_approval`; it cannot request code
  generation or report a simulated migration success.

## Independent review

- Gemini contract review: PASS, no blockers.
- Claude architecture review: PASS, no blockers. Target-versus-current wording
  was clarified before integration.
- Codex security review found and corrected static-test false positives,
  explicit Invoker-IAM enforcement, loopback status-post compatibility, Python
  package name collision, Go formatting, and missing MaxDB hardening.

## Gate evidence

- Contract conformance: 15 passed.
- Python security and MCP regression: 50 passed.
- Go test and vet: passed.
- Frontend lint: passed.
- Python and shell compile/syntax checks: passed.
- Docker Compose configuration: passed with obsolete-version warnings.
- `git diff --check`: passed.

The complete WIP frontend build remains a known baseline failure and is owned
by Milestone 4. No Milestone 1 artifact claims that Dataflow, BigQuery, local
Gemma, or the real source adapters are already implemented.
