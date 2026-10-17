#!/bin/sh
# Restore a backup into the running data volumes. Used by `make restore` / `make restore-latest`.
#
#   restore.sh            archive is read from stdin
#   restore.sh latest     newest archive in the server's backup folder
#
# The archive is fully extracted and checked BEFORE anything is deleted, so a broken or wrong
# file can never destroy the current data.
set -eu

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ "${1:-}" = "latest" ]; then
  src="$(ls -t "${BACKUP_DIR:-/app/backups}"/cofferant-*.tar.gz 2>/dev/null | head -1 || true)"
  [ -n "$src" ] || { echo "No backups found in ${BACKUP_DIR:-/app/backups}" >&2; exit 1; }
  echo "Restoring $src"
  tar -C "$WORK" -xzf "$src"
else
  tar -C "$WORK" -xzf -
fi

[ -d "$WORK/data" ] || { echo "This archive has no data/ folder - not a Cofferant backup." >&2; exit 1; }

rm -rf /app/data/tenants /app/data/cache
rm -f /app/data/*.sqlite3 /app/data/*.sqlite3-wal /app/data/*.sqlite3-shm
cp -a "$WORK/data/." /app/data/
if [ -d "$WORK/media" ]; then
  rm -rf /app/media/*
  cp -a "$WORK/media/." /app/media/
fi
echo "Restore complete."
