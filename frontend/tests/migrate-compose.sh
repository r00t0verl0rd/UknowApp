#!/usr/bin/env bash
set -euo pipefail
# This test owns the Compose projects, ports and volumes of its disposable CI runner.
: "${GITHUB_ACTIONS:?Requires a disposable GitHub Actions runner}"
test ! -e .env
work=$(mktemp -d)
export MIGRATION_ARCHIVE="$work/backup.zip"
export ADMIN_PASSWORD
ADMIN_PASSWORD=$(openssl rand -hex 24)
cat > .env <<EOF
ADMIN_USERNAME=migration-admin
ADMIN_PASSWORD=$ADMIN_PASSWORD
TELEGRAM_BOT_ENABLED=false
EOF
# Keep the production proxy rules. Only the public hostname/TLS changes for localhost.
sed 's/^uknowschool.ru, www.uknowschool.ru {/http:\/\/localhost {/' frontend/Caddyfile > "$work/Caddyfile"
cat > "$work/override.yml" <<EOF
services:
  frontend:
    image: uknow-migration-web
    volumes:
      - $work/Caddyfile:/etc/caddy/Caddyfile:ro
  backend:
    image: uknow-migration-backend
EOF
compose() { docker compose -p "migration-$1" -f docker-compose.yml -f "$work/override.yml" "${@:2}"; }
cleanup() {
  if [[ $1 != 0 ]]; then
    compose source logs --tail 50
    compose target logs --tail 50
  fi
  compose source down -v
  compose target down -v
  rm -rf "$work"
  rm -f .env
}
trap 'cleanup $?' EXIT
compose source up --build --wait --wait-timeout 180
compose source exec -T backend python - <<'PY'
import json
import wave
from pathlib import Path
from app.main import seed_demo_data
from app.core.database import SessionLocal
from app.models import Conversation, Message
seed_demo_data()
root = Path("/app/data/media")
root.mkdir(exist_ok=True)
with wave.open(str(root / "lesson.wav"), "wb") as audio:
    audio.setparams((1, 1, 8000, 0, "NONE", ""))
    audio.writeframes(bytes(8000))
(root / "archive-padding.bin").write_bytes(bytes(24 * 1024 * 1024))
with SessionLocal() as db:
    chat = db.query(Conversation).one()
    media = {"kind": "audio", "local_path": "lesson.wav", "archive_status": "stored",
             "mime_type": "audio/wav", "file_name": "lesson.wav"}
    db.add(Message(conversation_id=chat.id, sender_id=chat.teacher.id, sender_role="teacher",
                   text="migration lesson", content_type="audio", metadata_json=json.dumps({"media": media})))
    db.commit()
PY
node frontend/tests/migrate-browser.js export
compose source down
compose target up --no-build --wait --wait-timeout 180
node frontend/tests/migrate-browser.js restore
