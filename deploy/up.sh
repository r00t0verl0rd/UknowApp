#!/bin/sh
# Stable, non-interactive progress output, including when deploying over SSH.
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
exec docker compose --ansi never --progress plain up -d --build "$@"
