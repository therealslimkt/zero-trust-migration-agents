# Zero-Trust Migration Agents

A governed agent fleet that migrates three legacy data formats—JDE/AS400,
SAP MaxDB, and Accpac/Btrieve—into BigQuery under one human approval. The
system is built for the **All Things Agentic Hackathon**.

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
