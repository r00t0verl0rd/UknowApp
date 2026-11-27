#!/usr/bin/env bash
# Старый установщик NFS не поддерживает текущую архитектуру NATS.
echo 'Legacy NFS installer retired; use infrastructure/deploy.sh --check and docs/bots-gateway.md.' >&2
exit 2
