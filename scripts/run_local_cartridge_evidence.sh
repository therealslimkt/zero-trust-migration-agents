#!/bin/sh
# Build project-owned synthetic images and run one isolated evidence pass using
# Docker Desktop's runc override. Production continues to use runsc/gVisor on
# the private Compute Engine host.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROJECT="keraun-local-evidence-$$"

compose() {
  KERAUN_JDE_IMAGE=keraun-local-jde \
  KERAUN_AX_IMAGE=keraun-local-ax \
  KERAUN_EBS_IMAGE=keraun-local-ebs \
  KERAUN_RUNNER_IMAGE=keraun-local-runner \
    docker compose --project-name "$PROJECT" \
      -f "$ROOT/cartridge_runtime/host/compose.yaml" \
      -f "$ROOT/cartridge_runtime/host/compose.local.yaml" "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

wait_healthy() {
  service=$1
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    container_id=$(compose ps -q "$service")
    if [ -n "$container_id" ] && [ "$(docker inspect --format '{{.State.Health.Status}}' "$container_id")" = "healthy" ]; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  echo "synthetic cartridge did not become healthy: $service" >&2
  compose ps >&2
  return 1
}

cd "$ROOT"
docker build --file data/jde_e1_ibmi/Dockerfile --tag keraun-local-jde .
docker build --file data/dynamics_ax_2012_r3/Dockerfile --tag keraun-local-ax .
docker build --file data/oracle_ebs_19c/Dockerfile --tag keraun-local-ebs .
docker build --file cartridge_runtime/runner/Dockerfile --tag keraun-local-runner .

compose up -d jde-e1-ibmi dynamics-ax oracle-ebs-19c

wait_healthy jde-e1-ibmi
wait_healthy dynamics-ax
wait_healthy oracle-ebs-19c

compose --profile evidence run --rm evidence-runner
