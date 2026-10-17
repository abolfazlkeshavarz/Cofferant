# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=0 \
    DATA_DIR=/app/data \
    DB_PATH=/app/data/db.sqlite3 \
    MEDIA_ROOT=/app/media

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd -m -u 10001 app \
    && mkdir -p /app/data /app/media /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh \
    && chown -R app:app /app/data /app/media /app/staticfiles
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
