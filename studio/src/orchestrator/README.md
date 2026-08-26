# Skin Mission Control Orchestrator

Local TypeScript control plane for provider discovery, task orchestration, context enforcement, approvals, feedback, PostgreSQL persistence, and the REST/SSE interface consumed by Skin Studio.

The approved local stack uses Node.js, Fastify, PostgreSQL 18, pgvector, and LangGraph checkpoint storage. Start the database and services with:

```sh
brew services start postgresql@18
npm run db:migrate
npm run dev:api
npm run dev:studio
```

Runtime state belongs under `.orchestrator/runtime/` and is ignored by Git. PostgreSQL is authoritative; `events.jsonl` is an append-only audit mirror.

## Provider boundaries

Provider tasks run from task-specific capsules under `.task-context/`, never from the repository root. The Context Broker authorizes each requested path before a provider receives it.

Antigravity headless mode requires the prompt immediately after `--print`. `providers/antigravity.ts` constructs an argv array without a shell, injects verbatim broker-approved files, derives the effort setting from the model suffix, uses plan mode plus Antigravity's terminal sandbox, and consumes structured JSON output. The provider has no write allowlist during review; Mission Control persists its returned artifact.

The reproducible V2 integration demonstration uses:

```sh
./node_modules/.bin/tsx src/orchestrator/scripts/runAntigravityDemo.ts
./node_modules/.bin/tsx src/orchestrator/scripts/seedIntegrationDemo.ts
```
