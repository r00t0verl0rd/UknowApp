# Подключение Telegram и MAX

Core хранит данные школы и управляет сообщениями. `tg_bot` и `max_bot` — отдельные коннекторы. NATS передаёт задания между Core и ботами. Если бот недоступен, веб-кабинет продолжает работать.

## Подготовьте `.env`

Редактируйте рабочий `.env`, не заменяйте его файлом `.env.example`.

### Telegram

Укажите токен от BotFather и платформу:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_API_MODE=cloud
BOTS_PLATFORMS=telegram
COMPOSE_PROFILES=gateway,bots
```

Нужны три разных секрета: `BOTS_NATS_CORE_PASSWORD`, `BOTS_NATS_TELEGRAM_PASSWORD`, `BOTS_MEDIA_SECRET_TELEGRAM`.

### MAX

MAX-бот работает на сервере школы; вынести его на другой сервер нельзя. Укажите домен сайта и токен, полученный у владельца бота:

```env
DOMAIN=test.uknowschool.ru
MAX_BOT_TOKEN=...
MAX_WEBHOOK_SECRET=...
BOTS_NATS_MAX_PASSWORD=...
BOTS_MEDIA_SECRET_MAX=...
BOTS_PLATFORMS=telegram,max
COMPOSE_PROFILES=gateway,bots,max
```

Для каждого нового секрета запустите `openssl rand -hex 32` и используйте отдельный результат. Сохраните уже работающие секреты Telegram. Публичный сертификат MAX уже включён в образ; отдельный файл или параметр сертификата не нужен. Домен должен вести на сервер и открываться по HTTPS.

Если нужен только MAX, используйте `BOTS_PLATFORMS=max` и `COMPOSE_PROFILES=gateway,max`.

## Запустите и проверьте

Для Telegram и MAX на одном сервере:

```bash
cd ~/UknowApp
docker compose -f docker-compose.yml -f compose.max.yml config --quiet
docker compose -f docker-compose.yml -f compose.max.yml up -d --build
docker compose -f docker-compose.yml -f compose.max.yml ps
docker compose -f docker-compose.yml -f compose.max.yml logs --tail=80 core nats tg_bot max_bot
```

Убедитесь, что `uknow-core`, `uknow-nats`, `uknow-tgbot`, `uknow-maxbot` и `uknow-webpanel` запущены. Проверьте диагностику ботов в админ-панели и отправьте тестовые сообщения в обе стороны.

## Обновите сервер

`git pull` не меняет рабочий `.env`. После обновления кода пересоберите сервисы той же Compose-командой с `-f compose.max.yml`, если MAX подключён. Не запускайте второй экземпляр бота с тем же Telegram-токеном и не удаляйте Docker-тома.

Для режима `local` Telegram API и для Telegram-коннектора на отдельном сервере смотрите [инструкцию Telegram](telegram-service-architecture.md). MAX-коннектор остаётся на сервере Core.
