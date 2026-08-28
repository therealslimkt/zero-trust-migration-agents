# Setup and change boundaries

The discovery commands in [INVENTORY.md](INVENTORY.md) are safe to run as a
read-only operator check. Enabling APIs, creating datasets, deploying a
service, or launching a job changes cloud state and can incur cost. Those
operations require the project owner’s explicit approval and must be recorded
as a new deployed fact only after verification.

## Current configuration baseline

```bash
gcloud auth login
gcloud config set project ztm-agent-9049c3
gcloud config set compute/region us-central1
gcloud config set compute/zone us-central1-a
```

Do not use `gcloud auth application-default login` in a recorded judge flow if
it would display or persist operator-specific credentials. For a deployment
owner, use an approved workload identity or local ADC according to the project
security policy; never commit an ADC file or a service-account key.

## Owner-approved planned enablement

Identity Platform/Firebase and Dataflow are not enabled in the current
inventory. The following commands are examples of a planned change, not a
setup step a judge should run:

```bash
# OWNER APPROVAL REQUIRED: changes enabled services and may enable billing use.
gcloud services enable identitytoolkit.googleapis.com dataflow.googleapis.com \
  --project ztm-agent-9049c3
```

After an approved change, verify with:

```bash
gcloud services list --enabled --project ztm-agent-9049c3 \
  --filter='config.name:(identitytoolkit.googleapis.com dataflow.googleapis.com)' \
  --format='table(config.name,title)'
```

Firebase client configuration, Identity Platform providers, a Dataflow staging
location, a Dataflow template, and migration BigQuery datasets are separate
release items. None is implied merely by enabling an API.

## Service and repository checks

`execution-sandbox` and `cloud-run-source-deploy` are deployed inventory
resources. Before using either in a demo, inspect its current IAM, runtime
identity, and configuration rather than relying on this document:

```bash
gcloud run services get-iam-policy execution-sandbox \
  --project ztm-agent-9049c3 --region us-central1

gcloud artifacts repositories get-iam-policy cloud-run-source-deploy \
  --project ztm-agent-9049c3 --location us-central1
```

Do not make an existing service public to satisfy a demo. A hosted replay must
use an owner-published public route with its own reviewed access policy.
