# Тестирование UknowApp (test)

GitHub Actions проверяет сборку, работу интерфейса, серверную логику и безопасность. Полный Project checks запускается при каждом push в `main` и `test`, а также при pull request. Тесты используют изолированные данные и не затрагивают рабочую базу школы.

## Что проверяет CI

| Задача | Что проверяется |
| --- | --- |
| `frontend` | Сборка Vite/Solid, unit-тесты, SCSS, Stylelint и аудит CSS |
| `frontend-browser` | Вход, права доступа, диалоги, SSE и push-уведомления в браузере |
| `backend` | Ruff, Vulture, Bandit, detect-secrets и pytest: авторизация, сообщения, Telegram, SSE, push |
| `backup-function` | ZIP, контрольные суммы, вложения, восстановление и откат при ошибках |
| NATS Gateway checks | Core без aiogram, тесты коннекторов, NATS RPC/JetStream, Compose и синтетический benchmark |
| Database compatibility | Автоматические миграции на SQLite и PostgreSQL |
| PWA icons | Генерация PNG при изменении исходной иконки или скрипта |

Unit-тесты frontend также проверяют прочтения, даты, CSP, первый рендер и PWA-иконки. Браузерные тесты включают подробный интеграционный сценарий.

`backend/tests/test_board_removal.py` защищает от случайного возвращения удалённых API и таблиц досок. Тесты резервного копирования запускаются отдельно, без повторения в основной задаче backend Project checks. Отдельный Gateway workflow также запускает полный набор backend-тестов.

## Как запустить тесты локально

### Frontend

Из корня проекта:

```bash
cd frontend
npm ci
npm test
npm run build
```

Для браузерных тестов:

```bash
npm install --no-save playwright@1.56.1
npx playwright install --only-shell chromium
npm run test:browser
```

Можно использовать уже установленный совместимый браузер через `CHROMIUM_PATH`. Тесты проверяют собранный `dist` через `vite preview`.

### Backend

Из корня проекта, в активном Python-окружении:

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install ruff vulture bandit detect-secrets pytest httpx
ruff check app --extend-select BLE001,SIM115,B008
python -m pytest -q tests
```

Только резервное копирование и восстановление:

```bash
python -m pytest -q tests/test_admin_data_backup.py tests/test_restore_startup.py
```

### Стили

Для работы с дизайном см. [правила SCSS](../frontend/src/shared/styles/README.md). CI проверяет сборку и архитектуру стилей, но не требует побайтового совпадения CSS с предыдущим коммитом.

### Gateway и база данных

Дополнительные проверки находятся в [bots-gateway.yml](../.github/workflows/bots-gateway.yml) и [database-ci.yml](../.github/workflows/database-ci.yml). См. [Bots Gateway](bots-gateway.md), [миграции](database-migrations.md) и [производительность Core](core-performance.md).

## Как ускорены проверки

- Задачи frontend, browser, backend и backup выполняются параллельно.
- Playwright Chromium Headless Shell сохраняется в кэше GitHub Actions.
- Браузерные сценарии используют production-сборку вместо dev-сервера.
- Ruff выполняет все нужные правила одним проходом, включая BLE001, SIM115 и B008.
- Backend и backup используют `uv pip install --system` с кэшем и Python 3.11.
- Четыре повторяющихся PBKDF2-хеша кэшируются только в тестовых фикстурах. Production-хеширование не менялось.
- Повторный импорт `app.main` и прежний Compose/browser-тест переноса убраны: их покрывают pytest и backup-function.
- Новый push или PR отменяет устаревший прогон той же ветки, не затрагивая другие ветки.

Покрытие и проверки безопасности сохранены. Ускорять CI за счёт отключения тестов не нужно.

## Оптимизации приложения

Изменения от 23 ноября 2026 года:

| Что изменилось | Результат |
| --- | --- |
| Динамическая загрузка кабинетов через `workspaceRegistry.js` | Код кабинетов загружается после проверки роли, чаты — при переходе к ним |
| Разделение JavaScript | Меньше кода при первом открытии сайта |
| Push-подписка после входа | Кабинет открывается без ожидания необязательной подписки; параллельная инициализация не дублирует подписку |
| Кэширование Caddy | Хешированные `/assets/*` кэшируются на год; отсутствующие файлы возвращают 404 |

Политика кэширования HTML, API и service worker сохранена. Задержанная push-подписка проверяется регрессионным тестом.

## История замеров

Замеры зафиксированы 23 ноября 2026 года в прежней архитектуре, до отдельного Gateway и database CI. Это исторические результаты, не замеры текущей ветки `test`.

| Задача | До оптимизаций (`ec1484f`) | После оптимизации CI (`a278a3e`) | После изменений загрузки |
| --- | ---: | ---: | ---: |
| Полный CI | — | 36 с | 29 с |
| Frontend | 226 с | 18 с | 11 с |
| Browser | — | 32 с | 25 с |
| Backend | 50 с | 27 с | 26 с |
| Backup | — | 28 с | 18 с |

Ранее отдельный migration job занимал 141 с; его заменил backup-function, поэтому прямое сравнение некорректно. Из 226 с первоначального frontend 193 с занимала установка Chromium, в migration — 46 с. После замены браузера два сценария занимали примерно 5,5 и 1,2 с вместо 17,5 и 12,3 с.

| Метрика сборки | До разделения | После |
| --- | --- | --- |
| Стартовый JS | 144,36 КБ | 47,18 + 60,85 КБ |
| Стартовый JS (gzip) | 49,03 КБ | 16,17 + 23,39 КБ |
| CSS (gzip) | — | 20,47 КБ |
| Vite build | 522 мс | 835 мс |

Стартовый JS уменьшился примерно на 19% по gzip. Разделение кода ускоряет загрузку страницы, а не саму компиляцию Vite. Время CI зависит от очередей, кэша и загрузки runners; параллельные задачи могут потреблять больше суммарных runner-минут.

[Архитектура](architecture.md) · [Запуск приложения](../README.md)
