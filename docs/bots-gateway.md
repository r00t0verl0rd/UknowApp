# Bots Gateway: NATS JetStream (ветка test)

Core содержит SQLAlchemy, пользователей, права, назначения, диалоги, архив медиа,
SSE и push. В Core нет запуска aiogram, polling, токенов Bot API и сетевых
запросов к провайдеру. `connectors/common` содержит NATS-клиент, общий протокол,
команды, журнал входящих событий и подтверждения доставки. В `connectors/telegram`
остались SDK, Telegram API, кнопки, команды и обработка файлов. MAX пока
не является готовым адаптером; для него зарезервирована структура.

В новом режиме нет встроенного бота и нет WS-шлюза. Отдельный HTTP API Core
используется только для потоковой передачи файлов; Caddy блокирует /internal/bots/*.
Миграция 20261126_03 переносит старые идентификаторы и привязки, затем удаляет старые таблицы и колонки. Core больше не содержит старого Telegram-модуля. Состояние меню хранится в томе tgbot_state. После перехода преподаватель открывает /menu, чтобы создать новую панель; прежнее сообщение панели не переносится.

## Запуск на тестовом VPS

Не подключайте два polling-процесса к одному токену. Используйте отдельный тестовый
бот и копию БД, не рабочую школу. Сделайте проверенный бэкап базы и медиа, сохраните
.env, состояние старого коннектора и NATS том (если он уже есть).

```bash
cd ~/UknowApp
git fetch origin
git switch test
git pull --ff-only origin test
docker compose stop backend
docker compose --profile bots stop tgbot
cp -p .env .env.before-nats
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
nano .env
```

Уберите старые COMPOSE_FILE, TELEGRAM_TRANSPORT, BOTS_GATEWAY_URL,
BOTS_GATEWAY_TELEGRAM_SECRET. Укажите три разные случайные строки в пустых полях:

```dotenv
COMPOSE_PROFILES=gateway,bots
BOTS_PLATFORMS=telegram
BOTS_NATS_CORE_PASSWORD=
BOTS_NATS_TELEGRAM_PASSWORD=
BOTS_MEDIA_SECRET_TELEGRAM=
TELEGRAM_BOT_TOKEN=
TELEGRAM_API_MODE=cloud
```

Сохраните остальные параметры, токен и режим Bot API. Для локального Telegram API
в том же проекте добавьте профиль telegram, для PostgreSQL — postgres. При
размещении Bot API на другом VPS оставьте TELEGRAM_API_URL и TELEGRAM_CACHE_HOST_DIR
с прежними рабочими значениями. Core не монтирует кеш Telegram: его монтирует
только tgbot. При переносе polling без смены Bot API не вызывайте logOut.

```bash
chmod 600 .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 backend nats tgbot
```

Для веб-панели без коннекторов оставьте BOTS_PLATFORMS и COMPOSE_PROFILES пустыми
(сохраните профиль postgres, если он нужен). Остановите tgbot явно перед удалением
профиля. Для независимой сборки бота: `docker compose up -d --build tgbot`.

## Разные VPS

По умолчанию порты NATS и внутреннего API не опубликованы. Для удалённого
коннектора подключите серверы по WireGuard, ограничьте доступ к портам 4222 и 8000
IP-адресом peer, запретите публичный доступ. На Core оставьте профиль gateway
(и профиль postgres при необходимости), остановите локальный tgbot и укажите:

```dotenv
COMPOSE_FILE=docker-compose.yml:compose.gateway-remote.yml
COMPOSE_PROFILES=gateway
BOTS_PLATFORMS=telegram
BOTS_GATEWAY_BIND_IP=10.77.0.1
```

IP пример, замените своим приватным адресом. Запустите Core обычной командой.
На удалённом сервере checkout той же ревизии и отдельный .env:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_API_MODE=cloud
BOTS_NATS_URL=nats://10.77.0.1:4222
BOTS_MEDIA_URL=http://10.77.0.1:8000
BOTS_NATS_TELEGRAM_PASSWORD=
BOTS_MEDIA_SECRET_TELEGRAM=
```

Не копируйте пароль Core, админ-пароль и DATABASE_URL. Перенесите остановленный
том tgbot_state целиком (SQLite включая WAL) до старта нового коннектора.

```bash
docker compose -f compose.connector-remote.yml config --quiet
docker compose -f compose.connector-remote.yml up -d --build
```

## Протокол v1

RPC: `uknow.v1.rpc.<platform>.<operation>`. Операции account.resolve,
account.bind, conversation.list, conversation.open, endpoint.bind, delivery.authorize.
JetStream: `uknow.v1.inbound.<platform>`, `uknow.v1.outbound.<platform>`,
`uknow.v1.delivery.<platform>`. Stream UKNOW_BOTS_V1, file storage,
work-queue retention, отдельный durable consumer на каждый subject. Core
создаёт consumers. Коннектор получает только свои задания; разные логины,
пароли и namespace inbox ограничены ACL в infrastructure/nats/nats.conf.
Добавление платформы требует конфигурации ACL и платформы, а не нового
транспорта. Не используйте общий пароль Core на коннекторе.

Message + per-recipient SQL outbox и inbound receipt сохраняются одной
транзакцией. При отсутствии NATS веб-панель работает, задания остаются queued.
При публикации NATS-Msg-Id равен стабильному ID; после PubAck Core помечает
задание published. Перед отправкой коннектор перепроверяет права через RPC.
Локальный spool сохраняет входящие updates до продвижения offset. После сбоя
во время внешней отправки результат unknown, автоматически не повторяем.
ACK после сохранения результата в JetStream. Это at-least-once транспорт,
не exactly-once внешние операции. Сохраняйте nats_data, app_data, tgbot_state.

Файлы до 1 ГиБ передаются по HTTP потоком и ограничены правами платформы;
провайдер может иметь меньший лимит. Для legacy-данных импортируются аккаунты и группы, очередь queued из WS-версии переносится, незавершённая processing помечается unknown. Старые таблицы удаляются миграцией только после переноса. Панель преподавателя использует постоянную reply-клавиатуру, страницы, непрочитанные превью и историю через generic RPC. Состояние и ID панели локальны в коннекторе. Фоновые обновления идут через NATS UI invalidations без повторной отправки панели. Неподдержанные
медиа могут иметь только отметку download_failed; повтор доставки unknown
требует сверки. MAX требует самостоятельного адаптера и проверки API.

## Проверки

Тесты Core должны выполняться без aiogram. Перед main проверьте реальный
поток: привязка, команды, доступ к диалогам, текст, вложения, группы, права,
повтор событий, остановка NATS/Core/коннектора, перенос на WireGuard,
бэкап и восстановление. Не переносите экспериментальную ветку в main
без этих проверок.

## Доставка в личный чат и тему

Привязанная тема считается разрешённым дополнительным адресом доставки. Не привязывайте общую группу с посторонними участниками. Личный чат и тема получают отдельные задания, независимо от последнего входящего сообщения. В БД одна запись Message. Смена темы отменяет ещё не начатые задания на старый адрес. Старые сообщения не рассылаются повторно. Удаление внешних копий из веб-панели выполняется через постоянную очередь Universal Connector, в том числе при позднем подтверждении начатой отправки. Неизвестный результат без внешнего ID требует сверки, а провайдер может отказать в удалении. Перед обновлением сохраните БД и тома; миграция 20261126_02 меняет уникальность задания на адрес. Обновляйте backend и tgbot вместе.

Перед миграцией 20261126_03 обязательно сохраните проверенный полный бэкап. Старый backend после физического удаления колонок несовместим с новой БД: откат только с восстановлением бэкапа. Админ API использует `messenger_account` и `messenger_accounts`, отключение `/admin/users/{id}/messengers/{platform}/disconnect`. Обновляйте frontend, backend и tgbot вместе.
