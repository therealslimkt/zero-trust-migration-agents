# Milestone 5 authenticated workflow UI test plan

## Safe reuse decision

The four requested divergent branches are historical inputs, not integration
tips. Their useful content is already present on `origin/main` through later
cherry-picks and hardening commits:

- Gemini public pages are present with later routing and truthfulness fixes.
- Gemini visual primitives are present with later Keraun theme polish.
- Protected pages are present behind the joined authentication shell.
- Firebase authentication is present with safe return navigation and a
  development-only loopback demo adapter.

Do not cherry-pick those old branch tips. Doing so risks reverting the joined
router, local-demo isolation, protected route behavior, terminal streams,
theme refinements, and fixture-lab truth boundary.

## Current truth boundary

`/lab/m4` remains a public, read-only view of three checked-in synthetic
cartridge packets. It is not an authenticated run and does not call a live
backend. `/dashboard`, `/runs/:runId`, source detail, onboarding, and cloud
settings are private routes.

The frozen web v1 `LiveRunEvent` currently carries sequence, state, summary,
and evidence references, but not v2 node work class, `modelCall`, deterministic
component identity, checkpoint reference, or interrupt binding. The UI must not
infer those facts from agent names, tool labels, prose, or timestamps.

This lane adds a closed `WorkflowEvidencePanel` seam. Until a frozen private
API supplies its typed projection, the protected source view states that
workflow evidence is unavailable and withholds all derived counts. When a
projection is supplied, the panel accepts only contiguous persisted events and
keeps model calls, deterministic functions, and approval interrupts visibly
distinct. Approval interruptions must name `approval_endpoint`; generic input
or A2A content cannot be shown as approval proof.

## Required tests after the private projection freezes

### 1. Authentication and ownership

- Anonymous access to every private route redirects to `/login` with a safe
  same-origin return path.
- Local demo auth is selectable only in Vite development plus
  `VITE_LOCAL_DEMO=true`; production cannot select its public loopback token.
- Every private request and stream reconnect obtains a current identity token.
- A valid token for a different owner receives no run, event, approval, or
  artifact data.
- Signing out aborts streams, clears private query caches, and makes browser
  back-navigation unable to reveal private state.

### 2. Persisted event replay

- Start with ordered PostgreSQL-backed events, disconnect after sequence N,
  reconnect with the exact cursor, and prove each event appears once.
- Duplicate event IDs are ignored only when their bodies agree; conflicting
  reuse is an error.
- Gaps, reordering, malformed event bodies, and a cursor outside the authorized
  run fail closed and display stale/rejected state rather than a synthetic
  continuation.
- Browser refresh reconstructs the same timeline and counts from persisted
  events, not component memory or timers.

### 3. Approval and interruption evidence

- Simulation and production interruptions render as separate subjects.
- Pending approval shows the exact checkpoint/subject binding without claiming
  an approver or decision.
- Approved/rejected evidence appears only with a persisted approval ID and
  digest; stale, cross-run, and cross-tenant records are rejected.
- Clarification/task input is never labeled approval, and approval content sent
  through the input route never unlocks the UI.
- The production approval event is followed only by deterministic evidence;
  any later model-call event is a blocking integrity alert.

### 4. Model-call versus deterministic evidence

- `modelCall=true` requires model work class, agent identity, and model-call
  evidence. Deterministic/control-flow entries require a deterministic
  component and must set `modelCall=false`.
- Prisma repair may appear as a bounded pre-approval model call. Prisma
  validation, policy, Vale, Flow, Ledger, and Forge appear as deterministic.
- Counts are computed only from accepted persisted entries. Narration,
  terminal frames, fixture labels, and loading placeholders contribute zero.
- A model-call event after the production seal produces an explicit failure,
  never a green zero-call badge.

### 5. Keraun light, dark, responsive, and accessibility gates

- Exercise login, dashboard, one source, workflow replay, pending approval,
  rejected evidence, and reconnecting state in dark and light themes.
- Run desktop 1440x900, tablet 768x1024, and mobile 390x844 with reduced
  motion. Persist the selected `ztm-theme` across reload.
- Verify keyboard-only sign-in, tabs, workflow list, approval controls, and
  focus restoration after navigation.
- Run axe and require zero critical or serious violations. Check contrast for
  muted text and every Google-color badge in both themes.
- Assert status is never color-only; labels, icons, sequence, and decision text
  remain available to assistive technology.

## Recommended commands and evidence

After dependencies are installed in the integration worktree:

```bash
npm test -- src/web/features/auth src/web/pages/protected \
  src/web/pages/lab src/web/client.test.ts
npm run lint
npm run build
npm run test:e2e
```

For the manual loopback flow, use an owner-only synthetic control-plane
snapshot generated by the repository verifier:

```bash
npm run dev:demo -- --state /private/tmp/<verified-run>/synthetic-control-plane.json
```

Capture the login screen, authenticated dashboard, source evidence tab,
reconnect cursor, pending and resolved approval states, model/deterministic
counts, both themes, and the exact test output. Keep M4 screenshots labeled
`LOCAL FIXTURE LAB`; never mix their cartridge digests with live-run evidence.

## Remaining risks

- The private orchestration projection and mapping adapter are not frozen or
  implemented in this lane; ready-state inspector evidence is test-injected.
- Existing web source IDs remain `jde`, `maxdb`, and `btrieve`. This lane does
  not rename or widen them to the M4 cartridge IDs.
- Existing protected replay detail can contain synthetic raw hex and decoded
  sample values. The backend must continue to prove ownership and data class;
  production raw customer values must not be projected into this UI contract.
- Dataflow and BigQuery sections are meaningful only when authenticated server
  evidence exists. The M4 fixture lab provides no such evidence.
- Claude Opus 5 review was unavailable because managed policy denied external
  repository transfer. An approved final review remains required.
