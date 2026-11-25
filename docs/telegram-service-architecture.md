# Telegram API

Один и тот же бот от [BotFather](https://t.me/BotFather) может работать через облачный или локальный Bot API. Режим выбирается в `.env`.

## Какой режим выбрать

| | Облачный (cloud) | Локальный (local) |
| --- | --- | --- |
| Подключение | Официальный сервер Telegram | Собственный сервер Bot API |
| Скачивание файлов ботом | До 20 МБ | Без ограничения в 20 МБ |
| Что нужно | Токен бота | Токен, API ID, API Hash и сервер Bot API |

## Облачный API

В `.env`:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_API_MODE=cloud
COMPOSE_PROFILES=
```

Заполните `TELEGRAM_BOT_TOKEN`. Дополнительные API ID и Hash не нужны; `TELEGRAM_API_URL` не используется.

Для новой установки или уже работающего cloud-режима:

```bash
docker compose up -d --build
docker compose logs --tail=40 backend
```

Файлы больше 20 МБ могут остаться без локальной архивной копии.

## Локальный API на одном VPS

Получите API ID и API Hash на [my.telegram.org](https://my.telegram.org/apps).

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_API_MODE=local
COMPOSE_PROFILES=telegram
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_API_URL=http://telegram-bot-api:8081
TELEGRAM_CACHE_HOST_DIR=/srv/uknow-telegram
```

Заполните токен, ID и Hash в рабочем `.env`. Для новой установки выполните:

```bash
docker compose up -d --build
```

Профиль `telegram` запускает контейнер Bot API; backend читает его кеш.

Для отдельного VPS оставьте профиль пустым, укажите приватный `TELEGRAM_API_URL` и подключите удалённый кеш через `TELEGRAM_CACHE_HOST_DIR`. Порт 8081 не открывайте в интернет. См. [инструкцию для двух VPS](../infrastructure/README.md).

## Как переключить работающего бота

> [!IMPORTANT]
> Один токен — один polling-процесс. Не запускайте одновременно облачный и локальный серверы для одного бота.

**Cloud → local:**

1. Остановите backend: `docker compose stop backend`.
2. Один раз вызовите облачный метод `logOut` с токеном бота, до запуска локального API.
3. Укажите local-режим, профиль и действительные ID/Hash.
4. Выполните `docker compose --profile telegram up -d --build`.
5. Проверьте логи, команду `/start`, отправку текста и вложений.

**Local → cloud:** сначала корректно завершите работу локального Bot API по [официальной инструкции Telegram](https://github.com/tdlib/telegram-bot-api#moving-a-bot-to-a-local-server). После смены настроек на cloud:

```bash
docker compose --profile telegram stop telegram-bot-api
docker compose up -d --build --force-recreate backend
```

После облачного `logOut` возврат в облако может быть недоступен до 10 минут.

## Проверка

```bash
docker compose logs --since=2m --tail=40 backend
```

При локальном режиме дополнительно проверьте `docker compose logs --tail=40 telegram-bot-api`.

Успешное подключение отмечается `TELEGRAM_CONNECTED` и `TELEGRAM_POLLING_STARTED`. Проверьте реальные сообщения и вложения в обе стороны.

[Настройки приложения](../.env.example) · [Сообщения и права](communication-architecture.md)
