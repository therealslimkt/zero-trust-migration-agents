# Keraun cloud resource manifest

Status: **tracked operational inventory.** Update this file in the same branch
as every approved cloud-resource mutation, before its delivery report is
written. A resource marked **planned** is not a live claim; a link only opens
the relevant Google Cloud Console location for an authorized operator.

Project: [`ztm-agent-9049c3`](https://console.cloud.google.com/home/dashboard?project=ztm-agent-9049c3)  
Region: `us-central1`

| Resource | State | Operator link | Purpose / boundary |
| --- | --- | --- | --- |
| `execution-sandbox` Cloud Run | Existing | [Cloud Run service](https://console.cloud.google.com/run/detail/us-central1/execution-sandbox?project=ztm-agent-9049c3) | Historical contained service; not Keraun’s hosted demo and not migration proof. |
| `keraun-m6-pg` Cloud SQL | Live constrained canary | [Cloud SQL instance](https://console.cloud.google.com/sql/instances/keraun-m6-pg/overview?project=ztm-agent-9049c3) | Private-IP PostgreSQL 16 M3 authority canary; empty `m3_authority` database, zonal `db-f1-micro`, CMEK, deletion protection. |
| `keraun-m6/authority` Cloud KMS key | Live | [KMS key](https://console.cloud.google.com/security/kms/key/manage/us-central1/keraun-m6/authority?project=ztm-agent-9049c3) | CMEK for the M6 Cloud SQL canary. Do not destroy before the instance/backups are retired. |
| `keraun-m6-psa` private-services range | Live | [VPC IP ranges](https://console.cloud.google.com/networking/addresses/list?project=ztm-agent-9049c3) | `/24` reserved range for the Cloud SQL private-services connection. |
| `keraun-m6-outbox` Pub/Sub topic | Live constrained canary | [Pub/Sub topic](https://console.cloud.google.com/cloudpubsub/topic/detail/keraun-m6-outbox?project=ztm-agent-9049c3) | Sanitized transport only; not yet wired to the M3 database outbox. |
| `keraun-m6-outbox-sub` subscription | Live constrained canary | [Pub/Sub subscription](https://console.cloud.google.com/cloudpubsub/subscription/detail/keraun-m6-outbox-sub?project=ztm-agent-9049c3) | One-day retention, DLQ after five attempts. |
| `keraun-m6-outbox-dlq` topic | Live constrained canary | [Pub/Sub DLQ topic](https://console.cloud.google.com/cloudpubsub/topic/detail/keraun-m6-outbox-dlq?project=ztm-agent-9049c3) | Failed sanitized transport messages only. |
| `keraun_m6_audit.sanitized_outbox_events` BigQuery table | Live empty canary | [BigQuery table](https://console.cloud.google.com/bigquery?project=ztm-agent-9049c3&d=keraun_m6_audit&p=ztm-agent-9049c3&page=table&t=sanitized_outbox_events) | Empty downstream audit target; never lifecycle or approval authority. |
| `keraun-demo` Cloud Run | Planned M7 | — | Public, static fixture-lab host only; no Firebase login, Cloud SQL connection, or migration execution claim. |
| `keraun-jde-e1-ibmi` Artifact Registry image | Planned M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic JDE/IBM i-shaped source emulator. The actual deploy input must be a recorded digest, never a mutable tag. |
| `keraun-dynamics-ax` Artifact Registry image | Planned M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic AX/SQL Server-shaped source emulator; no Microsoft software or data. |
| `keraun-oracle-ebs-19c` Artifact Registry image | Planned M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic EBS/Oracle-shaped source emulator; no Oracle software or data. |
| `keraun-cartridge-evidence-runner` Artifact Registry image | Planned M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Read-only parser/certifier intended for `runsc`/gVisor; no Docker socket and no raw fixture output. |
| `keraun-cartridge-vpc` / `keraun-cartridge-subnet` | Planned M7 | [VPC networks](https://console.cloud.google.com/networking/networks/list?project=ztm-agent-9049c3) | Dedicated private-only cartridge host network; planned IAP-only ingress and temporary NAT bootstrap. |
| `keraun-cartridge-lab` Compute Engine VM | Planned M7 | [Compute Engine VM](https://console.cloud.google.com/compute/instancesDetail/zones/us-central1-a/instances/keraun-cartridge-lab?project=ztm-agent-9049c3) | Private source-emulator host; no external IP, no published database ports, low-cost `e2-small`. |

## Update and teardown rules

- Record the exact resource name, state, Console link, scope, and truth boundary
  immediately after a create/update/delete operation succeeds.
- Never put project account names, service-account keys, passwords, tokens, or
  customer identifiers in this manifest.
- Before a teardown, update the row to **scheduled for teardown** and link the
  owner-approved change record. After verified deletion, retain a dated
  **retired** entry rather than silently removing history.
- The M6 Cloud SQL canary is continuously billable. Deletion protection must be
  disabled by an approved owner action before deletion; retain the CMEK until
  the instance and retained backups are gone.
