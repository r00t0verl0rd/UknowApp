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

From stage 5 onward, `messenger_accounts` is the sole runtime source of truth
for linked external identities and chat destinations. The startup migration
copies legacy Telegram IDs before the bot starts, so shared identity and
delivery workflows no longer fall back to `users.telegram_id`. That column
remains temporarily as a compatibility projection for the existing admin UI
and is synchronized by legacy admin create/edit/disconnect operations.

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

## Stage 5 — registry-only runtime identity

Runtime identity resolution and chat-destination lookup now read exclusively
from `messenger_accounts`. The generic inbound workflow, web-panel delivery,
and Telegram teacher-panel presentation no longer use `users.telegram_id`
to identify users or route messages. The old column remains only as a
compatibility projection for the current admin API and is written alongside
Telegram account changes; it is not consulted by the shared identity service.

The unique constraints on `messenger_accounts` continue to allow one account
per platform for each UknowApp user while preventing an external account from
being claimed by two UknowApp users. The same persistent access code can
therefore connect different platforms to one user independently, and a
reconnection to the same platform account updates that account instead of
creating a duplicate.

## Stage 6 — UknowApp is the delivery authority

UknowApp message persistence and external messenger delivery are separate
facts. The message is committed to the shared conversation first. Once
committed, the UknowApp message status is `delivered`, regardless of whether
the recipient has a Telegram/MAX account or whether an external provider is
available. Only UknowApp moderation can leave a persisted message in
`blocked_contact`.

External send results are stored in
`metadata.messenger_deliveries[platform]` with an independent channel status,
delivered copy identifiers, and errors. A failure in one channel never changes
the UknowApp delivery status. Panel messages are fanned out through all
currently registered adapters; each platform is attempted only for recipients
who linked that platform.

The historical Telegram keys `telegram_deliveries` and
`telegram_delivery_errors` remain as compatibility projections for existing
forum-topic routing and old messages. New code should use the generic
`messenger_deliveries` ledger.

The UI receipt states are based only on UknowApp:
- one grey check — the send request is still pending;
- two grey checks — the message is stored and available in the UknowApp inbox;
- two blue checks — the recipient has read it in UknowApp.

The `panel_read_at` field is returned for both ordinary and personal
conversations, so the same `MessageBubble` component can render receipts
without knowing which external messengers are connected.

## Stage 7 — optional messenger modules

Telegram remains enabled by default when a bot token is configured. It can be
turned off without deleting its credentials by setting
`TELEGRAM_BOT_ENABLED=false`. In this state UknowApp starts with an empty
communication registry, while conversation storage, in-app delivery, push
notifications, and read receipts continue to work.

`CommunicationService` exposes the enabled platform registry and allows
additional adapters to be registered independently. The existing platform
enum and `messenger_accounts` constraints already allow a single UknowApp
user to link Telegram and MAX simultaneously.

## Next — MAX adapter

The MAX integration should implement the normalized adapter contracts and the
provider operations required by the shared inbound workflow. It should own
only MAX authentication, webhooks/events, provider API calls, and media
translation. The shared access-code, identity, moderation, conversation,
persistence, delivery-receipt, and notification rules must remain in UknowApp.

Verify MAX with these scenarios before enabling it:
- MAX is the only enabled messenger;
- Telegram and MAX are enabled in parallel;
- a recipient is linked only to Telegram, only to MAX, or to both;
- a recipient has no external messenger account;
- an external provider is unavailable or returns a duplicate event;
- UknowApp remains usable while every external adapter is disabled.
