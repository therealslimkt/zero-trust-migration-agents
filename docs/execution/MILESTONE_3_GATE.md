# Milestone 3 gate

Status: **PASSED**

Milestone 3 converts the three protected edge outputs into one immutable,
Gemini-planned portfolio, blocks on a digest-bound human approval, executes
only a closed transformation language, and persists authenticated portfolio
state and ordered evidence.

## Delivered trust path

1. `SourceManifest`, `RecordBatch`, and `RedactionReport` builders validate and
   snapshot every source artifact without retaining raw legacy bytes.
2. Gemini 3.5 Flash runs through the Antigravity SDK on the Vertex AI `us`
   endpoint. It receives only sanitized/tokenized contract documents and
   returns structured declarative drafts.
3. Code-owned validation supplies IDs, targets, source references, plan
   digests, and the canonical three-plan portfolio digest. Gemini cannot emit
   code, tools, commands, SQL, expressions, or an execution claim.
4. The portfolio workflow snapshots all three sources as one canonical JSON
   approval anchor. Caller mutations cannot change the stored digest.
5. Approval requires the exact run and portfolio digest plus an explicit
   policy-finding set. Non-overridable denials are checked before snapshot or
   batch work.
6. The trusted interpreter supports only `rename`, `cast`, and `drop`. It has
   no dynamic evaluation path and returns immutable protected rows plus
   reconciliation digests.
7. The Go control plane provides bearer-authenticated create/get/approval/SSE
   APIs, constant-time credential and digest comparisons, strict bodies,
   bounded resumable events, closed problem responses, a frozen state machine,
   and atomic `0600` JSON persistence with file and directory fsync.
8. Legacy unauthenticated broadcast and WebSocket routes are not mounted.

## Live approval canary

Run: `mig_b858c16c2f614722b844`

Approved portfolio digest:
`sha256:1af7f87c6651cdfd2b2a955b7c733ba10ae74b65cfa4960df8f33de775f9b4d4`

The user approved that exact digest. A deliberately wrong digest was rejected
before execution. The accepted snapshot was owner-only (`0600`) and contained
protected artifacts, never raw source bytes or pre-redaction values.

| Source | Live input | Protected findings | Unresolved | Trusted rows | Target | Output digest |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| JDE | 4 | 8 | 0 | 4 | `legacy_migration.jde_f0101` | `sha256:1b2c320c58094e95cb87aa0cafcda49a15334a24049768969c8a14208b45e838` |
| MaxDB | 4 | 12 | 0 | 4 | `legacy_migration.sap_kna1` | `sha256:7692361c89169382f99b64e8ec54d322f6b613d25e1ee25196882273a78e8162` |
| Btrieve | 1 | 2 | 0 | 1 | `legacy_migration.accpac_arcus` | `sha256:9e377a7705e9885cc9ff301ccb1d6b62bd3885636700dbf44a9232b6407a3d9d` |

After the security-review repairs, the same approved snapshot produced the
same counts and output digests.

Detailed evidence:

- `docs/execution/evidence/m3-live-planning-canary.json`
- `docs/execution/evidence/m3-gemini-security-review.md`

## Independent review

Gemini's initial read-only security review returned FAIL for optional policy
findings and reachable legacy broadcast routes. Both were repaired. The
follow-up review returned PASS with no blocking findings. It also confirmed
that Python and Go compute the same canonical portfolio digest and accepted
the bounded `Last-Event-ID` SSE replay design.

## Gate checks

- `python -m pytest -q`: **220 passed**
- `go test -race ./...`: **passed**
- `go vet ./...`: **passed**
- `npm run lint` in `studio/`: **passed**
- Approved live three-source execution: **3/3 passed**
- Independent Gemini security re-review: **PASS**

Pytest reports one existing third-party Pydantic settings warning about an
unresolved `lifespan` forward reference. It does not affect the migration
contracts or gate result.

## Truth boundary for Milestone 4

This milestone proves protected planning, human approval, trusted in-memory
interpretation, durable state semantics, and reconciliation digests. It does
not claim that Dataflow ran, that BigQuery rows exist, or that the new Mission
Control UI is deployed. Milestone 4 must implement and visibly prove those
cloud and presentation outcomes without replacing any real state with timers
or synthetic success messages.
