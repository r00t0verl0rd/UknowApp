# Telegram service architecture

## Goal

Prepare UknowApp to run the Telegram Bot API integration on a separate foreign server using Telegram webhooks, while keeping the application backend, business rules, persistent media storage, and database on the primary server.

This document describes both deployment modes. The local mode is the original
polling implementation. The remote gateway, protected Bot API transport, durable
inbound inbox and secondary-VPS Compose setup are implemented in the
`feature/telegram-dual-server-mode` branch, but **production cutover has not been
performed or validated with a live BotFather token**. Deployment instructions are
at `deploy/telegram/README.md`.

The current code uses independent 32+ character shared secrets over HTTPS for
gateway-to-primary and primary-to-gateway requests, not per-message HMAC
signatures/nonces. Telegram webhook authentication uses its dedicated webhook
secret header. Replay duplicates are deduplicated by the Telegram update ID at
the primary durable inbox; the system provides at-least-once processing, not
exactly-once side effects.

## Local-mode implementation

- With `TELEGRAM_MODE=local` (the default), FastAPI starts aiogram long polling inside the main backend process.
- Telegram handlers directly use SQLAlchemy sessions, application models, and the event hub.
- Handlers archive Telegram attachments into the primary server's persistent media directory.
- The web API directly calls the aiogram Bot for sending, copying, editing, and deleting Telegram messages and files.
- The teacher panel stores Telegram chat/message identifiers in the primary database.

A proxy URL only changes the network route for Bot API calls. It does not separate the Telegram process or its business logic dependencies.

## Target topology

```
Telegram
   | HTTPS webhook
   v
Foreign Telegram gateway
   | authenticated inbound event delivery
   v
Primary UknowApp backend
   | business logic + SQLAlchemy
   v
Primary database and media storage

Primary UknowApp backend
   | authenticated outbound Telegram commands
   v
Foreign Telegram gateway
   | Telegram Bot API
   v
Telegram
```

### Foreign Telegram gateway responsibilities

- Own the Telegram bot token. The token must not be required by the primary backend after cutover.
- Expose a public HTTPS webhook endpoint and configure Telegram's webhook secret token.
- Validate Telegram webhook requests and reject invalid requests.
- Forward updates to the primary backend over an authenticated private API.
- Execute outbound Bot API commands requested by the primary backend.
- Transfer inbound attachment bytes to the primary backend when the application needs to archive them.
- Keep only transient delivery state and operational logs; do not connect to the UknowApp database or own application records.

### Primary backend responsibilities

- Remain the only owner of users, assignments, conversations, messages, access codes, teacher panel state, and business rules.
- Process normalized Telegram updates using the existing application logic, adapted away from direct Bot API calls.
- Decide which Telegram actions are required and issue them through a gateway client.
- Store and serve all archived attachments in the existing primary media storage.
- Persist delivery state and idempotency records in the existing database or an application-owned durable queue. No separate database is required for the gateway.

## Required contracts

### Inbound update delivery

The gateway sends the original Telegram Update payload to a private backend endpoint, together with a stable event identifier derived from the bot identity and Telegram `update_id`.

Requirements:

- Authenticate gateway-to-backend requests with a dedicated secret (prefer HMAC over the exact request body, timestamp, and nonce, with constant-time signature comparison).
- Enforce a timestamp window and reject replayed nonces.
- Persist/deduplicate the update before acknowledging it as accepted.
- Treat retries as normal: the same update may be delivered more than once.
- Return success only after durable acceptance. If the backend is unavailable, the gateway must retry with bounded exponential backoff and retain the event until acknowledged.
- Do not log bot tokens, webhook secrets, authorization headers, or private message contents unnecessarily.

### Outbound Bot API commands

The primary backend calls a private gateway API using a separate service credential.

The command contract must cover every operation currently used by UknowApp, including:

- send text and media messages;
- copy messages between chats;
- edit message text and reply markup;
- delete messages;
- answer callback queries;
- get bot identity and chat-member status;
- download Telegram files and return their bytes or stream them securely.

Requirements:

- Include a stable command/idempotency identifier for retryable operations.
- Return Telegram message identifiers and relevant Bot API results to the primary backend.
- Apply request timeouts, bounded retries, and explicit error mapping.
- Support multipart/streamed file transfer; do not place large binary files in JSON.
- Never expose the gateway API publicly without authentication and network restrictions.

### Media flow

- The gateway downloads Telegram attachments using the bot token.
- It transfers bytes to a private backend endpoint.
- The primary backend validates size and MIME type, writes the file to the existing persistent media volume, and stores only application-owned metadata/path in the database.
- Outgoing attachments are read from primary storage and streamed to the gateway for Bot API upload.
- Telegram `file_id` values may be retained as transport metadata where useful, but they must not replace the primary archive or become a dependency for the web panel.

## Migration sequence

1. **Inventory and contracts (implemented):** document every inbound update, Bot API operation, file flow, and current database side effect. No runtime behavior changes.
2. **Introduce a gateway boundary (implemented):** replace direct Bot API calls in application code with an application-owned Telegram gateway interface, initially backed by the existing local aiogram Bot. Keep behavior unchanged.
3. **Separate update processing (implemented; update-ID deduplication, not globally exactly-once):** make update handling callable from a trusted internal entry point, add durable idempotent acceptance, and remove assumptions that updates arrive only from local polling.
4. **Implement the foreign gateway (implemented in the feature branch):** webhook receiver, Telegram token ownership, outbound command API, retry handling, and secure file relay.
5. **Cut over (NOT DONE):** deploy the gateway, configure Telegram webhook, verify inbound and outbound behavior, then disable local polling. Keep a controlled rollback path.
6. **Remove transitional code (NOT DONE):** delete polling-only code and proxy configuration only after the webhook deployment is stable.

Each step should be a small, independently reviewable change. Do not change the database schema unless a concrete requirement cannot be met with the existing models and durable processing design.

## Compatibility checklist

Before cutover, verify all of the following against the current behavior:

- /start, /menu, account linking, and access-code validation;
- student private messages and supported media;
- teacher replies, persistent teacher panel, inline callbacks, and keyboard actions;
- student forum-topic binding and group permission checks;
- message copy/forward behavior and destination message identifiers;
- delivery status updates and teacher-panel refreshes;
- attachment archiving, web download/preview, deletion, and size limits;
- personal/admin messages sent from the web panel;
- Telegram outage behavior, duplicate webhook deliveries, gateway restart, and backend restart.

## Security boundaries

- Bot token: foreign gateway only.
- Database credentials: primary backend only.
- Webhook secret and gateway service credentials: separate secrets, rotated independently.
- Gateway API: private network where possible, otherwise HTTPS plus request signatures, timestamp/nonce validation, rate limits, and strict request-size limits.
- Media: validate content and enforce limits on the primary backend; never trust gateway-supplied paths.
