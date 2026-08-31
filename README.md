# Keraun — Open Enterprise Migration Plugin Factory

Keraun is an open-source enterprise agentic control plane that helps authorized
engineers discover, build, verify, test, and package portable migration agents
for difficult legacy data systems. It is being built for the **All Things
Agentic Hackathon** under the **Fortified Enterprise Fleet** category.

The current preloaded demonstration target is **JD Edwards EnterpriseOne on
IBM i, Microsoft Dynamics AX 2012 R3, and Oracle EBS on Oracle 19c**. Their
synthetic source emulators exercise CYYDDD/UPMJ date handling, `RecId`
inheritance, and descriptive-flexfield translation respectively. See
[the next-session hackathon handoff](docs/hackathon/NEXT_SESSION_HANDOFF.md)
for the authoritative product path and proof gates.

> Historical note: the older local M3/M4 control-plane baseline below still
> refers to SAP MaxDB and Accpac/Btrieve. Those are retained implementation
> artifacts, not the current demo scope or submission narrative. Do not use
> them in the final video, Devpost copy, or newly built Mission Control flow.

The business problem is not merely parsing old files. Enterprises otherwise
maintain three middleware and licensing paths to move the same class of legacy
customer data. This project replaces that fragmented path with one auditable
migration portfolio:

1. private edge readers fetch all three exports through Tailscale MagicDNS;
2. deterministic protection plus local Gemma review prevents raw PII from
   leaving the edge;
3. Gemini 3.5 Flash compiles schema-validated declarative plans for all three
   sources;
4. one exact portfolio digest waits for a human decision in Mission Control;
5. a fixed Dataflow Flex Template writes only approved protected rows; and
6. BigQuery counts, lineage, reconciliation, and `migration_audit` must all
   agree before the portfolio completes.

Generated code is never evaluated. See [ARCHITECTURE.md](ARCHITECTURE.md) and
[the trusted cloud runtime](docs/execution/MILESTONE_4_TRUSTED_CLOUD_RUNTIME.md).

## For judges — start here

**Hosted UI:** <https://keraun-mission-control-322558310296.us-central1.run.app> — served
from Cloud Run in project `ztm-agent-9049c3`, no login required.

That deployment is deliberately **static and inert**: it holds no credentials, has no source
access, and cannot launch a billable action. The `/factory` **Run evidence** control needs the
loopback-only local agent, so live execution happens on *your* machine against *your* Vertex
project — which is the whole premise, since legacy source data must never leave the owner's
perimeter. Use the three steps below for the live path.

Everything in these three steps was executed and captured on 2026-08-31; see
[`docs/evidence/`](docs/evidence/).

### Step 1 — install (≈3 min)

Prerequisites: Python 3.11+, Node.js 24+, npm, Docker Desktop (running).

```bash
git clone https://github.com/therealslimkt/zero-trust-migration-agents
cd zero-trust-migration-agents
python3 -m venv venv
venv/bin/pip install -r requirements.txt
(cd studio && npm install)
```

### Step 2 — see the three legacy cartridges detect their signature defect (≈2 min)

```bash
./scripts/start_local_cartridge_ui.sh
```

Open **<http://127.0.0.1:5173/factory>** and press **Run evidence**.

This is live execution, not a fixture: the browser calls a loopback-only sealed agent, which
starts three synthetic source emulators on an **internal-only Docker network with no egress**,
plus one evidence runner that is the only container permitted to query them. Expect:

```json
{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,
 "checks":{"jdeInvalidCyyddd":1,"axOrphanDerived":2,"ebsUnmappedFlexfield":1}}
```

| Cartridge | Emulated source | Defect detected |
| --- | --- | --- |
| JDE | JD Edwards EnterpriseOne 9.2 / IBM i | invalid `CYYDDD` Julian date |
| AX | Dynamics AX 2012 R3 / SQL Server | orphan-derived `RecId` |
| EBS | Oracle E-Business Suite / Oracle 19c | unmapped descriptive flexfield |

Only **counts** cross the boundary — never raw records, credentials, or connection strings.
The payload asserts `synthetic: true`: these are deidentified emulators reproducing the
structural pathologies of those systems, not licensed vendor databases.

You can also run the same pass headlessly:

```bash
./scripts/run_local_cartridge_evidence.sh
```

### Step 3 — confirm Gemini 3.5 on Vertex AI (≈1 min)

Requires your own Google Cloud project with the Vertex AI API enabled, and
`gcloud auth application-default login`.

```bash
GOOGLE_CLOUD_PROJECT=<your-project> venv/bin/python - <<'EOF'
import asyncio, os
from google.antigravity import Agent, LocalAgentConfig
async def main():
    cfg = LocalAgentConfig(model="gemini-3.5-flash", vertex=True,
                           project=os.environ["GOOGLE_CLOUD_PROJECT"],
                           location="us", tools=[],
                           system_instructions="Reply with exactly the token you are asked for.")
    async with Agent(config=cfg) as a:
        r = await a.chat("Reply with exactly: KERAUN_VERTEX_OK")
        print((await r.text()).strip())
asyncio.run(main())
EOF
```

