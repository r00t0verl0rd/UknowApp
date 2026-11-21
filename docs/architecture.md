# UknowApp architecture

This document describes the current repository layout. The frontend and backend are separated by responsibility; the existing HTTP API and database remain the source of truth for application data.

## Backend

`backend/app/`:

- `core/` — configuration, database engine/session lifecycle and authentication/security.
- `modules/` — business domains: administration, assignments, boards, communication, conversations, messaging, notifications, panel, personal chat, system, Telegram and users.
- `infrastructure/storage/` — persistent media storage adapter.
- `api.py` — API router composition.
- `models.py` — SQLAlchemy models.
- `event_hub.py` — in-process event distribution for panel SSE.
- `rate_limit.py` and `request_validation.py` — shared request protections.
- `main.py` — FastAPI application composition and lifecycle.

Routes and services belong to their business modules. Keep provider-specific Telegram code inside the Telegram adapter/handlers; shared messaging and delivery rules belong to the communication and messaging services.

## Frontend

`frontend/src/`:

- `app/` — application root and authentication entry.
- `workspaces/` — role-specific workspace composition and shared layout.
- `features/` — administration, boards, conversations, graph, notifications and users. The [video feature plan](video-feature.md) describes a future module.
- `shared/components/` — reusable UI primitives.
- `shared/hooks/` — cross-feature state and controllers.
- `shared/services/` — shared inbox state and the singleton panel event stream.
- `shared/styles/` — design tokens and ordered CSS modules.
- `shared/services/api.js` — shared authenticated JSON transport.
- `main.jsx` — React entry point.

`app/App.jsx` is the composition root. It connects authentication, shared session/bootstrap state and global conversation synchronization, then mounts the workspace for the current role. Feature pages own their presentation and feature-specific actions; API adapters live alongside their feature.

## Loading and live updates

- The application shell is rendered as soon as the authenticated profile is available; inbox and administrator data load independently.
- A single SSE transport is shared by subscribers. It remains active independently of the selected page and closes when the session subscriber is removed.
- Conversation summaries update inbox rows and counters globally. Full history synchronization is limited to the selected conversation.
- Event IDs, inbox revisions and message merge rules prevent duplicate events and stale snapshots from reverting newer message, read or delivery state.
- Reconnection uses the server event stream's replay support. A full inbox recovery is reserved for cases where replay cannot safely restore state.

## Dependency and performance rules

1. Keep database models, migrations and public API payloads stable unless a separately planned migration requires a change.
2. Keep feature workflows in their feature modules; do not move business logic into `App.jsx`.
3. Reuse shared components, hooks and API transport instead of creating parallel implementations.
4. Avoid duplicate event sources, repeated polling, unnecessary network requests and state copies.
5. Keep DOM nesting and React state updates small; defer expensive or page-specific work until it is needed.
6. Do not add CSS overrides at the end of the cascade. Edit the owning rule and preserve the import order in `shared/styles/index.css`.
7. Keep persistent user data under the backend storage/database lifecycle. Frontend cleanup must not alter database contents or API contracts.
