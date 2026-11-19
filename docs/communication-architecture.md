# Communication layer

## Purpose

UknowApp owns users, roles, access codes, assignments, conversations, message
history, and delivery policy. Messenger adapters translate provider events
and deliver messages. Provider SDK objects stay inside their adapters.

## Core contracts and services

- `backend/app/modules/communication/contracts.py` — normalized messages,
  media references, delivery results, capabilities, and platform identifiers.
- `backend/app/modules/communication/service.py` — outbound adapter registry
  and delivery dispatch.
- `backend/app/modules/communication/accounts.py` — persistence helpers for
  platform identities and shared access-code claiming.
- `backend/app/modules/messaging/inbound.py` — the single inbound identity,
  conversation, moderation, persistence, and delivery workflow.
- `backend/app/modules/messaging/moderation.py` — provider-neutral contact-data
  checks applied before a message enters the shared history.
- `backend/app/modules/telegram/adapter.py` — Telegram Bot API implementation.

## Contract rules

1. External user, chat, message, and event identifiers are strings. Provider
   identifiers may be numeric today and opaque strings tomorrow.
2. `event_id` is the future deduplication key within a platform/bot scope.
3. `provider_file_id` is opaque and may only be interpreted by its adapter;
   it is not an application storage path.
4. Outbound media uses an application-owned `storage_key`, not a provider file
   identifier.
5. `idempotency_key` allows safe retries when a provider supports them. The
   Telegram Bot API adapter does not provide provider-side idempotency yet.
6. `MessengerCapabilities` describes optional platform features. The core
   must not assume all messengers support editing, deletion, groups, threads,
   or interactive messages.
7. Provider payloads and SDK objects must not cross the communication
   boundary; adapters normalize them into the shared contracts.

## Stage 1 — provider-neutral contracts

The first stage introduced normalized inbound/outbound message contracts and
the adapter protocol without changing runtime behavior.

## Stage 2 — web-panel outbound delivery

Web-panel text, attachments, and deletion now use `CommunicationService`.
Telegram-specific API calls live in `TelegramAdapter`. The existing message
history, delivery metadata, and Telegram forum-topic routing were preserved.
The Telegram teacher panel remains a platform-specific user interface.

## Stage 3 — messenger accounts

The `messenger_accounts` table stores the relationship between a UknowApp user
and an external messenger identity:

- `user_id` — the owning UknowApp account;
- `platform` — provider key such as `telegram`, `max`, or `whatsapp`;
- `external_user_id` — provider's user identifier, stored as text;
- `external_chat_id` — provider's chat destination, stored as text;
- `username`, `status`, `linked_at`, and `last_seen_at` — optional account
  metadata and connection state.

Database constraints enforce one owner per external identity and at most one
account per platform for each UknowApp user. Different platforms can therefore
be linked to the same UknowApp user independently.

On startup, the database migration copies every existing non-null
`users.telegram_id` into `messenger_accounts`. It is idempotent: running it
again does not create duplicate rows. The historical Telegram link date was
not stored by the previous schema, so migrated rows keep `linked_at = NULL`
rather than inventing a date. Existing user rows and Telegram IDs are not
deleted or rewritten by the migration.

Until the end of stage 4, `users.telegram_id` remains a compatibility field.
The inbound workflow resolves Telegram identities through
`messenger_accounts`, retaining a legacy-column fallback for older rows.
Admin user creation/editing, disconnect, and deletion continue to synchronize
the account table transactionally.

## Stage 4 — unified inbound transition

Every incoming messenger message now follows one application transition:

1. The provider adapter converts its SDK update into `InboundMessage`.
2. The shared identity service resolves the linked account or validates the
   persistent access code and claims the current messenger identity.
3. The same workflow resolves conversation context, checks the user role and
   permissions, applies contact-data moderation, and writes the shared message
   history.
4. The provider port performs channel operations only: sending responses,
   copying attachments, archiving provider media, or deleting transport
   messages.
5. The application returns UI refresh instructions; Telegram renders its
   teacher panel without owning conversation policy.

Private chats and forum topics enter this same workflow. A forum thread is
routing context, not an independent message-processing path. Its binding is
managed by one shared route function used by both automatic routing and the
explicit `/bind_group` setup command.

Persistent access-code validation is platform-neutral and writes to
`messenger_accounts`. Student messages, teacher replies, moderation, read
markers, delivery statuses, and conversation history all use the same
workflow. Teacher keyboard buttons and callback queries remain
presentation-specific events, but call the shared conversation authorization
and session functions.

aiogram message objects are confined to the Telegram adapter and Telegram
presentation handlers. The shared workflow receives only normalized DTOs and
a provider port. The shared media-storage module no longer imports Telegram
SDK types.

## Next

The next stage will make all remaining identity and delivery reads use the
universal account registry, then add MAX as an independent adapter.
