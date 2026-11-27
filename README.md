# UknowApp

Приложение онлайн-школы: веб-кабинет, чаты, файлы и уведомления. Telegram и MAX подключаются отдельными контейнерами. Веб-кабинет работает и без ботов.

## Новая установка

На сервере Debian установите Docker и Git, затем выполните:

```bash
git clone --branch test https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp .env.example .env
chmod 600 .env
nano .env
```

Задайте `ADMIN_PASSWORD` (не менее 16 символов) и `DOMAIN` (домен без `https://`). Для веб-кабинета без ботов оставьте настройки ботов пустыми.

Запустите веб-кабинет:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

## Подключение ботов

Инструкции по Telegram, MAX и секретам — в [руководстве по ботам](docs/bots-gateway.md). Оба бота запускаются на том же сервере, что Core.

## Обновление

Из папки проекта:

```bash
git pull --ff-only origin test
docker compose up -d --build
```

Для Telegram и MAX сохраните в рабочем `.env` `COMPOSE_PROFILES=gateway,bots,max`. После этого обновление всегда состоит из этих двух команд. `git pull` не заменяет рабочий `.env`. Не копируйте шаблон поверх настроек сервера.

## Резервная копия

В админ-панели откройте «Дополнительно» и создайте полную резервную копию. Храните `.env` отдельно и защищённо. Не удаляйте Docker-тома при обновлении.

## Документация

- [Настройки `.env`](.env.example)
- [Запуск и обслуживание ботов](docs/bots-gateway.md)
- [Режимы Telegram API](docs/telegram-service-architecture.md)
- [База данных и миграции](docs/database-migrations.md)
- [Архитектура](docs/architecture.md)
- [Тестирование](docs/ci-testing.md)
