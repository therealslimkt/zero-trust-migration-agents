# Verified inventory and discovery

Use this page to re-check the documented inventory. The commands only read
configuration or metadata unless a command is explicitly placed in the setup
document’s owner-approved change section.

## Recorded inventory

- Project: `ztm-agent-9049c3`.
- Region / zone: `us-central1` / `us-central1-a`.
- Private Compute Engine sources:
  - `legacy-btrieve-db` — `10.128.0.2`
  - `legacy-jde-db` — `10.128.0.3`
  - `legacy-maxdb` — `10.128.0.4`
- Cloud Run service: `execution-sandbox` in `us-central1`.
- Artifact Registry repository: `cloud-run-source-deploy` in `us-central1`.
- APIs known enabled: Vertex AI, BigQuery, Cloud Run, Artifact Registry.
- Not enabled at the recorded inventory point: Identity Platform / Firebase and
  Dataflow.
- No Dataflow jobs and no migration BigQuery datasets were observed at that
  point.

The active account is intentionally omitted. Treat account output as local
operator information, not submission material.

## Login and select the project

```bash
gcloud auth login
gcloud config set project ztm-agent-9049c3
gcloud config set compute/region us-central1
gcloud config set compute/zone us-central1-a

# View locally. Do not copy the account value into tracked files or recordings.
gcloud auth list --filter='status:ACTIVE' --format='value(account)'
gcloud config list --format='text(core.project,compute.region,compute.zone)'
```

## Read-only discovery commands

```bash
gcloud compute instances list \
  --project ztm-agent-9049c3 \
  --zones us-central1-a \
  --format='table(name,zone.basename(),networkInterfaces[0].networkIP,status)'

gcloud run services describe execution-sandbox \
  --project ztm-agent-9049c3 \
  --region us-central1 \
  --format='yaml(metadata.name,status.url,spec.template.spec.serviceAccountName)'

gcloud artifacts repositories describe cloud-run-source-deploy \
  --project ztm-agent-9049c3 \
  --location us-central1 \
  --format='yaml(name,format,mode,remoteRepositoryConfig)'

gcloud services list --enabled \
  --project ztm-agent-9049c3 \
  --format='value(config.name)' | sort

gcloud dataflow jobs list \
  --project ztm-agent-9049c3 \
  --region us-central1 \
  --format='table(id,name,currentState)' \
  --limit 20

bq --project_id=ztm-agent-9049c3 ls
```

If the last two commands return no jobs or no datasets, report that truthfully;
do not substitute local fixtures, screenshots, or a planned resource for a
cloud result.
