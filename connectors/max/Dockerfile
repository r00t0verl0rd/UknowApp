FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY connectors/max/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /app/requirements.txt \
    && groupadd --system bot && useradd --system --gid bot --home-dir /app bot \
    && mkdir -p /app/state && chown bot:bot /app/state
COPY --chown=bot:bot connectors/__init__.py /app/connectors/__init__.py
COPY --chown=bot:bot connectors/common /app/connectors/common
COPY --chown=bot:bot connectors/max /app/connectors/max
USER bot
CMD ["python", "-m", "connectors.max"]
