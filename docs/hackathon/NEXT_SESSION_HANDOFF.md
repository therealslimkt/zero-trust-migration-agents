# Start Here: Keraun’s Hackathon Finish Line

This is the first document for the next session. Read it before changing code.

## The north star

Keraun is an **open-source enterprise agentic control plane and Plugin
Factory**. An authorized migration engineer should be able to ask it to locate
a vetted migration agent in an enterprise fleet—or research and compile a new
one—then validate that agent in Mission Control before downloading a signed,
portable plugin.

The value is avoiding a permanent, expensive middleware path for sticky legacy
data systems while preserving authorization, licensing boundaries, human
approval, auditability, and reproducible translations. It never means bypassing
vendor licences, credentials, or application controls.

For the hackathon demo, the first preloaded cartridges are:

1. **Oracle JD Edwards EnterpriseOne 9.2 / IBM i** — decode `CYYDDD`/UPMJ
   dates and use UPMJ/UPMT as an incremental watermark.
2. **Microsoft Dynamics AX 2012 R3 / SQL Server** — resolve `RecId` table
   inheritance using AX metadata and reject orphan-derived records.
3. **Oracle EBS / Oracle 19c** — resolve descriptive-flexfield context and
   create typed output columns from FND metadata.

These are synthetic/deidentified source emulators in the demo. An enterprise
customer supplies authorized metadata, drivers/JARs and source access in its
private boundary.

## The demo judges need to see

```text
Engineer request
  → agent fleet finds/researches a cartridge
  → selected cartridge passes deterministic sandbox verification
  → one digest-bound human approval in Mission Control
  → three synchronized, backend-driven terminal lanes:
       private source VM | agentic compiler + Apache Beam | BigQuery
  → reconciled result and verified portable Agent Plugin/A2A Card download
```

Every visible state must originate in a persisted backend event. No timer,
generated terminal text, random number, or decorative success animation may
stand in for a VM action, Vertex call, Beam/Dataflow job, or BigQuery write.

The three terminal lanes must retain only sanitized content:

- source VM: selected cartridge, health, approved metadata/query outcome and
  count/digest—not raw records, SQL credentials or connection strings;
- compiler/Beam: declarative transform, approved template/image digest, job ID
  and bounded job events—not model chain-of-thought or arbitrary executed code;
- BigQuery: table/schema/job ID/reconciliation counts and lineage—not raw
  customer values.

## What is true right now

- `main` includes M8’s tested Plugin Factory checkpoint.
- `/factory` displays JDE, Dynamics AX and Oracle EBS preloaded synthetic
  candidates; `/lab/m4` redirects there.
- `./scripts/start_local_cartridge_ui.sh` starts a loopback-only local agent
  and UI. Its one permitted action runs fixed Docker evidence checks and emits
  count-only synthetic results.
- A private gVisor-protected GCE VM, `keraun-cartridge-lab`, exists for the
  synthetic source-emulator runner. See
  `docs/cartridges/M7_LIVE_CARTRIDGE_RUNTIME.md` and
  `cloud_architecture/CLOUD_RESOURCE_MANIFEST.md`.
- Firebase is active for project `ztm-agent-9049c3`; no hosted Cloud Run judge
  experience has been deployed or verified yet.
- The repository has a safe, inert Agent Plugins reference validator with
  SBOM/provenance/checksum generation. It is **not** yet a generated migration
  Plugin nor an A2A Agent Card.
- There is no proven Vertex model invocation, Dataflow job, migration BigQuery
  result, or backend event stream that represents the desired JDE/AX/EBS run.

The canonical detailed architecture is
[`PLUGIN_FACTORY_NORTH_STAR_HANDOFF.md`](PLUGIN_FACTORY_NORTH_STAR_HANDOFF.md).
The M8 delivery record is
[`delivered/milestone_8_delivery_report.md`](../../delivered/milestone_8_delivery_report.md).

## Non-negotiable ADK 2 design

| Need | Pattern | Bounded implementation |
| --- | --- | --- |
| Find an existing cartridge | Collaborative `single_turn` team | Registry Locator + Source/Metadata Analyst + Governance Reviewer; typed `match`, `review_required`, or `research_required` result |
| Understand an unknown source | Dynamic worker | bounded decomposition, `ctx.run_node` recursion, fixed width and `MAX_DEPTH=2`, citations/artifacts, no source mutation |
| Compile a candidate | Graph | deterministic metadata/policy/template functions fan out → `JoinNode` → one compiler agent emits a closed declarative contract → validator → digest-bound approval |
| Execute and observe | Runner + long-running approval | session-backed run, persisted event/artifact/audit data, only allowlisted runner and Dataflow actions after approval |

