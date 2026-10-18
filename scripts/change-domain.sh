#!/usr/bin/env bash
#
# Moves this installation to a NEW domain on the SAME server — one command instead of editing .env,
# nginx and certificates by hand.
#
#   make change-domain DOMAIN=newname.com
#   ./scripts/change-domain.sh newname.com [--drop-old]
#
# What it does
#   1. backs up .env, then rewrites the domain settings (allowed hosts, CSRF origins, platform domain)
#   2. keeps the OLD domain working (default): hosted customers' old addresses and the license-check
#      address of self-hosted installs don't break. Use --drop-old to stop serving the old domain.
#   3. restarts the app and gets a certificate + nginx entry for the new domain
#      (platform mode needs a wildcard certificate: CF_API_TOKEN in .env, or CHALLENGE=dns)
#
# Before you run it, point the new domain's DNS at this server (platform mode: the root AND *.newname.com).
# Customers' own domains (make add-domain) are not affected.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh

NEW="$(tr 'A-Z' 'a-z' <<<"${1:-}" | sed -E 's#^https?://##; s#/.*$##')"
DROP=0; [[ "${2:-}" == "--drop-old" ]] && DROP=1
[[ -n "$NEW" ]] || { echo "Usage: change-domain.sh <new-domain> [--drop-old]" >&2; exit 1; }
valid_hostname "$NEW" || { echo "'$NEW' is not a valid domain name." >&2; exit 1; }
[[ -f .env ]] || { echo ".env not found — is this the installation folder?" >&2; exit 1; }

load_env .env
MODE="${DEPLOYMENT_MODE:-standalone}"
OLD="${APP_DOMAIN:-}"
if [[ "$NEW" == "$OLD" ]]; then echo "Already using $NEW — nothing to do."; exit 0; fi

echo "Mode: $MODE   Old domain: ${OLD:-none}   New domain: $NEW"

# DNS sanity check (a warning only: the DNS change may still be propagating)
probe="$NEW"; [[ "$MODE" == "platform" ]] && probe="probe-$RANDOM.$NEW"
if ! getent hosts "$NEW" >/dev/null 2>&1 && ! host "$NEW" >/dev/null 2>&1; then
  echo "WARNING: $NEW has no DNS record yet — the certificate step will fail until it points here." >&2
fi
if [[ "$MODE" == "platform" ]] && ! getent hosts "$probe" >/dev/null 2>&1; then
  echo "WARNING: no wildcard DNS record for *.$NEW — customers' addresses won't resolve until you add one." >&2
fi

backup=".env.bak-$(date +%Y%m%d-%H%M%S)"
cp .env "$backup"
echo "==> Saved the previous settings to $backup"

apply_domain_env .env "$NEW" "$MODE" "$OLD" "$((1 - DROP))"
echo "==> Updated .env"

if [[ "${SKIP_TLS:-0}" == "1" ]]; then
  echo "SKIP_TLS=1: not restarting or touching nginx."
  exit 0
fi

echo "==> Restarting the app with the new settings"
"${DOCKER:-docker}" compose up -d

echo "==> Certificate and nginx for ${NEW}"
if ! bash scripts/deploy-host-nginx.sh; then
  echo "" >&2
  echo "The certificate step failed. Nothing is lost: ${OLD:-the old domain} keeps working." >&2
  echo "Fix DNS/credentials, then run:  make ssl   (previous settings are in $backup)" >&2
  exit 1
fi

echo ""
echo "================================================================"
echo " Now live at https://${NEW}"
echo "================================================================"
if [[ "$DROP" == "0" && -n "$OLD" ]]; then
  echo "  The old domain ($OLD) still works as an alias. When nobody uses it any more:"
  echo "     ./scripts/change-domain.sh $NEW --drop-old   then   make remove-domain DOMAIN=$OLD"
fi
[[ "$MODE" == "platform" ]] && echo "  Hosted customers are now at https://<name>.${NEW} — tell them. Self-hosted customers keep verifying against ${OLD:-the old address} until you update their LICENSE_SERVER_URL."
echo "  Check:  make deploy-health HOST=https://${NEW}"
