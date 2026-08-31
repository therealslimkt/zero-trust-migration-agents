#!/bin/sh
exec docker compose --project-name keraun-cartridge-lab -f /opt/keraun/compose.yaml --profile evidence run --rm evidence-runner
