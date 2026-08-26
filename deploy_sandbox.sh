#!/bin/bash
# Deploys the execution-sandbox Cloud Run service.
#
# Fail-closed by design: this script refuses to build or deploy anything
# unless an explicit runtime service account and an explicit invoker
# principal are provided. The service is deployed with authenticated
# invocation only, internal ingress, and an explicit Invoker IAM binding
# scoped to a single principal (never `allUsers`).
set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_NAME="execution-sandbox"
IMAGE_URI="us-central1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/execution-sandbox-img"

# Fail closed: refuse to deploy onto the default Compute Engine service
# account. The caller must name an explicit, least-privilege identity.
if [ -z "${SANDBOX_SERVICE_ACCOUNT:-}" ]; then
    echo "Error: SANDBOX_SERVICE_ACCOUNT is not set." >&2
    echo "Set it to an explicit service account email before deploying." >&2
    exit 1
fi

# Fail closed: refuse to deploy a service with no explicit invoker. There is
# no default/allUsers fallback.
if [ -z "${SANDBOX_INVOKER_MEMBER:-}" ]; then
    echo "Error: SANDBOX_INVOKER_MEMBER is not set." >&2
    echo "Set it to the principal allowed to invoke this service, e.g." >&2
    echo "  user:you@example.com" >&2
    echo "  serviceAccount:caller@${PROJECT_ID}.iam.gserviceaccount.com" >&2
    exit 1
fi

echo "Deploying Execution Sandbox to Cloud Run in project $PROJECT_ID..."

# Build using an explicit Cloud Build config that targets Dockerfile.sandbox
# directly; no Dockerfiles are renamed or moved during the build.
gcloud builds submit \
    --config cloudbuild.sandbox.yaml \
    --substitutions=_IMAGE_URI="$IMAGE_URI" \
    .

# Deploy with an explicit service account, authenticated invocation only
# (with IAM enforced on every request via --invoker-iam-check), and
# internal-only ingress.
gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE_URI" \
    --region "$REGION" \
    --service-account "$SANDBOX_SERVICE_ACCOUNT" \
    --no-allow-unauthenticated \
    --invoker-iam-check \
    --ingress=internal \
    --command="" \
    --args=""

# Grant Cloud Run Invoker to exactly one named principal. This replaces any
# prior public/allUsers binding; it does not add to one.
gcloud run services set-iam-policy "$SERVICE_NAME" \
    --region "$REGION" \
    /dev/stdin <<EOF
{
  "bindings": [
    {
      "role": "roles/run.invoker",
      "members": ["${SANDBOX_INVOKER_MEMBER}"]
    }
  ]
}
EOF

echo "Sandbox deployed: authenticated invocation only, internal ingress,"
echo "service account ${SANDBOX_SERVICE_ACCOUNT}, invoker ${SANDBOX_INVOKER_MEMBER}."
