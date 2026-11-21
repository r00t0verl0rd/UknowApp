# UknowApp

**UknowApp** — веб-панель и Telegram-бот для общения онлайн-школы. Приложение хранит пользователей, назначения преподавателей, переписки и вложения в собственной базе данных.

## Что умеет

- **Администратор:** управляет пользователями, назначениями, структурой школы, переписками, досками и резервными копиями.
- **Преподаватель:** общается со своими учениками через веб-панель или Telegram.
- **Ученик:** общается с преподавателем в личном кабинете, чате бота или привязанной теме Telegram-группы.
- **Сообщения:** текст, документы, фото, видео, голосовые сообщения; обновления чатов в реальном времени и Web Push-уведомления.

Для входа в веб-панель преподаватель и ученик используют логин и код доступа, выданные администратором. Для подключения Telegram предусмотрены коды привязки.

## Быстрый запуск на VPS

Нужны Docker Engine, Docker Compose и домен, направленный на сервер. Внешние порты — 80 и 443.

```bash
git clone https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp .env.example .env
nano .env
```

Заполните в `.env` **`TELEGRAM_BOT_TOKEN`**, **`ADMIN_PASSWORD`** и **`DOMAIN`**. Для стандартного Telegram API оставьте `TELEGRAM_API_MODE=cloud` и пустой `COMPOSE_PROFILES`; ключи API ID/Hash не нужны. Остальные настройки описаны в `.env.example`.

```bash
chmod 600 .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=40 backend
```

Панель доступна по `https://<ваш-домен>`. Проверка API — `/api/health`. Для бота в логах ожидаются `TELEGRAM_CONNECTED` и `TELEGRAM_POLLING_STARTED`.

## Обновление

```bash
git pull --ff-only origin main
docker compose up -d --build
```

**Важно:** обновление `.env.example` не меняет действующий `.env`. Новые параметры при необходимости добавляйте в него вручную. Не заменяйте `.env` шаблоном и не выполняйте `docker compose down -v` при обычном обновлении.

## Локальная разработка

Нужны Python 3.11+ и Node.js 22+.

```bash
# Первый запуск: создайте .env из шаблона и настройте его.
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload
```

В другом терминале:

```bash
cd frontend
npm ci
npm run dev
```

Адрес разработки: `http://127.0.0.1:22222`. Документация HTTP API: `http://127.0.0.1:8000/docs`.

## Данные и резервные копии

В Docker база SQLite, медиафайлы и ключ Web Push находятся в постоянном томе `app_data`. В разделе **«Дополнительно»** администратор может скачать полную резервную копию и восстановить её. Архив содержит данные приложения, но **не содержит `.env`, токен бота и TLS-сертификаты**. Храните его в защищённом месте.

Не копируйте работающую SQLite-базу простым копированием одного `.db`-файла: используйте встроенное резервное копирование.

## Подробнее

- [Устройство проекта](docs/architecture.md)
- [Сообщения и права доступа](docs/communication-architecture.md)
- [Стандартный и локальный Telegram API](docs/telegram-service-architecture.md)
