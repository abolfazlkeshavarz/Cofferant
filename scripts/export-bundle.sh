#!/usr/bin/env bash
#
# Packs EVERYTHING needed to move to a new server into one file: a fresh backup of all databases, customers
# and photos, plus this installation's settings (.env) and the list of customers' own domains.
#
#   make export
#   ./scripts/export-bundle.sh [output-file]
#
# The bundle contains secrets (.env) — treat it like a password and delete it after the move.
# On the NEW server:   ./scripts/migrate-import.sh cofferant-migration-....tar.gz
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh

DOCKER="${DOCKER:-docker}"
[[ -f .env ]] || { echo ".env not found — run this in the installation folder." >&2; exit 1; }
load_env .env
"$DOCKER" compose ps -q app | grep -q . || { echo "The app is not running (make up first)." >&2; exit 1; }

TS="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-dist/cofferant-migration-${TS}.tar.gz}"
mkdir -p "$(dirname "$OUT")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Taking a fresh backup (all databases, customers, photos)"
name="$("$DOCKER" compose exec -T app python manage.py backup | tail -1 | awk '{print $1}' | sed 's|.*/||')"
[[ "$name" == cofferant-*.tar.gz ]] || { echo "Backup failed." >&2; exit 1; }
"$DOCKER" compose exec -T app sh -c "cat backups/$name" > "$WORK/backup.tar.gz"
[[ -s "$WORK/backup.tar.gz" ]] || { echo "Could not copy the backup out of the container." >&2; exit 1; }

echo "==> Adding settings and the list of customers' own domains"
cp .env "$WORK/env"
custom_domains > "$WORK/domains.txt"
{
  echo "created: $(date -Iseconds)"
  echo "mode: ${DEPLOYMENT_MODE:-standalone}"
  echo "domain: ${APP_DOMAIN:-}"
  echo "version: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "custom_domains: $(wc -l < "$WORK/domains.txt" | tr -d ' ')"
} > "$WORK/manifest.txt"

tar -czf "$OUT" -C "$WORK" backup.tar.gz env domains.txt manifest.txt
chmod 600 "$OUT"

echo ""
echo "Bundle ready: $OUT  ($(du -h "$OUT" | cut -f1))"
cat "$WORK/manifest.txt" | sed 's/^/  /'
echo ""
echo "Next:"
echo "  1. Copy it to the new server:   scp $OUT USER@NEW_SERVER:/opt/cofferant/"
echo "  2. On the new server (fresh Ubuntu/Debian):"
echo "       git clone <repo> /opt/cofferant && cd /opt/cofferant"
echo "       ./scripts/migrate-import.sh $(basename "$OUT")            # add  --domain NEW.com  if the domain changes"
echo "  3. Switch DNS to the new server once it answers, then delete the bundle (it holds secrets)."
