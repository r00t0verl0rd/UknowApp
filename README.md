# UknowApp

Приложение онлайн-школы **UknowSchool**: личные кабинеты, чаты, обмен файлами, уведомления и интеграция с Telegram.

## Запуск на сервере

Подключитесь к серверу Debian по SSH. Если Docker ещё не установлен, выполните от `root`:

```bash
apt update
apt install -y git nano docker.io docker-compose docker-buildx
systemctl enable --now docker
```

Скачайте проект:

```bash
git clone https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp -n .env.example .env
chmod 600 .env
nano .env
```

Укажите в `.env`:

- `ADMIN_PASSWORD` — свой пароль (от 16 символов).
- `DOMAIN` — домен без https://.
- `VAPID_SUBJECT` — контактный email в формате `mailto:you@example.com`.
- `TELEGRAM_BOT_ENABLED=false` — если бот не нужен. Для подключения бота установите `true` и заполните `TELEGRAM_BOT_TOKEN` токеном от [BotFather](https://t.me/BotFather).

Остальные настройки можно оставить по умолчанию: SQLite и обычный Telegram API.

Укажите свой домен также в [frontend/Caddyfile](frontend/Caddyfile).

Запустите приложение:

```bash
docker compose up -d --build
docker compose ps
```

Откройте свой сайт по HTTPS. HTTPS настроится автоматически. Логин по умолчанию — `admin`, пароль — из `.env`.

## Локальный запуск

Нужны Git, Python 3.11+ и Node.js 22.12+ (Linux/macOS).

```bash
git clone https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp -n .env.example .env
```

В `.env` задайте свой `ADMIN_PASSWORD`, оставьте `DOMAIN=localhost` и отключите Telegram: `TELEGRAM_BOT_ENABLED=false`.

**Backend:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload
```

**Frontend** (в другом терминале):

```bash
cd UknowApp/frontend
npm ci
npm run dev
```

- Приложение: http://127.0.0.1:22222
- API: http://127.0.0.1:8000/docs

## Обновление на сервере

Из папки проекта:

```bash
git pull --ff-only origin main
docker compose up -d --build
```

Перед обновлением сделайте резервную копию. Не перезаписывайте рабочий `.env` и не удаляйте тома Docker (`docker compose down -v`).

## Полезные команды

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
docker compose restart
docker compose stop
```

## Резервные копии

Для SQLite: админ-панель → «Дополнительно» → полная резервная копия (ZIP). Архив включает базу и файлы приложения. Сохраните `.env` отдельно в защищённом месте; не добавляйте его в Git.

## Документация

- [Настройки приложения](.env.example)
- [Архитектура](docs/architecture.md)
- [Сообщения и права доступа](docs/communication-architecture.md)
- [PostgreSQL и миграции](docs/database-migrations.md)
- [Telegram API](docs/telegram-service-architecture.md)
- [Развёртывание на двух VPS](infrastructure/README.md)
- [Тестирование](docs/ci-testing.md)
