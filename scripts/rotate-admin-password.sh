#!/usr/bin/env bash
#
# Generates a new admin/developer password, stores it in .env and restarts the app
# so it takes effect (the start-up hook updates the account). Existing sessions stay
# valid until they expire.
#
#   make admin-password                     random password
#   make admin-password PASSWORD='...'      choose your own (>= 12 chars)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh

[[ -f .env ]] || { echo ".env not found — run: make env" >&2; exit 1; }

new="${PASSWORD:-$(rand_secret 18)}"
if [[ ${#new} -lt 12 ]]; then
  echo "The password must be at least 12 characters." >&2
  exit 1
fi

set_env_value .env ADMIN_PASSWORD "$new"
load_env .env

echo "==> Restarting the app with the new password"
"${DOCKER:-docker}" compose up -d app >/dev/null

echo ""
echo "Login:  ${ADMIN_USERNAME:-admin} / ${new}"
echo "(stored in .env — keep that file private)"
