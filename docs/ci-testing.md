# Проверки и тесты UknowApp

Аудит на 23 ноября 2026 года, по текущему коду `main`.

## Что выполняется

| Задача | Покрытие | Почему оставлена |
| --- | --- | --- |
| Frontend build и SCSS architecture | Сборка Vite/Solid, целостность SCSS-модулей | Проверяет реальные компоненты и стили |
| Frontend unit (`npm test`) | Сообщения, прочтения, realtime/SSE, даты, CSP, первый рендер, PWA-иконки | Все 7 существующих unit/contract-файлов включены в npm-script |
| Browser (`npm run test:browser`) | Аутентификация/доступ к рабочему пространству, UI диалогов, realtime, push-обновления | Оба текущих browser-файла (включая подробный интеграционный сценарий) |
| CSS lint / audit | Правила общего SCSS и кандидаты на неиспользуемые селекторы | Позволяет менять дизайн без обязательной идентичности прошлому CSS |
| Backend lint, security | Ruff (включая BLE001, SIM115, B008), Vulture, Bandit, detect-secrets | Сохранены проверки безопасности и качества |
| Backend pytest | Права доступа, авторизация, сообщения, SSE, Telegram, push, прежние доски | Выполняет оставшиеся backend-тесты, без повторного запуска backup-тестов |
| backup-function | Создание полного ZIP и контрольных сумм, вложения обычных и личных сообщений, восстановление, статус, откат при ошибках | Запускает существующие API/pytest-тесты напрямую, без Docker Compose и браузера |
| PWA icon workflow | Перегенерация PNG при изменении исходной иконки/скрипта | Отдельный workflow, запускается только для подходящих файлов |

Тест `backend/tests/test_board_removal.py` не устарел: он проверяет, что удалённые API и таблицы досок не появились снова. Тесты backup/restore и прав доступа сохранены, но разделены между независимыми задачами, чтобы не запускать одни и те же тесты дважды.

## Что ускорено

- В GitHub Actions `ubuntu-24.04` используется уже установленный `/usr/bin/google-chrome`, без повторного `playwright install --with-deps chromium`. Оставшиеся браузерные тесты поддерживают `CHROMIUM_PATH`.
- Сохранён Playwright как библиотека автоматизации, без загрузки отдельного Chromium и apt-зависимостей при каждом прогоне.
- Проверки Ruff объединены в один проход с `--extend-select`, без отключения дополнительных правил.
- Удалён второй самостоятельный импорт `app.main` в CI: его выполняют существующие pytest-тесты.
- Проверка абсолютной идентичности CSS удалена полностью. При изменении дизайна CI проверяет сборку, SCSS-архитектуру, Stylelint и аудит селекторов, но не сравнивает CSS с предыдущим коммитом.
- Новый push/PR в той же ветке отменяет устаревший прогон, но не прерывает проверки других веток.

## Замеры до изменения

Первоначальный успешный запуск `Project checks` для коммита `ec1484f`: frontend — 226 с (из них установка Chromium — 193 с), migration — 141 с (установка браузера — 46 с), backend — 50 с. С тех пор тест переноса через Compose заменён на `backup-function`. Для нового job время измеряется отдельным запуском; старое значение migration больше не сравнимо напрямую.

## Запуск локально

```bash
cd frontend
npm ci
npm test
npm run build
npm install --no-save playwright@1.56.1
npm run test:browser # нужен установленный браузер Playwright или CHROMIUM_PATH
```

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install ruff vulture bandit detect-secrets pytest httpx
ruff check app --extend-select BLE001,SIM115,B008
python -m pytest -q tests
```

В CI `backup-function` запускает `python -m pytest -q tests/test_admin_data_backup.py tests/test_restore_startup.py`. Прежний Compose/browser-тест переноса удалён: он проверял резервную копию ценой сборки двух копий приложения. Остальные backend-тесты запускаются в `backend` с исключением указанных двух файлов. Все операции выполняются с изолированными тестовыми данными — действующая база школы не затрагивается.
