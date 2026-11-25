# База данных и миграции

По умолчанию UknowApp использует SQLite. PostgreSQL поддерживается как дополнительный вариант. Модели данных находятся в `backend/app/models.py`, подключение определяется настройкой `DATABASE_URL`.

## Выбор базы

| | SQLite | PostgreSQL |
| --- | --- | --- |
| Настройка | Пустой `DATABASE_URL` | URL подключения через `psycopg` |
| Docker | Том `app_data` | Профиль `postgres`, том `postgres_data` |
| Резервные копии | Встроенный ZIP и экспорт базы | `pg_dump`, `pg_restore` и отдельная копия файлов |

> [!IMPORTANT]
> Смена `DATABASE_URL` не переносит данные. Автоматической миграции между SQLite и PostgreSQL пока нет.

## Новый сервер с PostgreSQL

Только для новой пустой установки. В `.env` задайте:

```dotenv
COMPOSE_PROFILES=postgres
POSTGRES_DB=uknowapp
POSTGRES_USER=uknowapp
POSTGRES_PASSWORD=YOUR_PASSWORD
DATABASE_URL=postgresql+psycopg://uknowapp:YOUR_PASSWORD@postgres:5432/uknowapp
```

Замените `YOUR_PASSWORD` своим надёжным паролем. В URL специальные символы пароля должны быть URL-кодированы.

После проверки миграций выполните:

```bash
docker compose --profile postgres up -d postgres
docker compose build backend
docker compose --profile postgres run --rm --no-deps backend alembic -c /app/alembic.ini upgrade head
docker compose up -d --build
```

Внешний порт PostgreSQL не открывается.

## Как работают миграции

При запуске `initialize_database()` создаёт отсутствующие таблицы и выполняет старые одноразовые миграции. Это механизм совместимости с действующими установками, а не полноценный Alembic-only режим.

Новые изменения схемы оформляются отдельными ревизиями Alembic. Не добавляйте их в `initialize_database()`; старый механизм удаляйте только в рамках отдельной проверенной миграции развёртывания.

### Начальная ревизия

`20261123_01` создаёт отсутствующие таблицы, не удаляя записи и не меняя существующие столбцы. Перед её применением к старой базе убедитесь, что прежние миграции уже выполнены. Откат этой ревизии запрещён намеренно.

Для действующей SQLite-базы:

1. Сделайте полный ZIP и проверьте восстановление на тестовой копии.
2. Запустите обновлённое приложение и проверьте его работу.
3. На тестовой копии выполните `alembic upgrade head`, затем `alembic current` и `alembic check`.
4. Только после успешной проверки выполните на основном сервере:

```bash
docker compose exec backend alembic -c /app/alembic.ini upgrade head
docker compose exec backend alembic -c /app/alembic.ini current
```

### Новая миграция

1. Сделайте резервную копию и проверьте восстановление.
2. На копии базы создайте черновик ревизии:

   ```bash
   alembic -c alembic.ini revision --autogenerate -m "описание изменения"
   ```

3. Проверьте весь файл: `DROP`/`ALTER`, переименования, типы, внешние ключи, индексы, значения по умолчанию и перенос данных. Alembic не всегда распознаёт переименования.
4. Используйте явные операции (`op.create_table`, `op.add_column` и т. д.), а не `create_all()`.
5. Проверьте миграцию на копиях SQLite и PostgreSQL: целостность данных, пользовательские функции, диалоги и резервные копии.
6. После код-ревью запустите `upgrade head` на сервере вручную.

> [!WARNING]
> Не включайте `alembic upgrade head` в Docker CMD или startup-hook. Новые миграции не должны выполняться автоматически при запуске веб-сервера.

## Резервные копии PostgreSQL

Встроенные операции ZIP, экспорта и восстановления SQLite недоступны при PostgreSQL (HTTP 501). Сохраняйте две части отдельно:

- Базу через `pg_dump`; проверяйте восстановление через `pg_restore`.
- Каталог данных, включая медиа и VAPID-ключи.

SQL-дамп не содержит файлы приложения. ZIP SQLite не подходит для восстановления PostgreSQL.

[Архитектура](architecture.md) · [Настройки](../.env.example)
