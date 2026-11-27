# UknowApp

Приложение онлайн-школы **UknowSchool**: личные кабинеты, чаты, обмен файлами, уведомления и интеграция с Telegram.

Ветка `test`: независимые коннекторы мессенджеров через NATS JetStream. Веб-панель работает без ботов.

## Запуск на сервере

Подключитесь к серверу Debian по SSH. Если Docker ещё не установлен, выполните от `root`:

```bash
apt update
apt install -y git nano docker.io docker-compose docker-buildx
systemctl enable --now docker
```

Скачайте проект:

```bash
git clone --branch test https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp -n .env.example .env
chmod 600 .env
nano .env
```

Укажите в `.env`:

- `ADMIN_PASSWORD` — свой пароль (от 16 символов).
- `DOMAIN` — домен без https://.
- `VAPID_SUBJECT` — контактный email в формате `mailto:you@example.com`.
- `COMPOSE_PROFILES` и `BOTS_PLATFORMS` — оставьте пустыми для запуска без ботов.

Для подключения Telegram используйте [инструкцию Bots Gateway](docs/bots-gateway.md).

Запустите приложение:

```bash
docker compose up -d --build
docker compose ps
```

## Локальный запуск

Нужны Git, Python 3.11+ и Node.js 22.12+ (Linux/macOS).

```bash
git clone --branch test https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp -n .env.example .env
```

В `.env` задайте свой `ADMIN_PASSWORD`, оставьте `DOMAIN=localhost` и оставьте `BOTS_PLATFORMS` пустым.

**Backend:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload
```

**Frontend** (в другом терминале, из папки проекта):

```bash
cd frontend
npm ci
npm run dev
```

- Приложение: http://127.0.0.1:22222
- API: http://127.0.0.1:8000/docs

## Обновление на сервере

Из папки проекта:

```bash
git pull --ff-only origin test
docker compose up -d --build
```

Перед обновлением сделайте резервную копию. Если подключены коннекторы, обновляйте Core, конфигурацию NATS и коннекторы вместе. Не перезаписывайте рабочий `.env` и не удаляйте тома Docker (`docker compose down -v`).

## Полезные команды

```bash
docker compose ps
docker compose logs --tail=100 core
docker compose logs --tail=100 web-panel
docker compose restart
docker compose stop
```

## Резервные копии

Для SQLite: админ-панель → «Дополнительно» → полная резервная копия (ZIP). Архив включает базу и файлы приложения. Для точного восстановления также сохраняйте Runtime, медиа и тома NATS и коннекторов согласованно. Сохраните `.env` отдельно в защищённом месте; не добавляйте его в Git.

## Документация

- [Настройки приложения](.env.example)
- [Архитектура](docs/architecture.md)
- [Сообщения и права доступа](docs/communication-architecture.md)
- [PostgreSQL и миграции](docs/database-migrations.md)
- [Telegram API](docs/telegram-service-architecture.md)
- [Развёртывание на двух VPS (старый комплект)](infrastructure/README.md)
- [Тестирование](docs/ci-testing.md)
- [Bots Gateway](docs/bots-gateway.md)
- [Хранение данных Core и Runtime](docs/runtime-storage.md)
- [Производительность Core](docs/core-performance.md)
- [Web Push на нескольких устройствах](docs/push-devices.md)
- [Стили SCSS](frontend/src/shared/styles/README.md)
