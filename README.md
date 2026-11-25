# UknowApp

**UknowApp** — основное приложение онлайн-школы **UknowSchool** и основа будущей образовательной платформы. Сейчас в нём работают личные кабинеты и диалоги для общения. Боты разных мессенджеров подключаются как дополнительные модули; в текущей версии доступна интеграция с Telegram.

Платформа будет расширяться: планируется добавление видеосвязи.

## Что работает сейчас

- **Администратор:** управляет пользователями, назначениями, структурой школы, переписками и резервными копиями.
- **Преподаватель:** общается с учениками в приложении или через подключённого Telegram-бота.
- **Ученик:** общается с преподавателем в личном кабинете, а при подключении Telegram — через бота или привязанную тему группы.
- **Сообщения:** текст, документы, фото, видео, голосовые сообщения; обновления чатов в реальном времени и Web Push-уведомления.

Вкладка **«Доски»** остаётся в панели администратора, но сейчас пуста.

Сейчас поддерживаются три роли: администратор, преподаватель и ученик. **Этот список не окончательный:** при развитии школы можно добавлять новые роли с собственными правами и интерфейсами. Для входа преподаватель и ученик используют логин и код доступа, выданные администратором; для подключения Telegram предусмотрены коды привязки.

## Развёртывание на VPS с нуля