Expected output: `KERAUN_VERTEX_OK`.

> `gemini-3.5-flash` is served from the `global`, `us`, and `eu` endpoints — **not**
> `us-central1`. A request pinned to `us-central1` returns 404.

### What is and is not proven

| Claim | Status |
| --- | --- |
| Gemini 3.5 Flash executes on Vertex AI | **proven** — [evidence](docs/evidence/VERTEX_GEMINI_3_5_PROOF.md) |
| Three cartridges detect their signature defect in sealed sandboxes | **proven** — [evidence](docs/evidence/THREE_CARTRIDGE_EVIDENCE.md) |
| gVisor-isolated private source host on Compute Engine, no external IP | **deployed** — `keraun-cartridge-lab` |
| ADK 2 collaborative / dynamic / graph orchestration | **implemented and unit-tested**; not yet exercised end-to-end in one cloud run |
| Clustered binary export decoded and loaded into BigQuery | **proven** — [evidence](docs/evidence/CLUSTERED_BINARY_TO_BIGQUERY.md) |
| Hosted UI on Cloud Run | **deployed** — static/inert by design |
| Dataflow job and portable plugin download | **not executed** — do not treat as complete |

We would rather show you a smaller proven surface than a larger claimed one.

## Local verification

Prerequisites are Python 3.11+, Node.js 24+, npm, and Go 1.24+.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cd studio && npm install && cd ..

venv/bin/python -m scripts.verify_python_gate
(cd studio-backend && go test ./... && go test -race ./... && go vet ./...)
(cd studio && npm run build && npm run lint && node src/mission-control/model.test.ts)
```

The Python gate runs the complete suite first and stops on failure; it runs the
focused M4 suite and prints `PYTHON TEST GATE PASSED` only after the complete
suite succeeds. These gates use local fakes for Google Cloud adapters and do
not create cloud resources. The Dataflow image/spec build, IAM, APIs, buckets,
tables, and live jobs remain a separate deployment/cost approval.

## Run the real three-lane approval flow

> **Not the judge path.** This section requires private Tailscale/MagicDNS reachability to
> source hosts that are not part of the current demonstration set, so it cannot be reproduced
> from a clean clone. It is retained for contributors with that environment. Judges should use
> [For judges — start here](#for-judges--start-here) instead.


Use independent printable tokens for browser/API traffic and the loopback-only
Python orchestration bridge:

```bash
export MISSION_CONTROL_STATE_PATH=/private/tmp/ztm-mission-control.json
export MISSION_CONTROL_API_TOKEN='<local-demo-api-token>'
export MISSION_CONTROL_ORCHESTRATOR_TOKEN='<different-local-orchestrator-token>'

(cd studio-backend && go run .)
```

In a second terminal, start the loopback-only Vite BFF. The token is held by
the server process and is never compiled into browser JavaScript:

```bash
export MISSION_CONTROL_API_TOKEN='<local-demo-api-token>'
cd studio
npm run dev
```

With the three MagicDNS sources reachable and Google ADC configured, prepare a
live portfolio. This command stops at the approval boundary and writes the
protected snapshot with mode `0600`:

```bash
venv/bin/python -m scripts.verify_m3_control_plane plan \
  --snapshot /private/tmp/ztm-prepared.json \
  --project '<gcp-project>' \
  --location us \
  --model gemini-3.5-flash \
  --mission-control-url http://127.0.0.1:8080
```

Open `http://127.0.0.1:5173/?runId=<runId-from-command>` and approve the exact
portfolio digest once. Mission Control displays all three migrations
simultaneously; counters come from its durable run snapshot and evidence comes
from its persisted SSE event log.

## Trusted cloud execution

Before a live M4 canary, render the exact approved target schemas and pre-create
the three target tables plus `migration_audit`:

```bash
venv/bin/python -m scripts.render_m4_bigquery_schemas \
  --snapshot /private/tmp/ztm-prepared.json \
  --digest 'sha256:<approved-digest>' \
  --dataset legacy_migration \
  --output-dir /private/tmp/ztm-bigquery-schemas
```

`venv/bin/python -m scripts.run_m4_cloud --help` lists the explicit bucket,
Flex spec, worker identity, private subnetwork, digest-pinned SDK image, and proof-output
arguments. Pass `--mission-control-url http://127.0.0.1:8080` to consume the
durable UI-recorded approval and publish Dataflow, BigQuery, reconciliation,
and audit evidence back to the three lanes. Successful proof contains only
resource identifiers, counts, and digests—never rows, credentials, or the
approver identity.

The reproducible image/spec build is [cloudbuild.dataflow.yaml](cloudbuild.dataflow.yaml),
but running it mutates Google Cloud and can incur cost. Do not run it merely to
perform local verification.
