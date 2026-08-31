# Record now — shot list and submission copy

Everything below is backed by something that actually runs. Nothing here is aspirational.

## Before you hit record (5 min)

```bash
# Terminal 1 — UI already running at http://127.0.0.1:5173
# Terminal 2 — have this ready to paste, do NOT run it yet:
cd ~/Documents/hackathons/all_things_agentic/zero-trust-migration-agents
./scripts/run_local_cartridge_evidence.sh

# Terminal 3 — have this ready to paste, do NOT run it yet:
venv/bin/python /tmp/keraun_vertex_probe.py
```

Browser tabs, pre-opened and logged in, in this order:
1. `http://127.0.0.1:5173/factory`
2. Cloud Console → **Compute Engine → VM instances**, project `ztm-agent-9049c3`
3. Cloud Console → **BigQuery** → `keraun_m6_audit`
4. Cloud Console → **Vertex AI** dashboard

Hide bookmarks, notifications, billing, and your email. 1440x900. One continuous take —
the criterion is *"unedited, live execution."* Trim only dead air at the ends.

---

## Shot list — target 3:48, hard stop 4:00

**Hosted URL (the star of the demo):**
`https://keraun-mission-control-322558310296.us-central1.run.app`

**Why anything runs locally at all — say this on camera, it is a feature not a gap.**
The UI and control plane are hosted on Google Cloud. The *sandbox that touches legacy source
data* runs inside the operator's own perimeter, because the entire premise is that raw legacy
data never leaves it. A hosted button that could reach into your ERP would contradict the
product. So: hosted UI, hosted Vertex reasoning, hosted BigQuery destination — local sealed
sandbox, by design.

### Tab setup before you record

1. `https://keraun-mission-control-322558310296.us-central1.run.app/factory` ← hosted
2. `https://keraun-mission-control-322558310296.us-central1.run.app/architecture.html` ← hosted
3. `http://127.0.0.1:5173/factory` ← local, only for the live **Run evidence** click
4. Cloud Console → BigQuery → `keraun_demo.sap_kna1_clustered`
5. Cloud Console → Compute Engine → VM instances
6. Terminal, in the repo, venv ready

**Do not show a sign-in button.** Say "read-only hosted UI, no login required."

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | **Hosted** `/factory` — the three bad guys | "Every legacy ERP migration buys a permanent middleware path. JD Edwards dates aren't dates. Dynamics AX rows inherit from parents that may not exist. Oracle EBS hides real columns behind flexfields. Three systems, three bespoke pipelines, forever." |
| 0:20–0:45 | **Hosted** — scroll the 01–04 lifecycle rail | "This is Keraun, running on Cloud Run in project ztm-agent-9049c3. The unlikely hero is the legacy-ERP migration engineer. Agents here are catalogued, not hard-coded — you search the registry for your system, and if it isn't there a long-running agent researches it, a human promotes it, and the next engineer's search finds it." |
| 0:45–1:15 | **Hosted** — click through the three cartridge tabs | "Each cartridge declares a source contract, a transform spec, and a reconciliation digest before it is allowed anywhere near a migration. Note what the page says about itself: this is a preflight gate, and passing it produces a candidate, never a published agent." |
| 1:15–2:00 | **Switch to local tab**, click **Run evidence**, let it finish | "The UI is hosted, but the sandbox that touches source data runs inside your own perimeter — that's the whole point. Watch it live: three sealed emulators on an internal-only network with no egress, and one evidence runner that is the only thing allowed to query them." — when the JSON lands — "Invalid CYYDDD date in JDE. Two orphan-derived RecIds in AX. An unmapped flexfield in EBS. Counts only, and the payload asserts synthetic true." |
| 2:00–2:50 | **Terminal** — `venv/bin/python scripts/demo_cluster_to_bigquery.py --load` | "Now the hardest case. A SAP-style cluster export where every record is its own compressed blob — point a warehouse loader at this and you get one opaque BYTES column." — as it scrolls — "Code-owned adapters check the magic number, then each record's length and CRC32 *before* decompressing. Out come typed columns, each tagged with a data class the redaction policy keys off. And it lands in BigQuery: four decoded, four loaded, reconciled." |
| 2:50–3:10 | **Cloud Console** — BigQuery table, then run the query | "Straight back out of BigQuery in the same project. Hexadecimal to typed warehouse columns, end to end, with a real load job ID." |
| 3:10–3:30 | **Terminal** — Vertex probe | "The reasoning runs on Gemini 3.5 Flash through Vertex AI, via the Antigravity SDK. Live call. The model may choose rename, cast, or drop — it may never emit or execute code. Deterministic code owns identifiers, digests, and schema validation, and execution is gated behind one human approval bound to an exact plan digest." |
| 3:30–3:40 | **Cloud Console** — Compute Engine VM list | "And the source host runs under gVisor with no external IP." |
| 3:40–3:48 | **Hosted** `/architecture.html` | "One governed fleet, three legacy sources, sanitized evidence end to end — instead of three permanent middleware paths. Open source, hosted on Google Cloud, runs in your own project." |

