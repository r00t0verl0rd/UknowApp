FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /app/backend/requirements.txt

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data \
    && chown app:app /app /app/data

COPY --chown=app:app backend /app/backend
COPY --chown=app:app alembic.ini /app/alembic.ini

USER app

EXPOSE 8000

# Доверяем прокси-заголовкам только от Caddy.
# Один worker: единый реестр коннекторов, SSE и очередь доставки.
# В legacy-режиме также сохраняется один процесс Telegram polling.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--ws-max-size", "1048576", "--timeout-graceful-shutdown", "20", "--proxy-headers", "--forwarded-allow-ips", "172.31.255.2"]
