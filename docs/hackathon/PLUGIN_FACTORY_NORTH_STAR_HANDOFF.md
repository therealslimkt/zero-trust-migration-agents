# Keraun Plugin Factory: North-Star Handoff

Status: **product direction locked; end-to-end demo path still in progress**  
Updated: 2026-08-31

## Product in one sentence

Keraun is an open-source enterprise agentic control plane that helps an
authorized migration engineer discover, create, verify, test, and download a
portable migration agent for legacy systems with expensive middleware,
licensing, binary formats, or difficult metadata translation.

It is not a generic chat UI, a collection of isolated "labs," or a claim that
Keraun can bypass vendor licences or access controls. It is a governed factory
for the data and metadata an enterprise is authorized to migrate.

## The user journey we are building

```text
Engineer request
      │
      ▼
Enterprise fleet discovery ── no match ──► bounded source research
      │                                        │
      ▼                                        ▼
Vetted existing cartridge                 declarative cartridge contract
      │                                        │
      └──────────────────► deterministic build + policy validation
                                             │
                                             ▼
                              sealed synthetic/authorized sandbox preflight
                                             │
                                  human review and digest-bound approval
                                             │
                                             ▼
                    Mission Control: source VM → compiler/Beam → BigQuery
                                             │
                                             ▼
                           signed portable Agent Plugin download
```

The initial three entries are **preloaded demonstration cartridges**, not a
separate product:

| Cartridge | Enterprise translation demonstrated | Required source inputs |
| --- | --- | --- |
| JDE EnterpriseOne on IBM i | CYYDDD / UPMJ dates, watermark-based incrementals | F9860/F98711 metadata, authorized JDBC driver such as JTOpen or supported Db2 driver |
| Microsoft Dynamics AX 2012 R3 | `RecId` inheritance flattening and orphan detection | SQLDICTIONARY/MODELELEMENT metadata, authorized Microsoft JDBC driver |
| Oracle EBS on Oracle 19c | Context-sensitive descriptive flexfields into typed columns | FND metadata, authorized `ojdbc8`-compatible driver |

They must use synthetic/deidentified seeds in the public demonstration. A
customer brings authorized source access, approved drivers/JARs, and their
metadata to a private execution boundary; no proprietary driver is committed
to this repository.

## Mission Control is the test environment

The factory page is intentionally a narrow **candidate verification** surface.
Its local action performs only deterministic, count-only synthetic evidence
checks. It does **not** prove an Apache Beam/Dataflow execution or a BigQuery
write.

After that gate, the authenticated Mission Control experience must present a
preloaded-cartridge selector and make an execution observable in three
synchronized, sanitized lanes:

| Lane | What the engineer sees | Safety boundary |
| --- | --- | --- |
| Source VM / sandbox | selected source contract, connection health, metadata discovery, approved query/result counts | no connection string, credentials, raw rows, or unrestricted shell |
| Agentic compiler / Apache Beam | selected transform contract, compiler decision, Flex Template job ID and bounded job events | no model-generated arbitrary code is executed; template/image/digest is allowlisted |
| BigQuery | target schema, job status, accepted/rejected/reconciled counts, lineage and final approval artifact | no raw customer values in public or shared event streams |

The UI must label each lane honestly: `planned`, `running`, `blocked`, or
`proven`. It must never animate a successful Beam or BigQuery result until a
backend event with a real job ID and reconciliation evidence exists.

## Agentic system design

This architecture follows the required ADK 2 division: predictable work is a
function node; reasoning uses an agent; every agent receives only the tools it
needs.

### 1. Discover a cartridge — collaborative pattern

Use an ADK 2 `single_turn` team. The request selects the relevant specialists
concurrently:

- **Registry locator** searches signed internal/enterprise fleet Agent Plugin
  manifests and A2A Agent Cards by capability, supported source and policy.
- **Source and metadata analyst** recognizes the source family and lists the
  minimum authorized metadata, drivers, extraction boundaries and watermark.
- **Governance reviewer** evaluates policy, data residency, human approval,
  supported connector and license constraints.

The coordinator returns a typed `discovery_result`: a verified match, a match
requiring review, or `research_required`. It does not construct commands or
connect to a source.

### 2. Research an unknown source — dynamic pattern

If discovery has no acceptable match, use a bounded dynamic research worker:

- decompose the question into no more than 3–7 source/metadata/CDC questions;
- recurse through `ctx.run_node` only to a fixed `MAX_DEPTH` (initially 2);
- retain citations, source confidence, licensing/driver constraints and open
  questions as artifacts;
- require approved sources and a human review before any proposed cartridge is
  buildable.

The model shapes research questions. Code enforces depth, width, time, source
allowlists, token/cost budgets, and the no-credentials boundary.

