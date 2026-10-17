#!/usr/bin/env bash
#
# Runs a Django management command against the right environment:
#   * the running production stack (docker compose app container), or
#   * the local development database via the project's virtualenv.
#
# Auto-detects by default; force with PROD=1 (container) or PROD=0 (local).
#
#   scripts/admin.sh createsuperuser
#   scripts/admin.sh migrate_tenants
#   PROD=1 scripts/admin.sh shell
set -euo pipefail
cd "$(dirname "$0")/.."

DOCKER="${DOCKER:-docker}"

use_prod="${PROD:-}"
if [[ -z "$use_prod" ]]; then
  if "$DOCKER" compose ps -q app 2>/dev/null | grep -q .; then use_prod=1; else use_prod=0; fi
fi

if [[ "$use_prod" == "1" ]]; then
  # -T only when there is no terminal, so interactive commands (shell, createsuperuser) still work.
  if [[ -t 0 ]]; then exec "$DOCKER" compose exec app python manage.py "$@"; fi
  exec "$DOCKER" compose exec -T app python manage.py "$@"
fi

PY=""
for c in .venv/Scripts/python.exe .venv/bin/python python3 python; do
  if [[ -x "$c" ]] || command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[[ -n "$PY" ]] || { echo "python is required for the local CLI (or run the stack and use PROD=1)." >&2; exit 1; }
exec "$PY" manage.py "$@"
