# Hosted web draft on Google Cloud

Status: **implemented in source; cloud resources and deployment not yet
created or verified**.

## Deployment shape

One Cloud Run service runs the compiled Go Mission Control server and serves
the Vite Studio build from the same origin:

```text
browser
  └─ Cloud Run: sparky-studio-draft
       ├─ /, /about, /login, /demo/*       React SPA
       ├─ /api/web/v1/demos/*              public immutable replay reads
       ├─ /api/web/v1/*                    Firebase-authenticated BFF
       └─ /api/v1/*, /internal/v1/*        service-token boundaries

Firebase Authentication                  Cloud Storage (private)
  └─ verified Google identity              ├─ control-plane.json
       └─ server invitation policy          ├─ web-state.json
            ├─ viewer: read only            └─ web-state.json.bundles/sha256.json
            └─ admin: mutations
```

The Cloud Run service accepts unauthenticated HTTP so the public site and a
published replay can load. That does not make private operations anonymous:
the Go BFF verifies a Firebase ID token, checks a server-owned email invitation
policy, and allows mutations only for configured admins.

## Durable state boundary

Cloud Run's container filesystem is disposable. The hosted store talks to the
Cloud Storage API directly and uses object-generation preconditions for every
snapshot replacement. If another revision has advanced an object, the write
fails instead of overwriting newer state. Published replay bodies are content
addressed and use a create-only precondition.

This is deliberately not a Cloud Storage FUSE mount: the stores depend on an
atomic visibility boundary, so treating object storage like a POSIX filesystem
would weaken their guarantees.

Keep the initial draft at `--max-instances=1`. Generation checks still protect
an overlapping old/new deployment revision. A larger active fleet should move
individual run and event records into a transactional database rather than
continually rewriting snapshot objects.

## Configuration

Build-time public Firebase identifiers:

```text
VITE_FIREBASE_API_KEY
VITE_FIREBASE_AUTH_DOMAIN
VITE_FIREBASE_PROJECT_ID
VITE_FIREBASE_APP_ID
```

Runtime configuration:

```text
MISSION_CONTROL_FIREBASE_PROJECT_ID
MISSION_CONTROL_GCS_STATE_BUCKET
MISSION_CONTROL_GCS_STATE_PREFIX
MISSION_CONTROL_ALLOWED_ORIGINS
```

Runtime Secret Manager values:

```text
MISSION_CONTROL_API_TOKEN
MISSION_CONTROL_ORCHESTRATOR_TOKEN
MISSION_CONTROL_ALLOWED_EMAILS
MISSION_CONTROL_ADMIN_EMAILS
```

The email values are comma-separated exact Google-account emails. Admins are
automatically included in the invitation set. An invited non-admin can sign in
and read public material but receives a closed `403 viewer-read-only` response
for every authenticated mutation.

## Owner-reviewed deployment sequence

The following is a runbook, not evidence that these resources exist. Enabling
services and creating resources can incur cost.

```bash
export ZTM_DRAFT_PROJECT="ztm-agent-9049c3"
export ZTM_DRAFT_REGION="us-central1"
export ZTM_DRAFT_SERVICE="sparky-studio-draft"
export ZTM_DRAFT_REPOSITORY="sparky-services"
export ZTM_DRAFT_BUCKET="${ZTM_DRAFT_PROJECT}-sparky-state"
export ZTM_DRAFT_RUNTIME_SA="sparky-web-runtime@${ZTM_DRAFT_PROJECT}.iam.gserviceaccount.com"
```

1. Enable Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud
   Storage, and Identity Toolkit. Create a Docker-format Artifact Registry
   repository and a private, uniform-access, versioned state bucket.
2. Enable Google sign-in in Firebase Authentication and create a Firebase web
   application. Add the eventual Cloud Run hostname to Firebase Authorized
   Domains.
3. Create the dedicated runtime service account. Grant it object-user access
   on the one state bucket plus only the Firebase permissions needed for token
   verification. Do not download a service-account key; Cloud Run supplies
   Application Default Credentials.
4. Store the two service tokens and two email lists in Secret Manager.
5. Build `Dockerfile.web` with `cloudbuild.web.yaml`, supplying the four public
   Firebase substitutions.
6. Deploy the digest-pinned image with the runtime identity,
   `--allow-unauthenticated`, `--max-instances=1`, and the environment/secrets
   above. Do not expose or reuse the old `execution-sandbox` service.
7. Read the resulting service URL, set it as the exact
   `MISSION_CONTROL_ALLOWED_ORIGINS`, add its hostname to Firebase Authorized
   Domains, and deploy that configuration revision.

Build shape:

```bash
gcloud builds submit \
  --project "$ZTM_DRAFT_PROJECT" \
  --config cloudbuild.web.yaml \
  --substitutions '_VITE_FIREBASE_API_KEY=PUBLIC_VALUE,_VITE_FIREBASE_AUTH_DOMAIN=PROJECT.firebaseapp.com,_VITE_FIREBASE_PROJECT_ID=PROJECT,_VITE_FIREBASE_APP_ID=PUBLIC_APP_ID'
```

Deploy shape after resolving the image to a digest:

```bash
gcloud run deploy "$ZTM_DRAFT_SERVICE" \
  --project "$ZTM_DRAFT_PROJECT" \
  --region "$ZTM_DRAFT_REGION" \
  --image "IMAGE_URI_AT_SHA256_DIGEST" \
  --service-account "$ZTM_DRAFT_RUNTIME_SA" \
  --allow-unauthenticated \
  --max-instances 1 \
  --concurrency 20 \
  --set-env-vars "MISSION_CONTROL_FIREBASE_PROJECT_ID=$ZTM_DRAFT_PROJECT,MISSION_CONTROL_GCS_STATE_BUCKET=$ZTM_DRAFT_BUCKET,MISSION_CONTROL_GCS_STATE_PREFIX=hosted-draft" \
  --set-secrets "MISSION_CONTROL_API_TOKEN=sparky-api-token:latest,MISSION_CONTROL_ORCHESTRATOR_TOKEN=sparky-orchestrator-token:latest,MISSION_CONTROL_ALLOWED_EMAILS=sparky-allowed-emails:latest,MISSION_CONTROL_ADMIN_EMAILS=sparky-admin-emails:latest"
```

## Exact-replay bootstrap

With no objects present, the service creates empty snapshots. To carry a
validated local run into the hosted draft, upload the exact control-plane
snapshot, web snapshot, and bundle directory before starting the service while
preserving these object names:

```text
gs://BUCKET/hosted-draft/control-plane.json
gs://BUCKET/hosted-draft/web-state.json
gs://BUCKET/hosted-draft/web-state.json.bundles/<manifest-sha256>.json
```

Use an if-generation-match-zero precondition for the initial upload. Never
overwrite a live hosted snapshot by copying a local file over it. Before
sharing the URL, test anonymous replay, invited viewer read-only enforcement,
admin access, hard refresh, and a new Cloud Run revision.
