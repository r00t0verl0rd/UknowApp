# UknowApp architecture

The application is organized by responsibility and business domain. The public HTTP contract, database schema and existing UI behavior remain unchanged during this migration.

## Backend

```text
backend/app/
├── core/
│   ├── config.py          # environment and application configuration
│   ├── database.py        # engine, sessions, schema bootstrap and migrations
│   └── security.py        # sessions, authentication and authorization
├── modules/
│   ├── administration/    # admin users, assignments, backups and data maintenance
│   │   └── routes.py      # /api/admin/*
│   ├── assignments/       # teacher/student assignment lifecycle
│   ├── conversations/    # participant conversation queries and serialization
│   ├── system/            # authentication, health and push subscription routes
│   │   └── routes.py
│   ├── panel/             # authenticated panel, messaging, SSE and graph routes
│   │   └── routes.py
│   ├── media/             # media feature boundary
│   ├── messaging/         # conversation access and safe message serialization
│   ├── notifications/     # Web Push delivery
│   ├── personal_chat/     # private administrator conversations
│   ├── telegram/          # bot transport, handlers and Telegram workflows
│   └── users/             # user validation and serialization
├── infrastructure/
│   └── storage/
│       └── media.py       # local persistent media adapter
├── api.py                 # includes feature routers; keeps the public API entry point
├── models.py              # SQLAlchemy entities
├── schemas.py              # request/response validation
├── event_hub.py            # in-process SSE event distribution
└── main.py                 # FastAPI composition root
```

### Backend boundaries

- `core` owns cross-cutting runtime concerns. Business modules should depend on core interfaces, not reimplement configuration, database sessions or authentication.
- `modules` owns business rules. Each domain has its own service boundary; Telegram, notifications and administration are isolated from unrelated domains.
- `infrastructure` owns concrete adapters such as local file storage.
- `main.py` is the composition root: it creates the application and connects routers, lifecycle hooks and integrations.
- HTTP routes are grouped by feature. Domain services remain separate from transport handlers, and the composition root only includes routers.

`api.py` now only composes three feature routers: `system`, `administration` and `panel`. The endpoint paths, dependencies, response shapes and business handlers remain unchanged. Each router owns its endpoint declarations and local dependencies; new domain endpoints should be added to the matching module rather than the composition root.

The old top-level `config.py`, `database.py`, `security.py`, Telegram files, `media_storage.py`, `push_notifications.py` and `admin_data.py` are compatibility re-exports. New code should import from `core`, `modules` or `infrastructure`; once all internal imports are migrated, these shims can be removed.

## Frontend

```text
frontend/src/
├── app/
│   └── App.jsx             # application composition and top-level orchestration
├── modules/
│   ├── administration/     # maintenance page and feature exports
│   │   └── AdditionalPage.jsx
│   ├── authentication/     # login page and authentication feature exports
│   │   └── LoginPage.jsx
│   ├── conversations/      # participant chat UI
│   │   └── ChatsPage.jsx
│   ├── graph/              # structure/graph page
│   │   └── StructurePage.jsx
│   ├── notifications/      # push notification client
│   ├── personal-chat/      # private chat state
│   ├── settings/           # appearance preferences
│   └── users/              # user directory page and editor state
│       └── UsersPage.jsx
├── components/             # shared UI and layout components
├── hooks/
│   ├── app/
│   ├── authentication/
│   ├── conversations/
│   ├── graph/
│   ├── personal-chat/
│   ├── settings/
│   └── users/
├── services/
│   └── api.js              # shared authenticated API client
├── styles/
│   ├── tokens.css
│   └── layout.css
└── main.jsx
```

### Frontend boundaries

- `main.jsx` mounts the app and loads global styles.
- `app/App.jsx` is the application composition root: it coordinates authentication, cross-feature state and actions, then renders the selected feature page.
- Page markup lives with its feature: authentication, structure, users, conversations and administration each have an independent page component. Feature pages receive explicit state and action props; they do not import the application root.
- `modules/<feature>` is the public boundary for a feature's UI and behavior.
- `hooks/<feature>` owns state and reusable React behavior for that feature.
- `services` owns communication with backend services.
- `styles` owns design tokens and global layout rules.

The former `App.jsx`, `useAppState.js`, `MessageBubble.jsx`, `pushNotifications.js`, `styles.css` and `tokens.css` paths remain thin compatibility entry points where applicable.

## Dependency rules

1. A feature may use `core`, `infrastructure` and other domain services through explicit imports.
2. `core` must not import business modules at module load time; model registration is deferred to database bootstrap.
3. Infrastructure adapters must not import UI or API route modules.
4. Frontend feature modules must not import from the application root. Shared behavior belongs in hooks or services.
5. Keep API paths and response shapes stable unless a separate product change explicitly requires a contract migration.

## Remaining extraction boundary

`app/App.jsx` still owns cross-feature orchestration, API refresh/SSE lifecycle, and modal workflows. Keep that orchestration there only while it coordinates multiple features; new page markup and domain-specific actions should live in the corresponding feature module. The next optional step is to move modal workflows into feature-owned dialog components and split the remaining orchestration hooks without changing API contracts or user-visible behavior.
