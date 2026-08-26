# Multi-provider execution protocol

Codex is the integration lead. Claude Code and Gemini/Antigravity are bounded
workers and independent reviewers. Product-runtime agents remain Gemini-based.

## Milestone rule

Only one milestone may be active. Tasks inside that milestone may run in
parallel only when their write allowlists do not overlap. The next milestone
does not start until the integration branch passes the current milestone gate.

## Workspace rule

Each writing task uses a fresh branch and Git worktree:

- Branch: `agent/m<NUMBER>/<provider>-<task>`
- Worktree: `../worktrees/m<NUMBER>-<provider>-<task>`

Workers do not write on `main` or `integration/hackathon-completion`. The
integration lead reviews and cherry-picks one accepted commit at a time.

## Global context boundary

Allowed when required by the task:

- Source code and tests
- Schemas and interfaces
- Project documentation
- Sanitized deterministic fixtures
- Task-specific diffs

Always denied:

- `.env` and credentials
- Tokens, keys, and secret-manager values
- Git metadata and unrelated branches
- Runtime state, logs, caches, and local databases
- Production data and raw PII

External infrastructure access is read-only unless the task packet names the
exact mutation and the user separately approves it.

## Acceptance flow

1. Integrator creates a task packet with frozen interfaces and owned paths.
2. Worker implements and runs its required checks.
3. Worker returns a commit SHA, validation output, risks, and unresolved items.
4. A different provider reviews the diff against the task packet.
5. Codex cherry-picks an approved commit and runs the whole milestone gate.
6. Failed work returns to a repair branch; unrelated accepted tasks remain
   closed.

An agent never approves its own work. No task may claim a deployment, data
transfer, agent action, or verification step without durable evidence.