Memory must be explicit: ADK Session for working state; Cloud SQL/GCS for
episodic runs/artifacts; Memory Bank and governed BigQuery for semantic facts;
versioned instructions/policy packs for procedural memory. Models supply
parameters to fixed tools and queries; they do not construct arbitrary shell
commands or SQL.

## Next few hours: ordered execution plan

### 1. Establish cloud facts and deploy the judge control plane

Read `cloud_architecture/HOSTED_DRAFT.md`, then inventory the project. Create
only the minimal, documented Cloud Run/Firestore/Secret Manager resources
needed for the hosted UI. Configure the existing Firebase web app, Google
sign-in and allowed Cloud Run domain. Deploy one `--max-instances=1` Cloud Run
revision and test it from an incognito browser.

Record every resource mutation immediately in
`cloud_architecture/CLOUD_RESOURCE_MANIFEST.md` with a Console link, region,
purpose, cost/safety boundary and real deployment digest. Do not use browser
direct Firestore access or service-account keys.

**Proof required:** public/credentialed Cloud Run URL, login, invited viewer
read-only behavior, admin mutation behavior, hard refresh persistence.

### 2. Make Mission Control the one true UI

Persist a `selected_cartridge` in the authenticated backend run model. Add the
three-item selector in Mission Control (JDE, AX, EBS), not a second standalone
workflow. Selecting a candidate starts only its preflight stage; the launch
remains approval-gated.

Wire source/Beam/BigQuery terminal panes exclusively to persisted sanitized
events with a shared run ID. The existing local preflight is an input to this
flow, not the outcome. If a producer is absent, show `not configured` or
`planned` explicitly.

**Proof required:** one browser run whose selector, lane statuses and terminal
frames all survive refresh and are backed by server events.

### 3. Prove one complete JDE path before broadening

Build a fixed JDE Apache Beam Dataflow Flex Template in Artifact Registry.
Use only the source metadata and driver contract declared for the synthetic
emulator; keep the template/image digest allowlisted. Create the typed BigQuery
staging/final/audit tables with explicit schema. Execute after one exact
digest-bound approval and reconcile source, accepted, rejected and destination
counts.

**Proof required:** real Vertex model/trace (Gemini version meeting the
hackathon requirement), Dataflow job ID, BigQuery job/table, audit row and
reconciliation report—visible in Mission Control.

### 4. Add AX and EBS as equivalent, honest lanes

Reuse the same sealed runner and event contract for AX inheritance/`RecId` and
EBS flexfield translation. Do not copy a JDE success state into either lane.
If time prevents live execution, show the correct verified preflight state and
call it incomplete; the final submission target remains three real lanes.

### 5. Close the plugin-factory loop

Have the compiler produce a package with normative Agent Plugins 1.0 manifest,
component discovery, skills/tools, environment placeholders, semantic version,
SBOM, provenance and checksums. Generate an A2A Agent Card with skills,
schemas, authentication requirement, data classification and supported source
contract. Validate it with the repository verifier before the UI offers a
download.

## Important repository hygiene

- Before each milestone: `git fetch origin`, switch/update `main` with
  `git pull --ff-only`, create a fresh milestone branch, and never overwrite
  unrelated work.
- Before each pause: run focused tests plus relevant build/lint, write matching
  detailed reports in repository `delivered/` and workspace-root `delivered/`,
  push, then fast-forward merge to `main` after review.
- Preserve the user-owned untracked `.firebaserc`, `firebase.json`, and
  `firestore.rules`; do not commit, alter or remove them without explicit
  instruction.
- Never claim deployment or a cloud result without direct evidence. Update the
  cloud manifest as part of—not after—every actual cloud change.

## First commands for the new session

```bash
cd /Users/kohalloran/Documents/hackathons/all_things_agentic/zero-trust-migration-agents
git switch main
git pull --ff-only
git status --short
sed -n '1,260p' docs/hackathon/NEXT_SESSION_HANDOFF.md
sed -n '1,260p' docs/hackathon/PLUGIN_FACTORY_NORTH_STAR_HANDOFF.md
```

Then inventory actual Google Cloud state before selecting the smallest honest
end-to-end JDE proof slice.
