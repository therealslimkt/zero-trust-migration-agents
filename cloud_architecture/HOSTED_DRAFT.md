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

Firebase Authentication                  Firestore (private)
  └─ verified Google identity              └─ hosted_draft_objects
       └─ server invitation policy              ├─ control-plane snapshot + chunks
            ├─ viewer: read only                 ├─ web snapshot + chunks
            └─ admin: mutations                  └─ immutable replay bundles + chunks
```

The Cloud Run service accepts unauthenticated HTTP so the public site and a
published replay can load. That does not make private operations anonymous:
the Go BFF verifies a Firebase ID token, checks a server-owned email invitation
policy, and allows mutations only for configured admins.

## Durable state boundary

Cloud Run's container filesystem is disposable. The hosted adapter stores state
in Firestore using an object-shaped compatibility boundary around the existing,
integrity-checked stores. Bodies are gzip-compressed and split into immutable
700 KiB chunk documents. A head document records the logical name, SHA-256
digest, uncompressed size, chunk count, and opaque revision.

Every mutable snapshot replacement transactionally compares the head revision
read by the process before installing the new head. A stale process therefore
cannot overwrite newer state. Published replay bodies remain content-addressed
and use create-only transactions. Readers verify chunk order, decoded length,
and the SHA-256 digest before accepting an object.

This design keeps the validated local and hosted store contracts identical and
avoids Firestore's per-document size ceiling. Keep the first draft at
`--max-instances=1`; transactions still protect an overlapping old/new Cloud
Run revision. Before scaling a high-write production fleet, normalize runs,
events, and ownership records into dedicated Firestore collections and add a
retention job for superseded immutable chunk revisions.

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
MISSION_CONTROL_FIRESTORE_PROJECT_ID
MISSION_CONTROL_FIRESTORE_DATABASE_ID
MISSION_CONTROL_FIRESTORE_NAMESPACE
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
export ZTM_DRAFT_RUNTIME_SA="sparky-web-runtime@${ZTM_DRAFT_PROJECT}.iam.gserviceaccount.com"
```

1. Enable Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Firestore,
   and Identity Toolkit. Create a Docker-format Artifact Registry repository
   and a Firestore Native Mode database named `(default)` in the chosen region.
2. Enable Google sign-in in Firebase Authentication and create a Firebase web
   application. Add the eventual Cloud Run hostname to Firebase Authorized
   Domains.
3. Create the dedicated runtime service account. Grant it
   `roles/datastore.user` on this project plus only the Firebase permissions
   needed for token verification. Do not download a service-account key; Cloud
   Run supplies Application Default Credentials.
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
  --set-env-vars "MISSION_CONTROL_FIREBASE_PROJECT_ID=$ZTM_DRAFT_PROJECT,MISSION_CONTROL_FIRESTORE_PROJECT_ID=$ZTM_DRAFT_PROJECT,MISSION_CONTROL_FIRESTORE_DATABASE_ID=(default),MISSION_CONTROL_FIRESTORE_NAMESPACE=hosted_draft" \
  --set-secrets "MISSION_CONTROL_API_TOKEN=sparky-api-token:latest,MISSION_CONTROL_ORCHESTRATOR_TOKEN=sparky-orchestrator-token:latest,MISSION_CONTROL_ALLOWED_EMAILS=sparky-allowed-emails:latest,MISSION_CONTROL_ADMIN_EMAILS=sparky-admin-emails:latest"
```

## Exact-replay bootstrap

With no Firestore head documents present, the service creates empty snapshots.
The logical objects remain the same even though each is represented by a head
document and one or more immutable chunk documents:

```text
control-plane.json
web-state.json
web-state.json.bundles/<manifest-sha256>.json
```

Do not write these collections manually in the Firebase console: doing so would
bypass chunking, digests, and compare-and-swap protections. Seed or publish a
validated replay through the application boundary. Before sharing the URL,
test anonymous replay, invited viewer read-only enforcement, admin access, hard
refresh, and an overlapping Cloud Run revision.

## Firebase versus Firestore

Firebase is the application platform. This deployment uses **Firebase
Authentication** to establish who the browser user is. **Cloud Firestore** is a
database available through Firebase and Google Cloud; it stores the durable
control-plane, web, and exact-replay state. Authentication does not itself store
the migration data, and browser clients never receive direct Firestore access.
All state access passes through the Go BFF and its invitation/role checks.

## Why Cloud Run hosts the site

Cloud Run is the primary site runtime because the same container serves the
compiled React SPA, authenticated Go BFF, control plane, and live terminal
streams on one origin. It supplies a shareable `run.app` URL, scales to zero,
and gives judges direct proof that the backend runs on Google Cloud.

Firebase Hosting can later become a CDN/custom-domain front door that rewrites
requests to Cloud Run. It is not the first deployment target because Hosting's
dynamic rewrites have request-duration constraints that are less natural for
long-lived terminal streams. A direct Cloud Run URL keeps those streams and the
authentication boundary simple; a custom domain or external load balancer can
be added after the draft is stable.
