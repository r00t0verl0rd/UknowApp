# Telegram API (test)

Telegram работает через отдельный коннектор `tgbot`. Core не запускает polling и не хранит токен Bot API. Настройка NATS и коннектора — в [Bots Gateway](bots-gateway.md).

## Какой режим выбрать

| | Облачный (cloud) | Локальный (local) |
| --- | --- | --- |
| API | Официальный сервер Telegram | Собственный сервер Bot API |
| Лимит вложения UknowApp (при включённом Telegram) | 20 МиБ | 888 МиБ |
| Что нужно | Токен BotFather | Токен, API ID, API Hash, сервер Bot API |

Один и тот же бот может использовать оба режима, но не одновременно.

## Быстрое переключение на одном VPS

Только администратор VPS через SSH (root или sudo), из корня проекта.
В веб-панели и Telegram команды переключения нет: Core не получает доступ к Docker.


```bash
python3 infrastructure/telegram-mode.py cloud
python3 infrastructure/telegram-mode.py local
python3 infrastructure/telegram-mode.py status
```

Выберите одну команду. Для cloud достаточно токена в .env; для local один раз
заполните API ID и Hash. Скрипт сохраняет .env в защищённую резервную копию,
добавляет недостающие секреты Gateway, меняет только нужные профили и платформы,
сохраняет PostgreSQL и тома, останавливает polling перед сменой API, вызывает
logOut на прежнем API, проверяет доступность нового API и запускает tgbot.
При возврате в cloud Telegram может блокировать вход до 10 минут; скрипт ждёт.
При ошибке после смены режима исправьте причину и повторите ту же команду.
Не запускайте другие polling-процессы с этим токеном. Команда предназначена
только для стандартной Compose-установки на одном VPS; удалённые варианты
переключаются по ручной инструкции ниже. Если ещё не применено обновление IPAM,
сначала пересоздайте сеть по инструкции Gateway (без удаления томов).

## Облачный API (ручная настройка)

Сначала настройте NATS и три секрета по [инструкции Gateway](bots-gateway.md). В `.env`:

```dotenv
COMPOSE_PROFILES=gateway,bots
BOTS_PLATFORMS=telegram
TELEGRAM_API_MODE=cloud
TELEGRAM_BOT_TOKEN=
```

Заполните токен. API ID и Hash не нужны; `TELEGRAM_API_URL` не используется. Файлы больше 20 МиБ не архивируются, но входящее сообщение сохраняется с отметкой об отсутствии файла. В веб-панели вложения сверх лимита отклоняются.

```bash
docker compose up -d --build
docker compose logs --tail=80 core nats tgbot
```

## Локальный API на одном VPS

Получите API ID и Hash на [my.telegram.org](https://my.telegram.org/apps), сохраните секреты Gateway и токен. Добавьте профиль `telegram`:

```dotenv
COMPOSE_PROFILES=gateway,bots,telegram
BOTS_PLATFORMS=telegram
TELEGRAM_API_MODE=local
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_API_URL=http://telegram-bot-api:8081
TELEGRAM_CACHE_HOST_DIR=/srv/uknow-telegram
```

Для новой установки заполните ID и Hash и выполните `docker compose up -d --build`. Если нужен PostgreSQL, сохраняйте профиль `postgres`.

## Отдельный VPS

Для удалённого Bot API не добавляйте профиль `telegram` на Core. Укажите приватный адрес API и доступный каталог кеша в настройках коннектора. Кеш монтирует только `tgbot`, не Core. Порт 8081 не публикуйте в интернет. Размещение удалённого коннектора описано в [Bots Gateway](bots-gateway.md).

## Переключение работающего бота (ручное)

> [!IMPORTANT]
> Один токен — один polling-процесс. Для переноса polling без смены Bot API не вызывайте `logOut`.

Cloud → local:

1. Остановите `tgbot` и убедитесь, что других процессов polling нет.
2. Один раз вызовите облачный метод `logOut`, до запуска локального API.
3. Настройте local-режим, профили и ID/Hash.
4. Выполните `docker compose up -d --build`.
5. Проверьте логи, `/start`, сообщения и вложения.

Local → cloud: корректно завершите работу локального API по [официальной инструкции Telegram](https://github.com/tdlib/telegram-bot-api#moving-a-bot-to-a-local-server). После облачного `logOut` возврат в облако может быть недоступен до 10 минут.

## Лимиты вложений

`TELEGRAM_API_MODE` задаёт лимит на Core и tgbot: 20 × 1024² байт в cloud,
888 × 1024² байт в local. Это ограничения UknowApp, а не гарантии Telegram
для всех типов медиа. При выключенном Telegram веб-панель сохраняет лимит 1 ГиБ.
Оба вида веб-чатов используют один лимит; ранее архивированные файлы остаются доступны.
На одном VPS скрипт пересоздаёт Core и коннектор автоматически; обновите страницу веб-панели.
На удалённом коннекторе режим должен совпадать с режимом Core.

## Проверка

```bash
docker compose ps
docker compose logs --tail=80 core nats tgbot
```

В local-режиме дополнительно проверьте логи `telegram-bot-api`. Проверьте реальные сообщения и вложения в обе стороны. Диагностика коннектора доступна администратору через `/api/admin/bots/diagnostics`.

[Настройки](../.env.example) · [Bots Gateway](bots-gateway.md)