Инструкция для чистого VPS с **Debian 13 (trixie), amd64/x86_64 и systemd**.
Основной сценарий — один сервер, SQLite и облачный Telegram Bot API (или без бота).
Для уже работающей установки используйте раздел [Обновление](#обновление), не повторяйте первичную настройку.

### 1. DNS, сеть и подключение

- Направьте DNS A-записи `uknowschool.ru` и `www.uknowschool.ru` на публичный IPv4 VPS. Если есть AAAA-записи, они должны указывать на рабочий IPv6 этого же сервера; иначе удалите устаревшие записи.
- Разрешите на внешнем firewall и на VPS TCP 80 и 443 для HTTP/HTTPS, UDP 443 для HTTP/3 (необязательно), TCP 22 для SSH. Порты backend, PostgreSQL и Telegram Bot API публично не открывайте.
- В текущем `frontend/Caddyfile` имена `uknowschool.ru, www.uknowschool.ru` заданы явно. Для другого домена измените и Caddyfile, и параметр `DOMAIN` в `.env` до сборки. Caddy получает TLS-сертификаты автоматически при корректном DNS и доступных портах.

На своём компьютере подключитесь к серверу (замените VPS_IP на публичный адрес):

```bash
ssh root@VPS_IP
```

Команды разделов 2–3 выполняются от `root`, без `sudo`. Не копируйте символы приглашения терминала.

### 2. Установка Docker, Compose и Buildx

На действующем VPS 25 ноября 2026 года проверена следующая комбинация:

| Компонент | Рабочая версия |
| --- | --- |
| Docker Engine / CLI (Debian) | 26.1.5+dfsg1 |
| Docker Compose (официальный CLI-плагин) | v5.8.0 |
| Docker Buildx (официальный CLI-плагин) | v0.17.1 |

Ниже используется Docker Engine из репозитория Debian и два официальных плагина GitHub Releases. Версия Engine зависит от текущих обновлений безопасности Debian; намеренно не фиксируем и не понижаем её. Compose и Buildx фиксируем на проверенных версиях. Для новой установки также допустим полностью официальный комплект из [репозитория Docker CE](https://docs.docker.com/engine/install/debian/) с совместимыми актуальными версиями; не смешивайте пакеты двух дистрибутивов Engine.

Установите необходимые пакеты:

```bash
apt-get update
apt-get install -y ca-certificates curl git nano docker.io docker-compose
systemctl enable --now docker
```

В Debian 13 пакет `docker-compose` может содержать Compose 2.26.1 и старый Buildx 0.13.1. У старого Compose наблюдалось мигание курсора и повреждение динамических строк при сборке через SSH. Новый Compose 5.8.0 требует Buildx не ниже 0.17.0. Поэтому на этой конфигурации устанавливаем **оба** плагина в системный каталог `/usr/local/lib/docker/cli-plugins`, который имеет приоритет над пакетными плагинами.

Загрузите официальные бинарные файлы, проверьте SHA-256 по файлам контрольных сумм соответствующих релизов, затем установите их. Блок в скобках выполняется в отдельной оболочке; при ошибке загрузки или проверки установка не продолжится.

```bash
(
  set -eu
  tmp=$(mktemp -d)
  trap 'rm -rf -- "$tmp"' EXIT
  cd "$tmp"

  curl -fsSL https://github.com/docker/compose/releases/download/v5.8.0/docker-compose-linux-x86_64 \\
    -o docker-compose-linux-x86_64
  curl -fsSL https://github.com/docker/compose/releases/download/v5.8.0/checksums.txt \\
    -o compose-checksums.txt
  grep -E '[[:space:]]\*?docker-compose-linux-x86_64$' compose-checksums.txt | sha256sum -c -

  curl -fsSL https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-amd64 \\
    -o buildx-v0.17.1.linux-amd64
  curl -fsSL https://github.com/docker/buildx/releases/download/v0.17.1/checksums.txt \\
    -o buildx-checksums.txt
  grep -E '[[:space:]]\*?buildx-v0\.17\.1\.linux-amd64$' buildx-checksums.txt | sha256sum -c -

  install -d -m 0755 /usr/local/lib/docker/cli-plugins
  install -m 0755 docker-compose-linux-x86_64 /usr/local/lib/docker/cli-plugins/docker-compose
  install -m 0755 buildx-v0.17.1.linux-amd64 /usr/local/lib/docker/cli-plugins/docker-buildx
)
```

Проверьте установку:

```bash
docker --version
docker compose version
docker buildx version
docker buildx ls
docker run --rm hello-world
```

Ожидаемые версии плагинов: Compose `v5.8.0`, Buildx `v0.17.1`. Если отображаются другие версии, проверьте пути плагинов в `docker info` (в том числе пользовательские плагины в `~/.docker/cli-plugins`).

Установка CLI-плагинов не требует перезапуска Docker Engine. Плагины, установленные вручную, APT не обновляет: отслеживайте обновления безопасности и совместимость отдельно. См. [установка Compose](https://docs.docker.com/compose/install/linux/) и [релиз Buildx](https://github.com/docker/buildx/releases/tag/v0.17.1).

### 3. Пользователь приложения

От `root`:

```bash
id uknow >/dev/null 2>&1 || useradd -m -s /bin/bash uknow
usermod -aG docker uknow
```

Группа `docker` фактически предоставляет привилегии root. Добавляйте в неё только доверенных администраторов.

Отдельной командой откройте новый сеанс пользователя, чтобы применилось членство в группе:

```bash
su - uknow
```

**Далее команды выполняются уже от `uknow`**, в новом приглашении терминала.

```bash
id
docker compose version
docker buildx version
docker ps
```

### 4. Загрузка проекта и настройка окружения

```bash
cd ~
git clone --branch main https://github.com/r00t0verl0rd/UknowApp.git
cd ~/UknowApp
umask 077
cp -n .env.example .env
chmod 600 .env
nano .env
```

Для новой установки с SQLite и облачным Telegram API задайте в `.env` следующие параметры:

```ini
DOMAIN=uknowschool.ru
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace-with-your-own-unique-password
TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_API_MODE=cloud
COMPOSE_PROFILES=
DATABASE_URL=
SEED_DEMO_DATA=false
ALLOWED_ORIGINS=
VAPID_SUBJECT=mailto:admin@example.com
```

Замените пример пароля на уникальный пароль длиной не менее 16 символов, укажите реальный контакт Web Push и токен бота от BotFather. Если Telegram не нужен, установите `TELEGRAM_BOT_ENABLED=false` и оставьте токен пустым. Для cloud-режима `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` не нужны. Остальные параметры описаны в [`.env.example`](.env.example). В nano сохранение — Ctrl+O, Enter; выход — Ctrl+X.

Не добавляйте `.env` в Git и не копируйте шаблон поверх существующего файла с рабочими секретами.

### 5. Сборка и первый запуск

```bash
cd ~/UknowApp
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=40 backend
docker compose logs --tail=40 frontend
```

Используются обычные команды Docker Compose, без вспомогательного скрипта, принудительного отключения ANSI или изменения настроек терминала. Frontend запускается после успешного healthcheck backend.

### 6. Проверка после запуска

```bash
docker compose ps
docker compose exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read().decode())"
curl -fsS https://uknowschool.ru/api/health
```

Панель доступна по адресу https://uknowschool.ru (для другого домена замените адрес в команде и браузере). Войдите с заданными `ADMIN_USERNAME` и `ADMIN_PASSWORD`. В `docker compose ps` backend должен быть healthy, frontend — запущен и после проверки тоже healthy. Если TLS ещё выпускается, проверьте DNS и логи frontend и повторите HTTPS-проверку. При включённом Telegram в логах backend ожидаются `TELEGRAM_CONNECTED` и `TELEGRAM_POLLING_STARTED`; отдельно проверьте отправку сообщений и вложений в обе стороны.

Для отдельного VPS с локальным Telegram Bot API, WireGuard и NFS см. [инструкцию по инфраструктуре](infrastructure/README.md) и [архитектуру Telegram API](docs/telegram-service-architecture.md). Не меняйте cloud/local на работающем боте без процедуры миграции. PostgreSQL описан ниже отдельно.

## Обновление

От пользователя `uknow`:

```bash
cd ~/UknowApp
git pull --ff-only origin main
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=40 backend
```

Перед обновлением действующей школы скачайте и проверьте резервную копию через админ-панель (SQLite) или предусмотрите отдельный бэкап PostgreSQL и файлов. Пересоздание контейнеров может вызвать короткий перерыв в работе.

**Важно:** обновление `.env.example` не меняет действующий `.env`. Новые параметры при необходимости добавляйте в него вручную. Не заменяйте `.env` шаблоном и не выполняйте `docker compose down -v`, `docker volume prune` или удаление каталога данных Docker при обычном обновлении.

### Диагностика Docker

Если прогресс сборки снова мигает или строки накладываются друг на друга:

```bash
docker --version
docker compose version
docker buildx version
echo "$TERM"
stty size
docker compose ps
```

Если возникает `compose build requires buildx 0.17.0 or later`, обновите Buildx до совместимой версии (см. шаг 2). При `no configuration file provided: not found` перейдите в `~/UknowApp`. Не переустанавливайте Docker Engine и не удаляйте его данные для устранения проблем CLI-плагина.

## SQLite, PostgreSQL и миграции

По умолчанию UknowApp использует SQLite. В Docker том `app_data` сохраняется при пересборке.
Подключение выбирается через `DATABASE_URL`; бизнес-модели используют SQLAlchemy.
Существует опциональный сервис `postgres` (PostgreSQL 17), не открывающий внешний порт.

Для **нового пустого** развёртывания PostgreSQL задайте в `.env`:

```ini
COMPOSE_PROFILES=postgres
POSTGRES_DB=uknowapp
POSTGRES_USER=uknowapp
POSTGRES_PASSWORD=замените-на-надежный-пароль
DATABASE_URL=postgresql+psycopg://uknowapp:замените-на-надежный-пароль@postgres:5432/uknowapp
```

Пароль в URL должен быть URL-кодирован, если содержит специальные символы (`@`, `:`, `/`, `%` и др.).
Перед запуском приложения и **после проверки миграций** выполните:

```bash
docker compose --profile postgres up -d postgres
docker compose build backend
docker compose --profile postgres run --rm --no-deps backend alembic -c /app/alembic.ini upgrade head
docker compose up -d --build
```

Для существующей SQLite-инсталляции **не меняйте DATABASE_URL** без плана переноса данных.
Само изменение URL **не переносит** пользователей, переписки, медиа и другие записи.
Перед работой со схемой скачайте полную резервную копию, проверьте миграцию и её эффект на копии данных.

В проект добавлен Alembic для **ручного управления будущими миграциями**. `revision --autogenerate`
создаёт только черновик; запуск `upgrade head` требует отдельного решения.
Чтобы не ломать существующие установки, прежняя стартовая инициализация схемы пока сохранена
как переходная совместимость. Подробности и ограничения: [миграции и СУБД](docs/database-migrations.md).

Встроенные **полный ZIP** и **экспорт/импорт базы** предназначены только для SQLite.
Для PostgreSQL используйте `pg_dump` и `pg_restore`, а файлы медиа и ключ Web Push сохраняйте отдельно.
В админ-панели операции SQLite-бэкапа автоматически недоступны при подключении PostgreSQL.

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

Для переноса всей школы используйте полный ZIP. Приложение проверяет контрольные суммы, целостность SQLite и доступность локальных вложений в учебных и личных чатах. Отдельную базу можно восстановить при наличии соответствующих файлов в каталоге медиа. При смене пути SQLite полный импорт размещает снимок по настройке нового сервера.

Оба вида восстановления применяются при запуске backend. В Docker перезапуск автоматический. Статус «восстановлено» появляется после миграций, проверки схемы и запуска служб приложения. При ошибке запуска или прерывании применения сервер возвращает предыдущие данные. Для переноса на другой сервер отдельно перенесите настройки окружения и учётные данные внешних сервисов.

Не копируйте работающую SQLite-базу простым копированием одного `.db`-файла: используйте встроенное резервное копирование.

## Подробнее

- [Устройство проекта](docs/architecture.md)
- [Сообщения и права доступа](docs/communication-architecture.md)
- [Стандартный и локальный Telegram API](docs/telegram-service-architecture.md)
