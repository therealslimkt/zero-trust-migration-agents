#!/bin/bash
# Fail-closed by design: this script refuses to touch any VM's network
# exposure or identity until it has confirmed the target service account
# actually exists. It never silently proceeds on a missing project or a
# failed service account creation.
set -euo pipefail

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: no active gcloud project is configured." >&2
    echo "Refusing to mutate VM identities or network access configs." >&2
    exit 1
fi
echo "Project ID: $PROJECT_ID"

echo "Creating Legacy DB Service Account..."
gcloud iam service-accounts create legacy-db-sa \
    --description="Service account for legacy database VMs" \
    --display-name="Legacy DB SA" 2>/dev/null || true

SA_EMAIL="legacy-db-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Fail closed: verify the service identity we're about to attach to every VM
# actually exists before deleting external IPs or rewiring identities.
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
    echo "Error: service account $SA_EMAIL does not exist and could not be created." >&2
    echo "Refusing to mutate VM identities or network access configs." >&2
    exit 1
fi

# Removing public access is allowed only after every source is reachable by
# its canonical MagicDNS name. A failure stops before the first VM mutation.
if ! command -v tailscale >/dev/null 2>&1; then
    echo "Error: tailscale CLI is required for the private-path preflight." >&2
    exit 1
fi
for host in legacy-btrieve-db legacy-jde-db legacy-maxdb; do
    if ! tailscale ping --c 1 --timeout 5s "$host" >/dev/null 2>&1; then
        echo "Error: $host is not reachable through Tailscale MagicDNS." >&2
        echo "Refusing to remove any public access configuration." >&2
        exit 1
    fi
done

echo "Configuring legacy-btrieve-db..."
# Delete external IP
gcloud compute instances delete-access-config legacy-btrieve-db \
    --access-config-name "External NAT" --zone us-central1-a 2>/dev/null || true
# Stop VM to change SA
gcloud compute instances stop legacy-btrieve-db --zone us-central1-a
gcloud compute instances set-service-account legacy-btrieve-db \
    --service-account="${SA_EMAIL}" \
    --zone us-central1-a
gcloud compute instances start legacy-btrieve-db --zone us-central1-a

echo "Configuring legacy-jde-db..."
# Delete external IP
gcloud compute instances delete-access-config legacy-jde-db \
    --access-config-name "External NAT" --zone us-central1-a 2>/dev/null || true
# Stop VM to change SA
gcloud compute instances stop legacy-jde-db --zone us-central1-a
gcloud compute instances set-service-account legacy-jde-db \
    --service-account="${SA_EMAIL}" \
    --zone us-central1-a
gcloud compute instances start legacy-jde-db --zone us-central1-a

echo "Configuring legacy-maxdb..."
# Delete external IP
gcloud compute instances delete-access-config legacy-maxdb \
    --access-config-name "External NAT" --zone us-central1-a 2>/dev/null || true
# Stop VM to change SA
gcloud compute instances stop legacy-maxdb --zone us-central1-a
gcloud compute instances set-service-account legacy-maxdb \
    --service-account="${SA_EMAIL}" \
    --zone us-central1-a
gcloud compute instances start legacy-maxdb --zone us-central1-a

echo "Done Zero Trust Configuration!"