### The three claims, and where each is proven on screen

| Claim | Proven by |
|---|---|
| **Discoverable** | the 01–04 lifecycle rail; three catalogued cartridges; A2A Card + Agent Plugin as the promotion output |
| **Secured** | sealed emulators, internal-only network, single permitted querier, count-only output, `synthetic:true`, gVisor + no external IP in Console |
| **Governed** | deterministic gates panel, the page's own "not yet execution proof" disclaimer, digest-bound human approval, no auto-promotion |

**Honesty guardrails.** Say "synthetic, deidentified emulators" — never imply licensed
production JDE/Dynamics/EBS databases. Do **not** claim a completed BigQuery migration run;
the BigQuery tab is the sanitized audit stream. Do not say the product bypasses vendor
licensing. If you show the three-lane Mission Control, label it `planned` — it is not backed
by a real run today.

---

## Devpost — copy/paste

**Category:** Fortified Enterprise Fleet

**Elevator pitch (200 char max):**
> A governed multi-agent fleet that migrates sticky legacy ERP data — JDE, Dynamics AX, Oracle EBS — without buying a permanent middleware path for each one.

**About the project:**

> **The friction.** Enterprises run decades-old ERP systems whose data is hostile by design.
> JD Edwards stores dates as `CYYDDD` Julian integers. Dynamics AX splits one logical record
> across an inheritance chain keyed by 64-bit `RecId`s that can orphan. Oracle EBS hides
> meaningful columns behind descriptive flexfields whose meaning lives in a separate metadata
> catalog. Today each one gets its own bespoke, permanently-licensed middleware path. The
> person maintaining them — the legacy migration engineer — is our unlikely hero.
>
> **What Keraun does.** Keraun is an open-source enterprise agentic control plane. A fleet of
> bounded specialist agents inventories a legacy source, profiles its schema, and compiles a
> *closed declarative transform contract*. A human approves one exact plan digest. Only then
> does a pre-registered trusted runner execute. Every visible state originates in a persisted
> backend event.
>
> **The security property that matters.** The model never emits or executes code. It selects
> parameters for fixed, allowlisted operations. Source emulators run sealed under gVisor on a
> private Compute Engine host with no external IP, on an internal-only network. Only
> count-level sanitized evidence crosses into the cloud — never raw records, credentials, or
> connection strings.
>
> **Architecture.** Built on ADK 2 with all three orchestration patterns: a **collaborative
> `single_turn`** team for source discovery, a **dynamic** worker with bounded recursion
> (`MAX_DEPTH=2`) for unknown sources, and a **graph** with deterministic fan-out into a
> `JoinNode` for compilation. Reasoning is an agent node; validation, routing, policy,
> approval, and reconciliation are deterministic function nodes. Memory is explicit across
> four tiers: ADK Session (working), Cloud SQL/GCS (episodic), governed BigQuery (semantic),
> versioned instruction and policy packs (procedural).
>
> **Technologies.** Gemini 3.5 Flash on Vertex AI via the Antigravity SDK (0.1.14); Google
> ADK 2.7.1; Google Cloud — Compute Engine (gVisor), BigQuery, Cloud Run, Firestore, Secret
> Manager, Artifact Registry; Gemma 2 running locally as an edge-side residual privacy
> reviewer; Go control plane with SSE; React + Vite + TypeScript Mission Control.
>
> **Data sources.** All demonstration data is synthetic and deidentified. The emulators
> reproduce the *structural* pathologies of JDE EnterpriseOne 9.2 / IBM i, Dynamics AX 2012 R3
> / SQL Server, and Oracle EBS / Oracle 19c. No licensed vendor database is used or required,
> and nothing here bypasses vendor licensing or application controls.
>
> **What we learned.** The hard part of an enterprise agent fleet is not model capability —
> it is authority. Almost every design decision came down to keeping the boundary in code:
> bounding recursion width and depth, refusing to let session state carry approval, binding a
> human decision to an exact digest, and failing closed when evidence is missing. We also
> learned to distinguish "the code exists" from "there is durable evidence it ran," and to
> label anything unproven as such.
>
> **Built with AI assistance.** Bounded coding agents worked in isolated branches with
> cross-review and tests before integration. They are tools, not team members. Project code
> was created during the submission period; first commit August 23, 2026.

**Repository:** https://github.com/therealslimkt/zero-trust-migration-agents

**Social post (X / LinkedIn):**
> Built Keraun for #AllThingsAgenticHackathon: an open-source agent fleet that migrates
> sticky legacy ERP data (JD Edwards, Dynamics AX, Oracle EBS) without a permanent middleware
> path for each one. Gemini 3.5 on Vertex AI plans declaratively — it never executes code.
> Sealed gVisor source emulators, one digest-bound human approval, sanitized evidence only.
