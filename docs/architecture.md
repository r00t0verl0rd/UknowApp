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
│   ├── administration/    # backups, exports and data maintenance
│   ├── assignments/       # teacher/student assignment lifecycle
│   ├── conversations/    # participant conversation queries and serialization
│   ├── media/             # media feature boundary
│   ├── messaging/         # conversation access and safe message serialization
│   ├── notifications/     # Web Push delivery
│   ├── personal_chat/     # private administrator conversations
│   ├── telegram/          # bot transport, handlers and Telegram workflows
│   └── users/             # user validation and serialization
├── infrastructure/
│   └── storage/
│       └── media.py       # local persistent media adapter
├── api.py                 # HTTP router composition / compatibility boundary
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
- `api.py` currently preserves the established HTTP endpoint contract. User, assignment, conversation, private-chat and messaging logic has been moved into domain services. Route handlers are intentionally kept behind this boundary for now so the migration does not alter endpoint behavior in one large step.

The old top-level `config.py`, `database.py`, `security.py`, Telegram files, `media_storage.py`, `push_notifications.py` and `admin_data.py` are compatibility re-exports. New code should import from `core`, `modules` or `infrastructure`; once all internal imports are migrated, these shims can be removed.

## Frontend

```text
frontend/src/
├── app/
│   └── App.jsx             # application composition and top-level orchestration
├── modules/
│   ├── administration/     # administration feature exports
│   ├── authentication/     # authentication feature exports
│   ├── conversations/      # participant chat UI
│   ├── graph/              # graph feature exports
│   ├── notifications/      # push notification client
│   ├── personal-chat/      # private chat state
│   ├── settings/           # appearance preferences
│   └── users/              # user directory and editor state
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
- `app/App.jsx` coordinates authentication state, feature state and page-level UI.
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

## Next extraction boundary

The API router and the top-level React application are still composition-heavy. The next safe step is to split route declarations into domain routers and extract page-level UI from `app/App.jsx`, while keeping `api.py` and `App.jsx` as thin composition layers. This is deliberately separate from moving core services: it can be done feature-by-feature with focused tests and without changing user-visible behavior.
