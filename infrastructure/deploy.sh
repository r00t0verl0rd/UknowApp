#!/usr/bin/env bash
# Проверка конфигурации без изменений на целевом сервере.
set -Eeuo pipefail
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo 'Usage: bash infrastructure/deploy.sh --check'
  echo 'Read-only Compose preflight. Deployment and rollback: docs/bots-gateway.md'
  exit 0
fi
if [[ $# != 1 || $1 != --check ]]; then
  echo 'The old two-VPS NFS installer is retired. Use --check on the intended VPS; see docs/bots-gateway.md.' >&2
  exit 2
fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ -f .env ]] || { echo 'Missing .env; prepare a protected configuration first.' >&2; exit 1; }
[[ -z $(git status --porcelain --untracked-files=no) ]] || { echo 'Tracked files are modified.' >&2; exit 1; }
printf 'Revision: %s\n' "$(git rev-parse HEAD)"
docker compose config --quiet
docker compose ps
printf '%s\n' 'Preflight complete. No services or data changed. Verify backups before deployment.'
