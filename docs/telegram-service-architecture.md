# Telegram API: облачный и локальный

UknowApp работает с **одним и тем же ботом** из @BotFather в двух режимах. Режим задаёт `TELEGRAM_API_MODE` в рабочем `.env`.

| Режим | Для чего подходит | Что требуется |
| --- | --- | --- |
| `cloud` | Текст, команды, небольшие вложения | `TELEGRAM_BOT_TOKEN` |
| `local` | Большие файлы и локальный кеш Telegram | Токен бота, сервер Bot API, `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` |

## Облачный API — без дополнительных ключей

В `.env` укажите:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_API_MODE=cloud
COMPOSE_PROFILES=
```

Сохраните существующий `TELEGRAM_BOT_TOKEN`. Значение `TELEGRAM_API_URL` в этом режиме не используется: запросы направляются на `https://api.telegram.org`.

```bash
docker compose --profile telegram stop telegram-bot-api
docker compose up -d --build --force-recreate backend
docker compose logs --since=2m --tail=40 backend
```

У облачного API лимит скачивания файлов ботом **20 МБ**. Вложения, превышающие лимит, могут остаться без локальной архивной копии.

## Локальный API — на том же VPS

Получите `API ID` и `API Hash` на [my.telegram.org](https://my.telegram.org/apps). В `.env` задайте:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_API_MODE=local
COMPOSE_PROFILES=telegram
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_API_URL=http://telegram-bot-api:8081
TELEGRAM_CACHE_HOST_DIR=/srv/uknow-telegram
```

Заполните реальные ID и Hash **только в рабочем `.env`**, затем запустите `docker compose up -d --build`. Профиль `telegram` запускает отдельный контейнер. Его кеш монтируется в backend для чтения.

Для Bot API на другом сервере оставьте `COMPOSE_PROFILES` пустым, укажите приватный `TELEGRAM_API_URL` и подключите каталог кеша к основному VPS через `TELEGRAM_CACHE_HOST_DIR`. Не публикуйте незащищённый порт 8081 в интернет.

## Переход с облачного на локальный API

**Нельзя просто запустить оба сервера для одного бота.**

1. Остановите backend: `docker compose stop backend`.
2. Выполните один раз облачный метод `logOut` с токеном бота (до запуска локального сервера).
3. Укажите `TELEGRAM_API_MODE=local`, профиль `telegram`, действительные ID/Hash.
4. Запустите сервисы: `docker compose --profile telegram up -d --build`.
5. Проверьте логи и отправку `/start`, текста и вложений.

Для обратного переноса на облачный API используйте официальную процедуру Telegram по остановке локального сервера и завершению его работы. После облачного `logOut` повторный вход на облачный сервер может быть недоступен до 10 минут.

**Проверка:** `docker compose logs --tail=40 backend telegram-bot-api`. Успешное подключение бота отмечено сообщениями `TELEGRAM_CONNECTED` и `TELEGRAM_POLLING_STARTED`.

[Официальные правила переноса бота](https://github.com/tdlib/telegram-bot-api#moving-a-bot-to-a-local-server).
