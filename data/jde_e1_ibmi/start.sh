#!/bin/sh
exec docker compose --project-name keraun-jde-e1-ibmi -f "$(dirname "$0")/compose.yaml" up -d
