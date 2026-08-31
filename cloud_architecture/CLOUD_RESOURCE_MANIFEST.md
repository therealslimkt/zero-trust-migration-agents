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
| `keraun-jde-e1-ibmi` Artifact Registry image | Live M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic JDE/IBM i-shaped emulator, deployed as `sha256:d66986970e1f8b6763a12cd238a1de2f8c6a11f4f8a54802bf654e6685055e99`; no vendor software or customer data. |
| `keraun-dynamics-ax` Artifact Registry image | Live M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic AX/SQL Server-shaped emulator, deployed as `sha256:db4a3db4fc5ef6916d40d89b931754c7504c43f09f0ef0afe9c582849c0b54a2`; no Microsoft software or data. |
| `keraun-oracle-ebs-19c` Artifact Registry image | Live M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Project-owned synthetic EBS/Oracle-shaped emulator, deployed as `sha256:f2549720c0eca29601fd38e7ea387010b7b9769ffde1a8e65efd85c3310db1a8`; no Oracle software or data. |
| `keraun-cartridge-evidence-runner` Artifact Registry image | Live M7 | [Artifact Registry](https://console.cloud.google.com/artifacts/docker/ztm-agent-9049c3/us-central1/sparky-services?project=ztm-agent-9049c3) | Read-only gVisor runner, deployed as `sha256:7147fc1904e8576a7738e071146ff4c8061e273c143eed6b3274fde6a78b9d73`; no Docker socket, bind mounts, or raw fixture output. |
| `keraun-cartridge-host` service account | Live M7 | [Service account](https://console.cloud.google.com/iam-admin/serviceaccounts/details/keraun-cartridge-host@ztm-agent-9049c3.iam.gserviceaccount.com?project=ztm-agent-9049c3) | VM workload identity. It has Artifact Registry Reader on `sparky-services`; it uses no service-account key. |
| `keraun-cartridge-vpc` / `keraun-cartridge-subnet` | Live M7 | [VPC network](https://console.cloud.google.com/networking/networks/details/keraun-cartridge-vpc?project=ztm-agent-9049c3) | Dedicated custom VPC and private `10.119.104.0/28` subnet with Private Google Access. |
| `keraun-cartridge-router` / `keraun-cartridge-bootstrap-nat` | Live M7, retirement pending | [Cloud NAT](https://console.cloud.google.com/net-services/nat/list?project=ztm-agent-9049c3) | Bootstrap egress only for Docker and signed `runsc` installation. It remains live until an approved post-bootstrap teardown changes the startup dependency. |
| `keraun-cartridge-iap-ssh` firewall rule | Live M7 | [Firewall rule](https://console.cloud.google.com/networking/firewalls/details/keraun-cartridge-iap-ssh?project=ztm-agent-9049c3) | Ingress allows TCP/22 only from the IAP range `35.235.240.0/20` and only to the cartridge host service account. |
| `keraun-cartridge-lab` Compute Engine VM | Live M7 | [Compute Engine VM](https://console.cloud.google.com/compute/instancesDetail/zones/us-central1-a/instances/keraun-cartridge-lab?project=ztm-agent-9049c3) | Private `e2-small` host in `us-central1-a`, no external IP or published database ports. On 2026-08-31 its `runsc` runner emitted only the sanitized expected counts: JDE `1`, AX `2`, EBS `1`. |

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
