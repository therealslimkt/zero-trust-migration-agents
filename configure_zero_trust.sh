#!/bin/bash
PROJECT_ID=$(gcloud config get-value project)
echo "Project ID: $PROJECT_ID"

echo "Creating Legacy DB Service Account..."
gcloud iam service-accounts create legacy-db-sa \
    --description="Service account for legacy database VMs" \
    --display-name="Legacy DB SA" 2>/dev/null || true

SA_EMAIL="legacy-db-sa@${PROJECT_ID}.iam.gserviceaccount.com"

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

echo "Done Zero Trust Configuration!"
