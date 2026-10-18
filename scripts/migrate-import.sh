#!/usr/bin/env bash
#
# Sets up a NEW server from a migration bundle (make export on the old server) or from a plain backup
# archive (the automatic backups / the off-server copy), restoring all data: databases, every hosted
# customer and photos.
#
#   git clone <repo> /opt/cofferant && cd /opt/cofferant
#   ./scripts/migrate-import.sh cofferant-migration-20261018-101500.tar.gz
#   ./scripts/migrate-import.sh bundle.tar.gz --domain newname.com        # the domain changes too
#   ./scripts/migrate-import.sh bundle.tar.gz --no-ssl                    # DNS not switched yet: no certificate now
#
# From a plain backup archive there is no .env, so tell it what to create:
#   MODE=platform DOMAIN=cofferant.ir LETSENCRYPT_EMAIL=me@example.com ./scripts/migrate-import.sh cofferant-2026....tar.gz
#
# Docker is already installed and you only want the data restored (no nginx/TLS changes)?  add  --skip-install
#
# Safe order for a zero-downtime move: run this with --no-ssl (or a Cloudflare token), test the new
# server, then switch DNS and run `make ssl` (and `make add-domain` for customers' own domains).
set -euo pipefail

cd "$(dirname "$0")/.."

ORIG_ARGS=("$@")   # kept for the sudo re-run below (the parser consumes "$@")
FILE=""; NEW_DOMAIN=""; NO_SSL=0; DROP_OLD=0; SKIP_INSTALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) NEW_DOMAIN="$(tr 'A-Z' 'a-z' <<<"${2:?--domain needs a value}")"; shift 2 ;;
    --no-ssl) NO_SSL=1; shift ;;
    --drop-old) DROP_OLD=1; shift ;;
    --skip-install) SKIP_INSTALL=1; NO_SSL=1; shift ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) FILE="$1"; shift ;;
  esac
done
[[ -n "$FILE" && -f "$FILE" ]] || { echo "Usage: migrate-import.sh <bundle-or-backup.tar.gz> [--domain NEW] [--no-ssl]" >&2; exit 1; }
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"

if [[ "$SKIP_INSTALL" == "0" && "$(id -u)" != "0" ]]; then
  echo "==> Root access is required; re-running with sudo"
  exec sudo -E bash "$0" "${ORIG_ARGS[@]}"
fi

# shellcheck disable=SC1091
source scripts/lib.sh
DOCKER="${DOCKER:-docker}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ------------------------------------------------------------ what did we get?
# read the listing first: `tar | grep -q` can fail under pipefail (grep exits early, tar gets SIGPIPE)
LISTING="$(tar -tzf "$FILE" 2>/dev/null || true)"
if grep -qx 'backup.tar.gz' <<<"$LISTING"; then
  echo "==> Migration bundle detected"
  tar -xzf "$FILE" -C "$WORK"
  DATA="$WORK/backup.tar.gz"
  ENV_SRC="$WORK/env"
  [[ -f "$WORK/manifest.txt" ]] && sed 's/^/    /' "$WORK/manifest.txt"
elif grep -q '^data/' <<<"$LISTING"; then
  echo "==> Plain backup archive detected"
  DATA="$FILE"
  ENV_SRC=""
else
  echo "'$FILE' is neither a migration bundle nor a Cofferant backup." >&2
  exit 1
fi

# ------------------------------------------------------------ settings (.env)
if [[ -f .env ]]; then
  echo "==> .env already exists here — keeping it"
elif [[ -n "$ENV_SRC" && -f "$ENV_SRC" ]]; then
  echo "==> Using the settings from the bundle"
  cp "$ENV_SRC" .env
  chmod 600 .env
else
  : "${MODE:?A plain backup has no settings: pass MODE=platform|standalone DOMAIN=… LETSENCRYPT_EMAIL=…}"
  : "${DOMAIN:?pass DOMAIN=…}"
  : "${LETSENCRYPT_EMAIL:?pass LETSENCRYPT_EMAIL=…}"
  echo "==> Creating new settings"
  MODE="$MODE" DOMAIN="$DOMAIN" LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL" bash scripts/init-env.sh
fi
load_env .env
MODE="${DEPLOYMENT_MODE:-standalone}"
OLD_DOMAIN="${APP_DOMAIN:-}"

if [[ -n "$NEW_DOMAIN" && "$NEW_DOMAIN" != "$OLD_DOMAIN" ]]; then
  valid_hostname "$NEW_DOMAIN" || { echo "'$NEW_DOMAIN' is not a valid domain." >&2; exit 1; }
  echo "==> Switching the domain: ${OLD_DOMAIN:-none} -> $NEW_DOMAIN"
  apply_domain_env .env "$NEW_DOMAIN" "$MODE" "$OLD_DOMAIN" "$((1 - DROP_OLD))"
  load_env .env
fi
: "${APP_DOMAIN:?APP_DOMAIN missing in .env}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL missing in .env}"

# ------------------------------------------------------------ install Docker, start the app (empty)
export MODE DOMAIN="$APP_DOMAIN" LETSENCRYPT_EMAIL SKIP_SSL="$NO_SSL"
export WEB_PORT="${WEB_PORT:-8081}"
if [[ "$SKIP_INSTALL" == "1" ]]; then
  echo "==> --skip-install: Docker is assumed to be installed; starting the application"
  "$DOCKER" compose up -d --build
else
  echo "==> Installing Docker and starting the application"
  bash scripts/bootstrap-vps.sh
fi

# ------------------------------------------------------------ restore the data
echo "==> Restoring the data"
"$DOCKER" compose stop app backup
"$DOCKER" compose run --rm --no-deps -T --entrypoint sh app docker/restore.sh < "$DATA"
"$DOCKER" compose up -d

echo "==> Waiting for the app"
for _ in $(seq 1 90); do
  st="$("$DOCKER" compose ps app --format '{{.Health}}' 2>/dev/null | head -1)"
  [[ "$st" == "healthy" ]] && break
  sleep 1
done
[[ "${st:-}" == "healthy" ]] || { echo "The app did not become healthy; check: make logs" >&2; exit 1; }

# ------------------------------------------------------------ customers' own domains
DOMAINS="$(custom_domains)"

pending=()
if [[ -n "$DOMAINS" ]]; then
  echo "==> Customers' own domains found in the data:"
  server_ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
  while IFS= read -r d; do
    [[ -n "$d" ]] || continue
    ip="$(getent hosts "$d" | awk '{print $1}' | head -1 || true)"
    if [[ "$NO_SSL" == "0" && -n "$server_ip" && "$ip" == "$server_ip" ]]; then
      echo "    $d already points here — issuing its certificate"
      bash scripts/add-domain.sh "$d" || pending+=("$d")
    else
      pending+=("$d")
    fi
  done <<<"$DOMAINS"
fi

echo ""
bash scripts/health.sh || true
echo ""
echo "================================================================"
echo " Migration finished: https://${APP_DOMAIN}"
echo "================================================================"
echo "  Panel login uses the same accounts as before."
if [[ "$NO_SSL" == "1" ]]; then
  echo "  HTTPS was skipped. Once DNS points to this server:  make ssl"
fi
if ((${#pending[@]})); then
  echo "  Customers' own domains still to enable (after their DNS points here):"
  for d in "${pending[@]}"; do echo "     make add-domain DOMAIN=$d"; done
fi
echo "  Then switch your DNS records to this server and check:  make deploy-health HOST=https://${APP_DOMAIN}"
echo "  Finally delete the migration bundle — it contains secrets."
