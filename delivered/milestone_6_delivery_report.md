# Enterprise Fleet Milestone 6 delivery report

Status: **complete for the bounded Cloud SQL / Pub/Sub / BigQuery readiness
and live-canary slice; ready for review.**

M6 establishes a constrained Google Cloud foundation without conflating it
with migration execution. Cloud SQL is provisioned as the intended M3
authority, and a sanitized Pub/Sub transport plus empty BigQuery audit table
exist as downstream canaries. No customer data, source connector, Dataflow
job, M3 schema migration, application-to-database path, or production release
was run.

## Delivered

### 1. Deterministic, offline cloud-readiness gate

`cloud_architecture/m6_cloud_readiness.json` records the planned production
target and binds it to the SHA-256 of
`studio-backend/migrations/m3_001_cloud_sql_authority.sql`. Its Python
validator rejects a live claim, a changed authority migration, secrets in the
manifest, undeclared IAM targets, project-wide `owner`/`editor` grants, and
BigQuery authority drift. `python scripts/validate_m6_cloud_readiness.py
--render` produces only a non-executable owner review checklist.

The desired state uses Cloud SQL as lifecycle/approval authority, selects a
sanitized Pub/Sub outbox relay, and makes BigQuery downstream only. It requires
separate migration/runtime/relay identities and documents the evidence required
before any full production claim.

### 2. Low-cost private Cloud SQL authority canary

The owner-approved project `ztm-agent-9049c3` received these newly enabled
APIs: Cloud SQL Admin, Service Networking, and Cloud KMS. The pre-existing
Pub/Sub and Model Armor APIs were confirmed enabled. A `/24` private-services
allocation and Service Networking peering were created on the existing default
VPC.

`keraun-m6-pg` is now `RUNNABLE`: PostgreSQL 16 Enterprise edition,
`db-f1-micro`, zonal `us-central1-a`, no public IP, default-VPC private IP,
10 GB SSD, automatic growth capped at 20 GB, two retained backups, IAM database
authentication, and deletion protection. It uses the dedicated software CMEK
`projects/ztm-agent-9049c3/locations/us-central1/keyRings/keraun-m6/cryptoKeys/authority`;
only the Cloud SQL service agent holds the key-level encrypt/decrypt binding.
The empty `m3_authority` database was created but the M3 schema was not applied.

This small canary is intentionally not HA. It is approximately the shared-core
Cloud SQL price tier plus small storage/backup usage, and it is covered by the
existing USD 100 Hackathon Budget Alert. Do not describe it as an HA or
production Cloud SQL deployment.

### 3. Sanitized Pub/Sub and BigQuery downstream canary

M6 created `keraun-m6-outbox`, `keraun-m6-outbox-sub`, and
`keraun-m6-outbox-dlq`. The subscription retains messages for one day and uses
five delivery attempts. The Pub/Sub service agent has only topic-publisher
access on the DLQ and subscription-subscriber access on the source
subscription.

One fixed non-customer message,
`m6-sanitized-outbox-canary-v1`, was published with attributes
`event_id=evt_m6_canary_0001` and `classification=sanitized_canary`, then
pulled and acknowledged. This proves the transport only; it is not an M3 event
relay.

`keraun_m6_audit.sanitized_outbox_events` is an empty partitioned BigQuery
table with sanitized event identifier, tenant/run IDs, sequence, type/state,
timestamp, evidence-reference, and delivery-status columns. A `COUNT(*)`
query returned zero rows. There is no Pub/Sub-to-BigQuery projector, Dataflow
job, or migration writer, so zero rows is correct.

## Agentic execution and models

Pattern: **deterministic infrastructure composition with human approval**.
Resource selection, configuration validation, IAM bindings, cost limits, and
canary verification are function-like gates; no generative model authorized or
executed a cloud mutation.

- `m6_persistence_audit` independently reviewed M3 PostgreSQL interfaces and
  identified the v1/v2 tenancy/identifier and workflow-evidence gaps.
- `m6_cloud_audit` independently reviewed deployment material and identified
  the unsafe legacy browser setup-command path and the owner-approval boundary.
- Claude Opus was requested through the available Antigravity subscription
  (`claude-opus-4-6-thinking`; Opus 5 was not listed by the CLI). The CLI did
  not return a usable repository review, so no Opus conclusion is claimed.

No secret, customer row, service-account key, or proprietary binary was passed
to an external model.

## Verification

```text
venv/bin/python -m pytest -q tests/cloud_architecture/test_m6_cloud_readiness.py tests/cloud_runtime  PASS (42)
venv/bin/python scripts/validate_m6_cloud_readiness.py                                      PASS
studio-backend: go test ./... -count=1 && go vet ./...                                      PASS
Pub/Sub publish/pull/ack sanitized canary                                                     PASS
BigQuery audit COUNT(*) = 0                                                                   PASS (expected)
Cloud SQL `keraun-m6-pg` = RUNNABLE                                                          PASS
```

## Deliberate deferrals

No M3 schema migration, private application connection, Cloud SQL IAM user,
separate WIF provider, deployed runtime/relay, BigQuery subscription/projector,
Dataflow, Cloud Run, VPC-SC perimeter, Model Armor template/enforcement,
hosted Firebase flow, CA/mTLS enrollment, customer-data movement, or production
claim is included. The legacy Cloud Settings endpoint that can generate broad
mutating commands is not M6 deployment automation and must not be run.

## Cost and teardown boundary

The canary's continuously billed component is the small Cloud SQL instance and
its storage/backups. Deletion protection is intentionally on. After the demo,
the owner must review and explicitly disable deletion protection before deleting
the instance; do not delete the KMS key before the instance and its backups are
retired. Pub/Sub, BigQuery, and the reserved private-services range should also
be removed only through a reviewed teardown change.
