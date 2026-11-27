# Telegram Bot API

Telegram работает в отдельном контейнере `uknow-tgbot`. Core хранит школьные данные и проверяет доступы; токен Telegram находится только в `.env` и передаётся коннектору.

## Выберите режим

| Режим | Настройки | Ограничение UknowApp |
| --- | --- | --- |
| `cloud` | Токен от BotFather | Файлы до 20 МиБ |
| `local` | Токен, API ID и API Hash | Файлы до 888 МиБ |

По умолчанию используйте `cloud`. Не запускайте одновременно два polling-процесса с одним токеном.

## Настройка

Для `cloud` задайте в `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_API_MODE=cloud
BOTS_PLATFORMS=telegram
COMPOSE_PROFILES=gateway,bots
```

Для `local` сначала получите API ID и API Hash на [my.telegram.org/apps](https://my.telegram.org/apps), затем укажите их:

```env
TELEGRAM_API_MODE=local
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
COMPOSE_PROFILES=gateway,bots,telegram
```

Создайте секреты NATS и передачи файлов по [руководству по ботам](bots-gateway.md). Для локального режима запустите Telegram Bot API:

```bash
docker compose up -d --build
```

Для переключения стандартной установки на одном VPS используйте скрипт от `root` из папки проекта:

```bash
python3 infrastructure/telegram-mode.py cloud
python3 infrastructure/telegram-mode.py local
python3 infrastructure/telegram-mode.py status
```

Запускайте одну команду за раз. Скрипт сохраняет `.env` и сам останавливает прежний polling перед переключением. Для коннектора на отдельном сервере или установки с MAX overlay этот скрипт не используйте: он не управляет удалённым коннектором и Compose-файлом MAX.

Подробнее о подключении MAX и общих профилях — в [руководстве по ботам](bots-gateway.md). Кеш Telegram Bot API хранится отдельно от Core; не удаляйте его том или каталог при обновлении.
