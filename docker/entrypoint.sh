#!/usr/bin/env bash
# Container start-up: prepare the database, then hand over to gunicorn.
set -euo pipefail

echo "==> Applying migrations"
python manage.py migrate --noinput

if [[ "${DEPLOYMENT_MODE:-standalone}" == "platform" ]]; then
  echo "==> Migrating hosted customers' databases"
  python manage.py migrate_tenants
fi

echo "==> Collecting static files"
python manage.py collectstatic --noinput >/dev/null

python manage.py ensure_admin

# SQLite + several workers is fine with WAL; threads keep memory low on small servers.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${WEB_WORKERS:-2}" \
  --threads "${WEB_THREADS:-4}" \
  --timeout 60 \
  --access-logfile - \
  --forwarded-allow-ips="*"
