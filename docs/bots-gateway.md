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

Для каждого нового секрета используйте отдельное случайное значение. Сохраните уже работающие секреты Telegram. Публичный сертификат MAX включён в образ. Домен должен вести на сервер и открываться по HTTPS.

Если нужен только MAX, используйте `BOTS_PLATFORMS=max` и `COMPOSE_PROFILES=gateway,max`.

## Запустите и проверьте

Для Telegram и MAX на одном сервере один раз укажите в рабочем `.env` `COMPOSE_PROFILES=gateway,bots,max`. Для обновления:

```bash
cd ~/UknowApp
git pull origin test
docker compose up -d --build
```

Убедитесь, что `uknow-core`, `uknow-nats`, `uknow-tgbot`, `uknow-maxbot` и `uknow-webpanel` запущены. Проверьте диагностику ботов в админ-панели и отправьте тестовые сообщения в обе стороны.

## Обновите сервер

MAX входит в основной `docker-compose.yml`. NATS автоматически выбирает конфигурацию MAX, если задана соответствующая переменная окружения (см. раздел MAX выше). `git pull` не меняет рабочий `.env`; не запускайте второй экземпляр бота с тем же токеном и не удаляйте Docker-тома.

Для режима `local` Telegram API и для Telegram-коннектора на отдельном сервере смотрите [инструкцию Telegram](telegram-service-architecture.md). MAX-коннектор остаётся на сервере Core.


## Автовосстановление MAX Webhook

После запуска коннектор проверяет подписку и обновляет её с настроенным секретом. Затем каждые 60 секунд запрашивает список подписок через GET /subscriptions. При отсутствии нужного URL или обязательных типов событий восстанавливает подписку через POST /subscriptions. Другие подписки не удаляются, Long Polling не включается. При сбое API проверка повторяется с задержкой 60–300 секунд (или дольше по Retry-After). Сбой проверки не останавливает обработку уже принятых сообщений и исходящих заданий.

В существующем административном API GET /api/admin/bots/diagnostics в connectors.max передаются webhook_status, webhook_last_check, webhook_last_success, webhook_last_event, webhook_next_check, webhook_recoveries, webhook_failures. Времена — Unix timestamp в секундах, счётчики и время последнего принятого события относятся к текущему процессу. Статус active означает подтверждённую подписку, а не проверку доставки реального сообщения; отсутствие событий само по себе не считается сбоем. При потере связи учитывайте также online/age_seconds коннектора. Секреты и содержимое сообщений в диагностику не попадают. События, которые MAX уже перестал хранить, восстановление подписки не возвращает.
