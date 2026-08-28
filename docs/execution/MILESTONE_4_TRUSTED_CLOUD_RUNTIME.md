# Milestone 4: Trusted Dataflow and BigQuery Runtime

Status: **implemented and locally verified; cloud deployment and live proof pending approval**

## What this runtime does

The Milestone 3 interpreter remains the only component that applies a
declarative transform plan. After the complete portfolio is approved, this
runtime:

1. revalidates the exact run, portfolio digest, approval, source order,
   registered targets, output schemas, protected-cell markers, record counts,
   and output digests;
2. serializes exactly three small canonical bundles containing sanitized or
   tokenized output only;
3. stores each bundle at a content-addressed Cloud Storage object using a
   create-only precondition, accepting a retry only after a byte-for-byte
   equality check;
4. launches one fixed Dataflow Flex Template per source with typed parameters,
   a dedicated worker service account, private worker IPs, blocked project SSH
   keys, bounded autoscaling, and no generated code;
5. recovers a prior job by its deterministic name before launching, and refuses
   any partial or conflicting warehouse lineage so a lost response cannot
   cause a duplicate append;
6. waits for the canonical terminal state `JOB_STATE_DONE`;
7. queries BigQuery by immutable lineage columns and returns success only when
   the exact ordinal range, job name, approval, policy, plan, output, and bundle
   digests reconcile for all three sources; and
8. idempotently commits and rereads exactly three immutable rows in
   `migration_audit` before returning the portfolio audit digest.

Any error returns a stable repository-owned code. Provider responses and row
values are not reflected into errors.

## Files

- `cloud_runtime/bundle.py`: approval-bound cloud bundle builder.
- `cloud_runtime/dataflow_template.py`: fixed Beam graph and worker-side
  binding verification.
- `cloud_runtime/orchestrator.py`: all-three-sources execution and warehouse
  reconciliation.
- `cloud_runtime/google_adapters.py`: injected GCS, Dataflow REST, and BigQuery
  clients; it does not discover credentials or read environment variables.
- `dataflow/Dockerfile`: custom pinned Beam 2.75.0 Flex Template image.
- `dataflow/metadata.json`: strict launch-parameter metadata.
- `requirements-dataflow.txt`: isolated worker dependency.
- `requirements-cloud-control.txt`: pinned launch-side Google SDK clients.
- `cloudbuild.dataflow.yaml`: digest-resolved worker image and Flex spec build.
- `scripts/render_m4_bigquery_schemas.py`: local, approval-bound target and
  audit schema renderer; it emits no records or cell values.
- `scripts/run_m4_cloud.py`: executable composition boundary that consumes the
  durable UI-recorded approval, constructs official clients only after local
  validation, and writes a new `0600` sanitized proof.
- `control_plane/mission_control_client.py` and
  `studio-backend/orchestrator_bridge.go`: separately authenticated,
  loopback-only event-store bridge. Dataflow, BigQuery, reconciliation, and
  audit references are persisted before the three UI lanes show completion.

## Deployment gate

Building or deploying this template, creating buckets/tables, enabling APIs,
or changing IAM is outside the local implementation gate and requires a
separate explicit approval. Before that approval, none of the following may be
claimed:

- a Flex Template image or spec exists in Google Cloud;
- a Dataflow job ran;
- a BigQuery table contains migrated rows; or
- the screenshot UI represents live warehouse proof.

When approved, deployment must use dedicated identities and resource-scoped
roles. The default Compute Engine service account and project-wide Editor are
not acceptable. Target tables must be pre-created with the bound output schema
plus the nine `_ztm_*` lineage columns; the template uses `CREATE_NEVER`. The
dedicated subnetwork must have Private Google Access, and the runtime must use
a digest-pinned Artifact Registry SDK image. Render schemas locally with:

```text
python -m scripts.render_m4_bigquery_schemas \
  --snapshot /owner-only/prepared.json \
  --digest sha256:<approved-portfolio-digest> \
  --dataset legacy_migration \
  --output-dir /owner-only/rendered-schemas
```

Running `gcloud builds submit --config cloudbuild.dataflow.yaml` is deliberately
outside the local gate because it pushes an image, writes a Flex spec, and
incurs cloud-side mutations.

## Official implementation references

- Dataflow Flex Template packaging:
  <https://cloud.google.com/dataflow/docs/guides/templates/configuring-flex-templates>
- Flex Template REST launch method and runtime environment:
  <https://cloud.google.com/dataflow/docs/reference/rest/v1b3/projects.locations.flexTemplates/launch>
- Apache Beam BigQuery I/O and bounded `FILE_LOADS`:
  <https://beam.apache.org/documentation/io/built-in/google-bigquery/>
- Parameterized BigQuery queries:
  <https://cloud.google.com/bigquery/docs/parameterized-queries>

## Local verification

The cloud boundary and adapters are covered by dependency-free fakes; the
tests make no network calls and need no credentials:

```text
venv/bin/python -m pytest -q tests/cloud_runtime
```

The complete local suite must pass before a template build. A live canary must
then record sanitized references for the run ID, approved portfolio digest,
three Dataflow job IDs, three target tables, and three reconciliations. Those
references become the only basis for a `completed` Mission Control state.
