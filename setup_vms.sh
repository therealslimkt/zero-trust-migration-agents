#!/bin/bash
# Creates the legacy database VMs.
#
# Fail-closed by design: the raw Tailscale auth key must never be copied into
# Compute Engine instance metadata. Only a Secret Manager secret *resource
# name* is placed in metadata; each VM's own attached service account
# identity resolves the actual key value at boot time via the Secret Manager
# API, authenticated with its instance metadata access token.
set -euo pipefail

echo "Waiting for compute.googleapis.com to be enabled..."
while ! gcloud services list --enabled | grep -q "compute.googleapis.com"; do
  sleep 5
done

echo "Setting default compute region and zone..."
gcloud config set compute/region us-central1
gcloud config set compute/zone us-central1-a

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "Error: .env file not found."
    exit 1
fi

# Fail closed: only a Secret Manager resource name is accepted. A raw
# TAILSCALE_KEY value is never read or placed into VM metadata by this
# script.
if [ -z "${TAILSCALE_SECRET_NAME:-}" ]; then
    echo "Error: TAILSCALE_SECRET_NAME not set in .env." >&2
    echo "Expected a Secret Manager secret version resource name, e.g." >&2
    echo "  projects/PROJECT_ID/secrets/tailscale-authkey/versions/latest" >&2
    exit 1
fi

# Fail closed: refuse to create VMs under the default Compute Engine service
# account. The caller must name an explicit, least-privilege identity.
if [ -z "${VM_SERVICE_ACCOUNT:-}" ]; then
    echo "Error: VM_SERVICE_ACCOUNT not set in .env." >&2
    echo "Set it to an explicit service account email before creating VMs." >&2
    exit 1
fi

# The startup script never receives the auth key value directly. At boot, it
# reads the secret *resource name* from its own instance metadata, then
# exchanges its instance identity token for the secret value via the Secret
# Manager REST API. If either step fails, Tailscale enrollment is skipped
# rather than falling back to an unauthenticated or unjoined state.
STARTUP_SCRIPT="#!/bin/bash
set -euo pipefail
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install tailscale -y

SECRET_RESOURCE=\$(curl -fsS -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/tailscale-secret-name')
if [ -z \"\$SECRET_RESOURCE\" ]; then
  echo 'No tailscale-secret-name in instance metadata; refusing to join tailnet.' >&2
  exit 1
fi

ACCESS_TOKEN=\$(curl -fsS -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)[\"access_token\"])')

TAILSCALE_AUTHKEY=\$(curl -fsS -H \"Authorization: Bearer \$ACCESS_TOKEN\" \
  \"https://secretmanager.googleapis.com/v1/\${SECRET_RESOURCE}:access\" \
  | python3 -c 'import sys, json, base64; print(base64.b64decode(json.load(sys.stdin)[\"payload\"][\"data\"]).decode())')

if [ -z \"\$TAILSCALE_AUTHKEY\" ]; then
  echo 'Secret Manager returned no Tailscale auth key; refusing to join tailnet.' >&2
  exit 1
fi

tailscale up --authkey=\"\$TAILSCALE_AUTHKEY\"
"

echo "Creating Btrieve VM (e2-micro)..."
gcloud compute instances create legacy-btrieve-db \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --service-account="$VM_SERVICE_ACCOUNT" \
    --scopes=cloud-platform \
    --metadata=tailscale-secret-name="$TAILSCALE_SECRET_NAME" \
    --metadata-from-file startup-script=<(echo "$STARTUP_SCRIPT")

echo "Creating JDE VM (e2-micro)..."
gcloud compute instances create legacy-jde-db \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --service-account="$VM_SERVICE_ACCOUNT" \
    --scopes=cloud-platform \
    --metadata=tailscale-secret-name="$TAILSCALE_SECRET_NAME" \
    --metadata-from-file startup-script=<(echo "$STARTUP_SCRIPT")

echo "Creating MaxDB VM (e2-micro)..."
gcloud compute instances create legacy-maxdb \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --service-account="$VM_SERVICE_ACCOUNT" \
    --scopes=cloud-platform \
    --metadata=tailscale-secret-name="$TAILSCALE_SECRET_NAME" \
    --metadata-from-file startup-script=<(echo "$STARTUP_SCRIPT")

echo "Done!"
