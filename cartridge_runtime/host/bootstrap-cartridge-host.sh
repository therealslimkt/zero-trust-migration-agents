#!/bin/bash
# Immutable bootstrap input: VM metadata provides digest-pinned image references.
set -euo pipefail

metadata() {
  curl --fail --silent --show-error -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

require_image() {
  local value
  value="$(metadata "$1")"
  if [[ ! "$value" =~ ^us-central1-docker\.pkg\.dev/ztm-agent-9049c3/[a-z0-9._-]+/[a-z0-9._-]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "invalid digest-pinned image metadata" >&2
    exit 64
  fi
  printf '%s' "$value"
}

export KERAUN_JDE_IMAGE="$(require_image keraun-jde-image)"
export KERAUN_AX_IMAGE="$(require_image keraun-ax-image)"
export KERAUN_EBS_IMAGE="$(require_image keraun-ebs-image)"
export KERAUN_RUNNER_IMAGE="$(require_image keraun-runner-image)"

apt-get update
apt-get install --yes --no-install-recommends ca-certificates curl docker.io docker-compose-v2 gnupg
install -d -m 0755 /usr/share/keyrings
curl --fail --silent --show-error https://gvisor.dev/archive.key \
  | gpg --dearmor --yes -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main' \
  > /etc/apt/sources.list.d/gvisor.list
apt-get update
apt-get install --yes --no-install-recommends runsc
runsc install
systemctl restart docker

metadata_root='http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default'
token="$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' "$metadata_root/token" | sed -n 's/.*"access_token"[ ]*:[ ]*"\([^"]*\)".*/\1/p')"
test -n "$token"
printf '%s' "$token" | docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev

install -d -m 0700 /opt/keraun
cat > /opt/keraun/.env <<EOF
KERAUN_JDE_IMAGE=$KERAUN_JDE_IMAGE
KERAUN_AX_IMAGE=$KERAUN_AX_IMAGE
KERAUN_EBS_IMAGE=$KERAUN_EBS_IMAGE
KERAUN_RUNNER_IMAGE=$KERAUN_RUNNER_IMAGE
EOF
chmod 0600 /opt/keraun/.env
cat > /opt/keraun/compose.yaml <<'EOF'
services:
  jde-e1-ibmi:
    image: "${KERAUN_JDE_IMAGE:?digest-pinned image required}"
    environment: [POSTGRES_DB=keraun_jde, POSTGRES_USER=keraun, POSTGRES_PASSWORD=synthetic-only-admin]
    networks: [cartridge-internal]
    volumes: ["jde-data:/var/lib/postgresql/data"]
    restart: unless-stopped
  dynamics-ax:
    image: "${KERAUN_AX_IMAGE:?digest-pinned image required}"
    environment: [POSTGRES_DB=keraun_ax, POSTGRES_USER=keraun, POSTGRES_PASSWORD=synthetic-only-admin]
    networks: [cartridge-internal]
    volumes: ["ax-data:/var/lib/postgresql/data"]
    restart: unless-stopped
  oracle-ebs-19c:
    image: "${KERAUN_EBS_IMAGE:?digest-pinned image required}"
    environment: [POSTGRES_DB=keraun_ebs, POSTGRES_USER=keraun, POSTGRES_PASSWORD=synthetic-only-admin]
    networks: [cartridge-internal]
    volumes: ["ebs-data:/var/lib/postgresql/data"]
    restart: unless-stopped
  evidence-runner:
    image: "${KERAUN_RUNNER_IMAGE:?digest-pinned image required}"
    runtime: runsc
    depends_on: [jde-e1-ibmi, dynamics-ax, oracle-ebs-19c]
    networks: [cartridge-internal]
    read_only: true
    tmpfs: ["/tmp"]
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    pids_limit: 64
    mem_limit: 256m
    cpus: 0.50
    profiles: [evidence]
networks:
  cartridge-internal:
    internal: true
volumes:
  jde-data:
  ax-data:
  ebs-data:
EOF
cat > /opt/keraun/run-evidence.sh <<'EOF'
#!/bin/sh
set -eu
cd /opt/keraun
docker compose --env-file .env --project-name keraun-cartridge-lab --profile evidence run --rm evidence-runner
EOF
chmod 0700 /opt/keraun/run-evidence.sh
cd /opt/keraun
docker compose --env-file .env --project-name keraun-cartridge-lab up -d jde-e1-ibmi dynamics-ax oracle-ebs-19c
for attempt in $(seq 1 30); do
  if docker compose --env-file .env --project-name keraun-cartridge-lab --profile evidence run --rm evidence-runner >/var/log/keraun-cartridge-evidence.json 2>/var/log/keraun-cartridge-evidence.err; then
    chmod 0600 /var/log/keraun-cartridge-evidence.json /var/log/keraun-cartridge-evidence.err
    exit 0
  fi
  sleep 2
done
exit 1
