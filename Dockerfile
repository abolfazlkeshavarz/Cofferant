# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=0 \
    DATA_DIR=/app/data \
    DB_PATH=/app/data/db.sqlite3 \
    MEDIA_ROOT=/app/media \
    BACKUP_DIR=/app/backups

WORKDIR /app

# ssh/scp: used to copy backups to a second server (BACKUP_REMOTE)
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd -m -u 10001 app \
    && mkdir -p /app/data /app/media /app/staticfiles /app/backups \
    && mkdir -p /home/app/.ssh && chmod 700 /home/app/.ssh && chown app:app /home/app/.ssh \
    && chmod +x /app/docker/entrypoint.sh \
    && chown -R app:app /app/data /app/media /app/staticfiles /app/backups
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
