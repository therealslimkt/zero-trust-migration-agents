# Milestone 6 cloud readiness

Status: **the desired-state boundary is implemented; a constrained live M6
canary is provisioned and verified separately below.**

M6 selects the sanitized **Pub/Sub outbox** path, rather than Datastream, for
the code-first relay. Cloud SQL for PostgreSQL remains the only lifecycle,
approval, release, lease, idempotency, and outbox authority. BigQuery is an
append-only downstream audit/reconciliation projection and must never be read
to authorize an approval or a lifecycle change.

[`m6_cloud_readiness.json`](m6_cloud_readiness.json) is deliberately a
non-secret desired-state record, not Terraform, deployment automation, or
proof that resources exist. It binds the record to the exact M3 authority SQL
bytes, names all planned resource classes, requires resource-scoped IAM, and
forbids service-account keys, project-wide editor/data-editor grants, raw rows
in the relay, browser-to-Cloud-SQL access, and Model Armor bypass.

Validate and render the owner-review-only checklist locally:

```sh
python scripts/validate_m6_cloud_readiness.py --render
```

The command is offline and makes no API call. A valid result says only that the
checked-in planned configuration is internally consistent. It is not Cloud SQL
connectivity, Pub/Sub delivery, BigQuery projection, KMS, VPC Service Controls,
Model Armor enforcement, or deployment proof.

## Live canary facts

The owner-approved M6 canary is a deliberately small, non-production slice in
`ztm-agent-9049c3` / `us-central1`:

- `keraun-m6-pg`: Cloud SQL PostgreSQL 16, `db-f1-micro`, zonal
  (`us-central1-a`), private IP only on the default VPC, 10 GB SSD with a
  20 GB automatic-growth cap, deletion protection, two retained backups, IAM
  database authentication, and the dedicated `keraun-m6/authority` software
  CMEK. Its empty database is `m3_authority`.
- `keraun-m6-outbox`, `keraun-m6-outbox-sub`, and
  `keraun-m6-outbox-dlq`: a Pub/Sub transport canary with one-day retention,
  five delivery attempts, and only the Pub/Sub service agent grants needed for
  the DLQ policy. One fixed sanitized canary message was published and
  acknowledged.
- `keraun_m6_audit.sanitized_outbox_events`: an empty partitioned BigQuery
  audit table. No Pub/Sub-to-BigQuery projector or migration writer is
  deployed, so zero rows is the expected result.

The enabled M6 APIs are Cloud SQL Admin, Service Networking, Cloud KMS,
Pub/Sub, and Model Armor. The canary has a project budget alert at USD 100 and
does not create HA, Dataflow, Cloud Run, a Serverless VPC connector, a VPC
Service Controls perimeter, or a Model Armor template.

These are resource configuration and transport facts only. They do **not**
prove an M3 schema migration, Cloud SQL application connectivity, an outbox
relay, BigQuery projection, workload-identity federation, VPC-SC enforcement,
Model Armor enforcement, customer data processing, or production readiness.

## Read-only inventory result on 2026-08-31

The configured project is `ztm-agent-9049c3` in `us-central1`. Read-only
inventory observed Pub/Sub and Model Armor APIs enabled. Cloud SQL Admin and
Cloud KMS APIs were disabled, so neither Cloud SQL nor KMS resource existence
is claimed. This snapshot is local operator evidence, not a substitute for a
fresh deployment verification.

## Owner approval boundary

Creating or enabling any planned item is an external, potentially billable
change. Obtain owner approval and capture the evidence named in the manifest
before saying it is live. That includes API enablement; VPC private-service
access and perimeter changes; Cloud SQL HA/private-IP instance, database,
roles, and migration; KMS key; workload-identity provider and service
accounts/IAM; Pub/Sub topic/subscription/DLQ; BigQuery dataset/table; Model
Armor template; Secret Manager versions; Cloud Run/Dataflow deployment; and
Firebase/Identity Platform changes.

The legacy browser Cloud Settings setup flow is not M6 deployment automation:
it can generate mutating commands with broad historical bindings. Do not run
or record it as a deployment step. M6 requires a separately approved,
resource-scoped implementation before any cloud mutation.
