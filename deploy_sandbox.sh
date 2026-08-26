#!/bin/bash
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_NAME="execution-sandbox"
IMAGE_URI="us-central1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/execution-sandbox-img"

echo "Deploying Execution Sandbox to Cloud Run in project $PROJECT_ID..."

# Build explicitly using the correct Dockerfile
mv Dockerfile Dockerfile.bak
mv Dockerfile.sandbox Dockerfile
gcloud builds submit --tag $IMAGE_URI .
mv Dockerfile Dockerfile.sandbox
mv Dockerfile.bak Dockerfile

# Deploy the explicitly built image
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_URI \
    --region $REGION \
    --allow-unauthenticated \
    --command="" \
    --args=""

echo "Sandbox deployed successfully!"
