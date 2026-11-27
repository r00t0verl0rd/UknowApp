FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    FORWARDED_ALLOW_IPS=172.31.255.2

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /app/backend/requirements.txt

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data \
    && chown app:app /app /app/data

COPY --chown=app:app backend/app /app/backend/app

USER app

EXPOSE 8000

# Доверяем прокси-заголовкам только от Caddy.
# Один worker: единый реестр коннекторов, SSE и очередь доставки.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "20", "--proxy-headers"]
