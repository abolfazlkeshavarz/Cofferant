#!/usr/bin/env bash
#
# Copies every automatic backup (every 12 h) to a SECOND server too, so losing this server loses nothing
# and a new server can be restored from the off-server copy.
#
#   make backup-remote-setup REMOTE=backupuser@backup.example.com:/backups/cofferant
#
# The remote side only needs SSH and a folder. This script
#   1. stores REMOTE in .env and restarts the services
#   2. creates an SSH key inside the app (kept in a Docker volume) and prints its public half
#   3. waits while you add that key to the backup server, then tests the connection and sends a first copy
# Restore later with:  ./scripts/migrate-import.sh <the copied cofferant-....tar.gz>
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh
DOCKER="${DOCKER:-docker}"

[[ -f .env ]] || { echo ".env not found — run this in the installation folder." >&2; exit 1; }
load_env .env
REMOTE="${1:-${BACKUP_REMOTE:-}}"
[[ "$REMOTE" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:/[A-Za-z0-9_./-]*$ ]] \
  || { echo "Usage: backup-remote-setup.sh user@host:/absolute/folder   (got: '${REMOTE}')" >&2; exit 1; }

set_env_value .env BACKUP_REMOTE "$REMOTE"
[[ -n "${PORT_SSH:-}" ]] && set_env_value .env BACKUP_REMOTE_PORT "$PORT_SSH"
load_env .env   # docker compose lets the environment override .env, so re-read the edited file first
echo "==> Saved BACKUP_REMOTE=$REMOTE; restarting the services"
"$DOCKER" compose up -d

echo "==> Preparing the SSH key"
"$DOCKER" compose exec -T app sh -c 'test -f "$HOME/.ssh/id_ed25519" || ssh-keygen -q -t ed25519 -N "" -C "cofferant-backup" -f "$HOME/.ssh/id_ed25519"'
pub="$("$DOCKER" compose exec -T app sh -c 'cat "$HOME/.ssh/id_ed25519.pub"' | tr -d '\r')"

host="${REMOTE%%:*}"
echo ""
echo "On the BACKUP server, add this line to  ~/.ssh/authorized_keys  of ${host%%@*}:"
echo ""
echo "  $pub"
echo ""
echo "  (one command on the backup server:  echo '$pub' >> ~/.ssh/authorized_keys )"
echo ""
if [[ "${YES:-0}" != "1" ]]; then
  read -r -p "Press Enter once the key is added to test the connection… " _
fi

echo "==> Testing the connection"
if ! "$DOCKER" compose exec -T app python manage.py backup_remote --test; then
  echo "The connection failed. Check the key, the user and the folder, then run this again." >&2
  exit 1
fi

echo "==> Sending the newest backup as a first copy"
"$DOCKER" compose exec -T app python manage.py backup_remote --push || echo "(no local backup yet — the next automatic one will be copied)"
echo ""
echo "Done. Every backup from now on is copied to ${REMOTE} automatically."
