#!/bin/sh
exec docker compose --project-name keraun-oracle-ebs-19c -f "$(dirname "$0")/compose.yaml" up -d
