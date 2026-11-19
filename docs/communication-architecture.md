# Communication layer

## Purpose

UknowApp owns users, roles, access codes, assignments, conversations, message
history, and delivery policy. A messenger adapter only translates provider
events to the communication contract and sends messages requested by UknowApp.

The first implementation stage introduces contracts only. It does not change
runtime routing, Telegram polling, account linking, database tables, or the
web-panel API.

## Contract location

- `backend/app/modules/communication/contracts.py` — normalized messages,
  media references, delivery results, capabilities, and adapter protocol.
- `backend/app/modules/communication/__init__.py` — public exports.

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
   supports idempotent operations.
6. `MessengerCapabilities` describes optional platform features. The core
   must not assume that edit, delete, groups, threads, or interactive messages
   exist on every platform.
7. Provider payloads and SDK objects must not cross this boundary. Adapters
   normalize them into these dataclasses.

## Current status

Telegram remains on its existing implementation in this stage. The contracts
are not wired into handlers or web routes yet. The next stage will introduce a
local Telegram adapter behind this boundary and move outbound delivery out of
the web-panel routes without changing current behavior.
