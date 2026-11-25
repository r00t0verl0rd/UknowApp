# Core: производительность и отзывчивость (test)

Core и веб-API имеют приоритет над внешней доставкой. NATS один, его недоступность не останавливает веб.

## Обязательное правило SQL

Запрещено выполнять синхронные операции SQLAlchemy (включая получение соединения, lazy load, транзакции) непосредственно внутри async def на event loop. Синхронные HTTP endpoints объявляются def, FastAPI выполняет их в threadpool. Для асинхронного NATS Gateway используется run_db: отдельный пул на один рабочий поток, отдельная ORM-сессия внутри каждой операции. Не передавать ORM-объекты в event loop. В SSE проверка прав и replay выполняются в потоках с локальными сессиями. Startup миграций и restore вынесен в поток. Завершение выполняющейся транзакции не бросается при отмене задачи. Уведомление SQL outbox потокобезопасно.

CI: статическая проверка прямых синхронных вызовов в async def и runtime-проверка SQLAlchemy в backend-тестах. Медленный SQL Gateway моделируется отдельным подключением; HTTP health должен завершиться до освобождения SQL. Проверяется ограничение в один фоновой DB worker. Это не гарантия абсолютного приоритета в самом движке: SQLite всё ещё сериализует записи, PostgreSQL может ждать блокировок. Настоящие нагрузочные замеры на VPS обязательны для количественной оценки.

## Изменения горячих путей

- Подтверждение доставки не пересчитывает счётчики и превью диалога. Frontend не инициирует полное восстановление inbox из-за отсутствия summary у delivery; открытый диалог по-прежнему синхронизирует статус.
- Отметка прочтения выполняется одним атомарным UPDATE нужного JSON-поля (без перезаписи метаданных доставки); проверка отсутствия непрочитанных не создаёт ненужную запись. Delivery обновляет своё JSON-поле.
- SQLite резервирует транзакцию перед чтением изменяемого состояния отправки/удаления; PostgreSQL блокирует строки заданий. Это сохраняет корректность поздних подтверждений при удалении сообщения.
- Диагностические результаты Push записываются небольшими пакетами до 16 завершённых результатов, без ожидания сети внутри транзакции. Рассылка на все устройства остаётся независимой.
- Составные индексы очередей и подписок добавляются автоматически миграцией 20261126_06. Исторические схемы проверяются SQLite/PostgreSQL CI. Метрики очередей обновляются раз в 60 секунд вместо 30.

Остаются отдельные задачи: измерение p50/p95/p99 запросов, RAM/CPU/IO на одинаковых данных и ресурсах, оптимизация полных подсчётов непрочитанных, контроль общего размера фоновых очередей и безопасная политика хранения технических журналов. Без данных замеров не заявляем проценты ускорения.

## Main DB / Runtime DB
Производительность является обязательным критерием: избегаем повторного чтения, промежуточные вычисления — код/RAM, персистентное техническое состояние — Runtime. Main сохраняет только данные школы и минимальные гарантии целостности. Подробности: runtime-storage.md. PubAck пакетируется, ожидание пустой очереди не выполняет Main SQL до очередного сигнала или сверки.

## SSE and query budgets
SSE recovery journal is now bounded RAM (one replay hint <= 4 KiB, per-subscriber queue 128). No SQL writes for publishing or SQL reads for replay. Migration 20261126_07 removes only realtime_events, never message history. Lost cursor/restart or overflow triggers full reconciliation. Core runs one process; multiple independent Core processes would need a shared event transport. Authorization and conversation visibility are still checked against Main DB. A session is validated by a single joined SELECT, `/panel/me` uses that identity; history loads the sender via JOIN, not separate queries for messenger accounts. Query-budget regression tests enforce <=4 SQL statements for 100 messages in a teacher chat, <=3 for personal, exactly one for profile. Run `PYTHONPATH=backend python backend/tests/benchmark_core.py --messages 100000 --clients 10 50 100` for isolated ASGI measurements. CI reports p50/p95/p99 and SQL/request. This is synthetic read-only concurrency, not an external-network or VPS load test. Full-history count and unread aggregate remain potential bottlenecks.
