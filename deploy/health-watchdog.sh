#!/bin/sh
# Restart only containers that Docker has marked unhealthy.
# Crashed containers are already handled by restart: unless-stopped.
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