### 3. Compile a cartridge — graph pattern

Use a fixed ADK graph:

```text
START → parallel deterministic readers (seed/metadata/policy/template checks)
      → JoinNode → one compiler agent → schema validator
      → digest-bound human approval → sealed artifact build → verifier
```

The compiler agent emits a closed declarative migration contract, never an
executable shell command. Deterministic validators resolve allowed driver
references, target schema, high-water-mark semantics, PII policy, Beam template
version, container digest and BigQuery merge key. The present repository's
`agent_runtime/workflows/cartridge_provisioning.py` is the starting preflight
pattern; its approved plan remains sealed and verification-oriented.

### 4. Run and remember — runner + four memory categories

- **Working:** ADK Session state holds the current request, selected cartridge,
  exact contract digest and approval state.
- **Episodic:** Cloud SQL stores replayable run/event/audit state; GCS stores
  approved manifests, artifacts, evidence and reconciliation reports.
- **Semantic:** Vertex AI Memory Bank and governed BigQuery vector/search
  surfaces hold curated adapter facts and prior approved migration learnings.
- **Procedural:** versioned agent instructions, policy packs and Plugin skills
  state how the fleet may act.

Write and recall policies are mandatory: a completed or approved session is
written deliberately, and an agent recalls only governed facts via fixed tools.
The model never creates arbitrary SQL. It provides parameters to fixed,
audited BigQuery traversals.

## Portable plugin and A2A deliverable

A successful factory flow ends in a versioned Agent Plugins 1.0 package, not
only a screen result. The package must include a normative `plugin.json`,
component discovery, declared skills/tools, environment placeholders, semantic
version, SBOM, provenance, checksums and client-conformance evidence.

It should also publish/contain the appropriate A2A Agent Card describing the
agent identity, skills, authenticated endpoint requirements, supported source
contracts, data classification and input/output schemas. Environment values
are placeholders only; credentials and raw source information never ship in a
downloaded archive.

The current `plugin_factory/` is a deliberately inert reference-profile
validator. It validates a package tree and deterministic evidence without
activating MCP or executing package content. It is a supply-chain foundation,
not yet the downloadable migration plugin generated by the full flow.

## Cloud execution target

The source-emulator VM is private and sandboxed. Source containers run without
published ports and use gVisor; they never receive the Docker socket. A runner
agent makes only allowlisted actions against the VM/sandbox. Where stronger
isolation is required, Kata Containers can provide a per-workload micro-VM
boundary.

The real translation target is a hardened Apache Beam **Dataflow Flex
Template** container image in Artifact Registry. A Cloud Run/control-plane
backend creates a bounded execution inside the enterprise VPC only after the
digest-bound approval. BigQuery receives typed outputs and reconciliation/audit
records after a real job proves them. This is the path to demonstrate—not a
claim already made by a local fixture preflight.

## Current proof and next proof

| State | What is genuinely available now | What still requires evidence |
| --- | --- | --- |
| Preloaded examples | JDE, Dynamics AX, Oracle EBS synthetic data folders, source emulators, semantic seeds, fixed start scripts and deterministic count checks | live authorized customer source connection |
| Sandbox | private GCE runner VM and gVisor runtime; sealed synthetic evidence runner | VM-to-control-plane live execution event stream |
| Factory integrity | Agent Plugins reference validator, SBOM/provenance/checksum build and inert verifier | generated migration package with Agent Card and real client install/download |
| Local UI | `/factory` displays candidate contracts and can trigger a loopback-only synthetic preflight via the local runner | authenticated Mission Control selector and three live backend-driven terminal lanes |
| Cloud pipeline | architecture and target contracts defined | Vertex model trace, Dataflow job ID, BigQuery write/merge and per-lane reconciliation evidence |

## Immediate build sequence

1. Extend the hosted control plane to persist a factory request and approved
   cartridge candidate, then expose the three preloaded examples in the
   authenticated Mission Control selector.
2. Add a bounded runner-agent API that provisions/starts exactly the selected
   synthetic source on the private VM and streams sanitized backend events with
   a shared run ID.
3. Build one real JDE Beam Flex Template path first: source metadata and
   CYYDDD decoding → typed staging/final BigQuery tables → reconciliation.
4. Drive the three terminal lanes solely from those backend events; capture a
   Cloud Run URL, Vertex trace, Dataflow job ID, BigQuery job/table and audit
   row as submission evidence.
5. Repeat the same contract for AX and EBS; produce a signed/verified portable
   Plugin and A2A Card only after the package has the required components.

This document is the durable context handoff for subsequent implementation.
Use it together with `docs/hackathon/SUBMISSION_PLAN.md`; update both whenever
an intended component becomes live proof.
