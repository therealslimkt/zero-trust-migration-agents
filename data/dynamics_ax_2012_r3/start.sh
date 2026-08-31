#!/bin/sh
exec docker compose --project-name keraun-dynamics-ax -f "$(dirname "$0")/compose.yaml" up -d
