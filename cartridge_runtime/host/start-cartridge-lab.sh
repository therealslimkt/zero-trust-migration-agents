#!/bin/sh
exec docker compose --project-name keraun-cartridge-lab -f /opt/keraun/compose.yaml up -d jde-e1-ibmi dynamics-ax oracle-ebs-19c
