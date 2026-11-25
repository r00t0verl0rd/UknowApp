# Intentionally not a runnable integration. Add MAX provider implementation first.
FROM python:3.11-slim
WORKDIR /app
COPY connectors/max/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY connectors /app/connectors
CMD ["python", "-c", "raise SystemExit('MAX connector is not implemented; configure and test provider first')"]
