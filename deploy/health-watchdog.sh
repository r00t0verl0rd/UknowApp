#!/bin/sh
# Перезапускаем только контейнеры со статусом unhealthy.
# Упавшие контейнеры Docker перезапускает самостоятельно.
set -eu

APP_DIR="/home/deploy/UknowApp"
cd "$APP_DIR"

for service in backend frontend; do
    container_id="$(docker compose ps -q "$service" 2>/dev/null || true)"
    [ -n "$container_id" ] || continue

    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
    if [ "$health" = "unhealthy" ]; then
        logger -t uknowapp-watchdog "Restarting unhealthy service: $service"
        docker compose restart "$service"
    fi
done
