#!/bin/sh
# Start the Go control plane in credential-free local-demo mode and persist the
# two tokens so the pipeline producer and the Vite BFF can both reach it.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENVFILE="${MISSION_CONTROL_ENV_FILE:-/private/tmp/keraun-mission-control.env}"

if [ ! -f "$ENVFILE" ]; then
  umask 077
  {
    echo "MISSION_CONTROL_API_TOKEN=$(openssl rand -hex 24)"
    echo "MISSION_CONTROL_ORCHESTRATOR_TOKEN=$(openssl rand -hex 24)"
  } > "$ENVFILE"
fi
# shellcheck disable=SC1090
. "$ENVFILE"
export MISSION_CONTROL_API_TOKEN MISSION_CONTROL_ORCHESTRATOR_TOKEN
export MISSION_CONTROL_LOCAL_DEMO=true
export MISSION_CONTROL_STATE_PATH="${MISSION_CONTROL_STATE_PATH:-/private/tmp/keraun-mc-control.json}"
export MISSION_CONTROL_WEB_STATE_PATH="${MISSION_CONTROL_WEB_STATE_PATH:-/private/tmp/keraun-mc-web.json}"
export MISSION_CONTROL_ALLOWED_ORIGINS="${MISSION_CONTROL_ALLOWED_ORIGINS:-http://127.0.0.1:5173}"

echo "tokens: $ENVFILE"
cd "$ROOT/studio-backend"
exec go run .
