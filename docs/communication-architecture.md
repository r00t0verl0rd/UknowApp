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
  platform identities.
- `backend/app/modules/telegram/adapter.py` — Telegram Bot API implementation.

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

Until the later identity and handler migration stages, `users.telegram_id`
remains a compatibility field. Telegram linking through the existing access
code flow, admin user creation/editing, disconnect, and user deletion
dual-write or clean up the account table in the same database transaction.
Current Telegram handlers still resolve users through the compatibility
field; this stage does not change their routing behavior.

## Next

The next stage will move Telegram inbound event normalization and message
processing behind the communication boundary, while preserving the current
conversation, access-control, and attachment behavior.
