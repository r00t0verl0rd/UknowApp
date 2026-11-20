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

The frontend is organized around feature modules. `app/App.jsx` is the composition root: it connects the application-level controllers, renders the shared navigation and shell, and mounts the active feature page. It does not contain feature API workflows.

```text
frontend/src/
├── app/App.jsx
├── hooks/
│   ├── app/usePanelDataState.js
│   ├── authentication/
│   │   ├── useAuthController.js
│   │   └── useAuthState.js
│   ├── administration/useAdminDataController.js
│   ├── boards/useBoardsState.js
│   ├── conversations/
│   │   ├── useChatState.js
│   │   ├── useChatActionState.js
│   │   └── useChatsController.js
│   ├── graph/useGraphState.js
│   ├── notifications/usePushNotificationsState.js
│   ├── settings/useSettingsState.js
│   └── users/
│       ├── useDirectoryState.js
│       ├── useUserActionState.js
│       ├── useUserEditorState.js
│       └── useUsersController.js
├── modules/
│   ├── administration/
│   │   ├── AdministrationModule.jsx
│   │   ├── AdditionalPage.jsx
│   │   └── services/adminDataApi.js
│   ├── authentication/
│   │   ├── LoginPage.jsx
│   │   └── services/authApi.js
│   ├── boards/
│   │   ├── BoardsPage.jsx
│   │   └── services/boardsApi.js
│   ├── conversations/
│   │   ├── ChatsModule.jsx
│   │   ├── ChatsPage.jsx
│   │   ├── components/
│   │   │   ├── ChatDialogs.jsx
│   │   │   └── MessageBubble.jsx
│   │   └── services/conversationsApi.js
│   ├── graph/
│   │   ├── StructureModule.jsx
│   │   └── StructurePage.jsx
│   ├── panel/services/panelApi.js
│   ├── notifications/pushNotifications.js
│   └── users/
│       ├── UsersModule.jsx
│       ├── UsersPage.jsx
│       ├── components/UserDialogs.jsx
│       └── services/usersApi.js
├── services/api.js
└── styles/
    ├── layout.css
    └── tokens.css
```

### Frontend boundaries

- `app/App.jsx` owns application composition, global navigation, role-based page visibility and shared shell elements. It mounts the four feature entry components and does not call their feature controllers or render their internal pages/dialogs.
- `UsersModule`, `ChatsModule`, `AdministrationModule` and `StructureModule` are feature entry points. They connect each feature controller to its pages and dialogs; `UsersModule` composes `StructureModule` because the graph actions operate on the same user/assignment domain.\n- Each feature controller owns its data transformations, asynchronous workflows and lifecycle effects. The page components focus on rendering and forwarding user intent.
- Feature API adapters live under `modules/<feature>/services/`. They own endpoint paths, HTTP details and payload serialization. Controllers coordinate operations through these adapters.
- `services/api.js` is the shared authenticated JSON transport. File uploads and binary backup transfers use feature-specific adapters because they require multipart or blob handling.
- Authentication, push notifications, theme persistence, panel bootstrap/SSE, user management, conversations, boards and administration have separate ownership boundaries.
- Feature components do not import the application root. The application root composes them through explicit props and controller results.
- Boards are fully encapsulated: `BoardsPage` creates its own board controller and does not expose board state or API details to `App`.

`App.jsx` is intentionally the composition root, but it is now a small application shell rather than a feature implementation: it connects the shared session/bootstrap state, renders navigation, and mounts the active page. Feature workflows, API paths, binary transfers, dialogs and lifecycle effects live in their owning modules. Keep future changes within those boundaries; do not add domain API calls or CRUD handlers back to `App.jsx`.
 
## Dependency rules

1. A feature may use `core`, `infrastructure` and other domain services through explicit imports.
2. `core` must not import business modules at module load time; model registration is deferred to database bootstrap.
3. Infrastructure adapters must not import UI or API route modules.
4. Frontend feature modules must not import from the application root. Shared behavior belongs in hooks or services.
5. Keep API paths and response shapes stable unless a separate product change explicitly requires a contract migration.

## Remaining extraction boundary

`app/App.jsx` still owns cross-feature orchestration, API refresh/SSE lifecycle, and modal workflows. Keep that orchestration there only while it coordinates multiple features; new page markup and domain-specific actions should live in the corresponding feature module. The next optional step is to move modal workflows into feature-owned dialog components and split the remaining orchestration hooks without changing API contracts or user-visible behavior.
