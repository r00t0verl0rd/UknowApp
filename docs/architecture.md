# Архитектура UknowApp (test)

UknowApp — самостоятельная образовательная платформа. Основные функции работают в браузере, даже без Telegram. Мессенджеры — дополнительные каналы общения, а не источник данных.

## Из чего состоит приложение

| Компонент | Технология | Назначение |
| --- | --- | --- |
| Frontend | SolidJS | Личные кабинеты и чаты |
| Backend | FastAPI | API, права доступа, бизнес-логика |
| База данных | SQLite / PostgreSQL | Пользователи, диалоги и другие данные |
| Bots Gateway | NATS JetStream | Связь Core с независимыми коннекторами |
| Telegram | Bot API | Отдельный коннектор для общения |
| Caddy | HTTPS, reverse proxy | Доступ к сайту |

Сейчас реализованы кабинеты администратора, преподавателя и ученика. Вкладка «Доски» пока пустая; видеосвязь планируется.

## Backend

Основная папка: [backend/app](../backend/app/).

| Путь | Назначение |
| --- | --- |
| `main.py`, `api.py` | Запуск Core, HTTP API и опциональный NATS Gateway |
| `core/` | Настройки, база данных и безопасность |
| `models.py`, `migrations/` | SQLAlchemy-модели и автоматические миграции |
| `modules/auth/`, `modules/users/` | Авторизация, сессии и пользователи |
| `modules/assignments/`, `modules/conversations/` | Назначения и диалоги |
| `modules/communication/`, `modules/messaging/` | Обработка и доставка сообщений |
| `bots_gateway/` | NATS, RPC и события коннекторов |
| `modules/communication/outbox.py` | Очередь внешней доставки |
| `modules/messaging/read_state.py` | Прочтения в панели и Gateway |
| `modules/personal_chat/` | Личные диалоги; HTTP-маршруты в `modules/panel/` |
| `modules/administration/` | Управление школой, `backup.py`, `restore.py`, `stats.py` |
| `modules/notifications/` | Web Push |
| `infrastructure/storage/` | Хранение вложений |
| `event_hub.py` | События для обновления интерфейса |

Telegram-коннектор работает отдельным процессом в `connectors/telegram/`. Core не запускает polling и не обращается к Bot API.

## Frontend

Основная папка: [frontend/src](../frontend/src/).

| Путь | Назначение |
| --- | --- |
| `app/` | Вход и запуск интерфейса |
| `workspaces/` | Кабинеты пользователей |
| `features/` | Пользователи, структура, переписки, администрирование и уведомления |
| `shared/components/`, `shared/state/` | Общие компоненты и состояние |
| `shared/services/` | API и единое SSE-подключение |
| `shared/styles/` | Стили и темы |

SSE (Server-Sent Events) передаёт краткие обновления всех диалогов. Полная история загружается только для открытого чата.

Общие стили подключаются через `index.scss`, стили ролей — лениво из `AdminWorkspace` и `TeacherWorkspace`. `StudentWorkspace` загружает общие стили досок, диалог восстановления имеет отдельный CSS-чанк; `critical.css` входит в версионированный CSS первого кадра. Для кнопок с одной иконкой используйте общий `IconButton.jsx` и стили `icon-actions.scss`: `tone="danger"` для опасных действий, `size="compact"` для компактного варианта. Подробнее — [правила SCSS](../frontend/src/shared/styles/README.md).

## Как добавить новую роль

1. Определите права, доступные данные и действия.
2. Настройте серверные проверки, вход и сессии.
3. Добавьте кабинет в `frontend/src/workspaces/workspaceRegistry.js`.

Скрытие кнопок не заменяет проверку прав на сервере. Одной регистрации кабинета недостаточно.

## Развёртывание и хранение

`docker-compose.yml` запускает `core` и `web_panel` (Caddy). Дополнительные сервисы включаются профилями: `gateway` для NATS, `bots` для Telegram-коннектора, `telegram` для локального Bot API, `postgres` для PostgreSQL.

| Том Docker | Что хранится |
| --- | --- |
| `app_data` | SQLite, вложения и ключ Web Push |
| `caddy_data`, `caddy_config` | Данные и конфигурация Caddy |
| `postgres_data` | Данные PostgreSQL (если включён) |
| `nats_data` | Состояние брокера |
| `tgbot_state` | Локальное состояние Telegram-коннектора |

Core автоматически обновляет схему при запуске. Техническое состояние хранится в отдельной Runtime DB внутри каталога `data`.

## Основные правила

- Платформа должна работать без мессенджеров.
- Общая логика сообщений не должна зависеть от Telegram.
- Для одного токена бота допускается только один polling-процесс.
- Новые роли и учебные модули подключаются независимо.
- Секреты не хранятся в Git, тома Docker не удаляются при обновлении.

[Bots Gateway](bots-gateway.md) · [Main DB и Runtime DB](runtime-storage.md) · [Сообщения и права доступа](communication-architecture.md) · [База данных](database-migrations.md) · [Запуск приложения](../README.md)

При первом обновлении со старых имён остановите и удалите только существующие контейнеры со старыми именами `backend`, `frontend` или `web-panel`, `tgbot` и `maxbot`. Затем запустите Compose с теми же файлами, профилями и именем проекта. Это освобождает фиксированные адреса и порты и исключает одновременный запуск двух экземпляров одного бота. Именованные тома сохраняются.
