#!/bin/sh
# Start the loopback-only local runner agent and M4 lab UI together. Neither
# process is a hosted deployment and both terminate when Vite exits.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${KERAUN_LOCAL_CARTRIDGE_AGENT_TOKEN:=$(openssl rand -hex 32)}"
export KERAUN_LOCAL_CARTRIDGE_AGENT_TOKEN

"$ROOT/venv/bin/python" "$ROOT/scripts/local_cartridge_agent.py" &
agent_pid=$!
cleanup() {
  kill "$agent_pid" >/dev/null 2>&1 || true
  wait "$agent_pid" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

cd "$ROOT/studio"
MISSION_CONTROL_LOCAL_FIXTURE_LAB=true VITE_LOCAL_CARTRIDGE_AGENT=true npm run dev:m4
