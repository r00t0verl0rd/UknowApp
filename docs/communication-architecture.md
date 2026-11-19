# Communication layer

## Purpose

UknowApp owns users, roles, access codes, assignments, conversations, message
history, and delivery policy. A messenger adapter translates provider events
and sends messages requested by UknowApp. Provider SDK objects stay inside
their adapter.

## Contract location

- `backend/app/modules/communication/contracts.py` — normalized messages,
  media references, delivery results, capabilities, and platform identifiers.
- `backend/app/modules/communication/service.py` — outbound adapter registry
  and delivery dispatch.
- `backend/app/modules/telegram/adapter.py` — Telegram Bot API implementation.
- `backend/app/modules/communication/__init__.py` — public contract exports.

## Rules

1. External user, chat, message, and event identifiers are strings. Provider
   identifiers may be numeric today and opaque strings tomorrow.
2. `event_id` identifies a provider event and is the future deduplication key
   within a platform/bot scope.
3. `provider_file_id` is opaque and may only be interpreted by its adapter.
   It is not an application storage path.
4. Outbound media uses an application-owned `storage_key`; adapters must not
   make the web panel depend on provider file identifiers.
5. `idempotency_key` allows the delivery layer to retry safely when a provider
   supports idempotent operations. The Telegram Bot API adapter does not yet
   provide provider-side idempotency.
6. `MessengerCapabilities` describes optional platform features. The core
   must not assume that edit, delete, groups, threads, or interactive messages
   exist on every platform.
7. Provider payloads and SDK objects must not cross the communication boundary.

## Stage 1 — contracts

The first stage introduced the provider-neutral message and adapter contracts.
It did not change runtime routing, Telegram polling, account linking, database
tables, or web-panel behavior.

## Stage 2 — web-panel outbound delivery

The web-panel text and attachment endpoints now send through
`CommunicationService`. Message deletion also uses the adapter boundary.
Telegram thread IDs are carried as a neutral optional route field, while the
existing student-topic selection logic and delivery metadata remain unchanged.

`TelegramAdapter` owns aiogram calls, Telegram media selection, the existing
document fallback, and external message ID conversion. The application starts
the service with a Telegram adapter when the bot is configured; otherwise the
service remains available with no active providers and the web panel retains
its existing delivery-error behavior.

The Telegram teacher-panel refresh remains a Telegram-specific UI operation.
Inbound Telegram handlers and their direct Telegram operations are deliberately
unchanged in this stage; they will be separated in later stages.

## Next

The next stage will extend the same outbound service to the remaining
application-originated delivery points without changing the shared message
history or current user experience.
