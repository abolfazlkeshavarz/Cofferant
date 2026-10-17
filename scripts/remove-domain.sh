#!/usr/bin/env bash
#
# Stops serving a customer's own domain from this server: removes its nginx entry and, after
# confirmation, its certificate. Remove the domain from the customer's page in the developer
# panel as well (the customer's sub-domain keeps working).
#
#   make remove-domain DOMAIN=menu.mycafe.com
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(id -u)" != "0" ]]; then
  echo "==> Root access is required; re-running with sudo"
  exec sudo -E bash "$0" "$@"
fi

CUSTOM="$(tr 'A-Z' 'a-z' <<<"${1:-}")"
[[ "$CUSTOM" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { echo "Usage: remove-domain.sh <domain>" >&2; exit 1; }

# shellcheck disable=SC1091
source scripts/lib.sh
load_env .env 2>/dev/null || true
ROOT="${APP_DOMAIN:-${PLATFORM_DOMAIN:-}}"
if [[ -n "$ROOT" && ( "$CUSTOM" == "$ROOT" || "$CUSTOM" == *".$ROOT" ) ]]; then
  echo "Refusing: $CUSTOM is the platform's own domain." >&2
  exit 1
fi

if [[ -e "/etc/nginx/sites-enabled/${CUSTOM}.conf" || -e "/etc/nginx/sites-available/${CUSTOM}.conf" ]]; then
  rm -f "/etc/nginx/sites-enabled/${CUSTOM}.conf" "/etc/nginx/sites-available/${CUSTOM}.conf"
  nginx -t && systemctl reload nginx
  echo "Removed the nginx entry for ${CUSTOM}."
else
  echo "No nginx entry found for ${CUSTOM}."
fi

if [[ -d "/etc/letsencrypt/live/${CUSTOM}" ]]; then
  read -r -p "Also delete the certificate for ${CUSTOM}? [y/N] " reply
  if [[ "$reply" =~ ^[Yy]$ ]]; then certbot delete --cert-name "${CUSTOM}" --non-interactive; fi
fi
echo "Done."
