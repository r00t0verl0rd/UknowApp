# Telegram gateway deployment (secondary server)

This container owns the BotFather token and provides:
- HTTPS Telegram webhook `/telegram/webhook` protected by Telegram's webhook secret header.
- Private bot transport endpoints `/bot{placeholder}/{method}` and `/file/bot{placeholder}/{path}` protected by the independent gateway key.
- Durable local SQLite update spool (named Docker volume).
- Periodic delivery of updates to primary UknowApp via `/api/internal/telegram/updates`.

## Startup
1. Set `TELEGRAM_MODE=remote` and `TELEGRAM_BOT_ENABLED=true` on primary; **remove** its `TELEGRAM_BOT_TOKEN` and set `TELEGRAM_GATEWAY_URL=https://telegram.example.com` and a random `TELEGRAM_GATEWAY_TOKEN` (32+ characters).
2. Deploy the updated primary backend first. Check that `/api/health` reports Telegram `remote`.
3. On secondary, copy `.env.telegram.example` to `.env.telegram`. Set the actual token, the *same* gateway key as primary, a separate 32+ character webhook secret, the public webhook URL and the HTTPS primary URL.
4. On the secondary server set `TELEGRAM_DOMAIN=telegram.example.com` in a local `.env` (this is for Docker Compose/Caddy, not the web app).
5. Point DNS to the secondary, allow inbound HTTPS and run `docker compose -f docker-compose.telegram.yml up -d --build`.
6. Test `/start`, teacher menu, callbacks, text and media in both directions, topic binding, file archive and web-panel sends. Monitor the secondary `/health` pending counter.

Use separate randomized values for `TELEGRAM_WEBHOOK_SECRET` and `TELEGRAM_GATEWAY_TOKEN`. HTTPS is mandatory. Restrict access to private Bot API endpoints to the primary server via firewall / WireGuard or reverse-proxy ACL when practical. Keep both env files and gateway persistent volume private.

## Reverting to local mode
1. Stop gateway/webhook delivery to primary only after verifying its pending count is zero.
2. Set primary `TELEGRAM_MODE=local` and restore `TELEGRAM_BOT_TOKEN`.
3. Restart primary backend; its existing startup calls `deleteWebhook(drop_pending_updates=False)` and resumes long polling.
4. Stop the secondary gateway. **Do not run both modes at the same time.**

The primary database and archived media stay on the primary host. Back them up before switching; never mount its live SQLite database on the secondary. The delivery model is at-least-once: Telegram events are deduplicated for stored messages; a crash immediately after an external side-effect may repeat an unrelated action. This is not an exactly-once command queue.
