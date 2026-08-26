#!/bin/bash
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

if [ -z "$TAILSCALE_KEY" ]; then
    echo "Error: TAILSCALE_KEY not set in .env"
    exit 1
fi

STARTUP_SCRIPT="#!/bin/bash
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install tailscale -y
tailscale up --authkey=$TAILSCALE_KEY
"

echo "Creating Btrieve VM (e2-micro)..."
gcloud compute instances create legacy-btrieve-db \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --metadata startup-script="$STARTUP_SCRIPT"

echo "Creating JDE VM (e2-micro)..."
gcloud compute instances create legacy-jde-db \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --metadata startup-script="$STARTUP_SCRIPT"

echo "Creating MaxDB VM (e2-micro)..."
gcloud compute instances create legacy-maxdb \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=legacy-db \
    --metadata startup-script="$STARTUP_SCRIPT"

echo "Done!"
