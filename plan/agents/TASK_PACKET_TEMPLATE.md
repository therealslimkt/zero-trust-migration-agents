# Task packet: <task ID>

- Milestone: `<number>`
- Provider: `<codex | claude | gemini>`
- Owner: `<agent name>`
- Reviewer: `<different provider>`
- Base commit: `<integration SHA>`
- Branch: `agent/m<number>/<provider>-<task>`
- Worktree: `../worktrees/m<number>-<provider>-<task>`

## Objective

State one bounded outcome.

## Frozen interfaces

List schemas, routes, messages, and invariants that this task must preserve.

## Context

- Read allowlist: `<paths>`
- Read denylist: `.env`, credentials, Git metadata, runtime state, logs, local databases, production data, raw PII
- Write allowlist: `<non-overlapping paths>`
- Network policy: `<deny | explicit read-only allowlist>`
- Allowed commands: `<commands>`

## Acceptance criteria

1. Add task-specific, deterministic criteria.
2. Require exact verification commands.
3. Require fail-closed behavior for security boundaries.

## Stop conditions

- A required interface is ambiguous or incompatible.
- A requested path falls outside the allowlist.
- A credential, raw PII, or production mutation would be required.
- Tests expose unrelated baseline breakage that prevents trustworthy validation.

## Result contract

Return:

- Commit SHA
- Summary of changed behavior
- Validation commands and results
- Security or deployment implications
- Known risks and unresolved items
