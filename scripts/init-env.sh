#!/usr/bin/env bash
#
# Creates .env from .env.example with freshly generated secrets, so a new
# install never ships a placeholder password.
#
#   make env
#   DOMAIN=cafe.example.com LETSENCRYPT_EMAIL=me@example.com make env
#   MODE=platform DOMAIN=cofferant.ir LETSENCRYPT_EMAIL=me@example.com make env     # your own SaaS domain
#   MODE=standalone LICENSE_KEY=CFR-... LICENSE_SERVER_URL=https://cofferant.ir DOMAIN=menu.cafe.ir make env
#
# Never overwrites an existing .env (delete it yourself if you really want a new one).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh

if [[ -f .env ]]; then
  echo ".env already exists — leaving it untouched."
  exit 0
fi

cp .env.example .env

MODE="${MODE:-standalone}"
[[ "$MODE" == "standalone" || "$MODE" == "platform" ]] || { echo "MODE must be standalone or platform" >&2; exit 1; }
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(rand_secret 18)}"

set_env_value .env DJANGO_SECRET_KEY "$(rand_secret 48)"
set_env_value .env ADMIN_PASSWORD "$ADMIN_PASSWORD"
set_env_value .env DEPLOYMENT_MODE "$MODE"

if [[ -n "${DOMAIN:-}" ]]; then
  set_env_value .env APP_DOMAIN "$DOMAIN"
  set_env_value .env PLATFORM_DOMAIN "$DOMAIN"
  set_env_value .env DJANGO_ALLOWED_HOSTS "${DOMAIN},localhost,127.0.0.1"
  set_env_value .env DJANGO_CSRF_TRUSTED_ORIGINS "https://${DOMAIN}"
fi
[[ -n "${LETSENCRYPT_EMAIL:-}" ]] && set_env_value .env LETSENCRYPT_EMAIL "$LETSENCRYPT_EMAIL"

# Self-hosted customer: enforce the license issued from the developer panel
if [[ -n "${LICENSE_KEY:-}" ]]; then
  set_env_value .env LICENSE_ENFORCE 1
  set_env_value .env LICENSE_KEY "$LICENSE_KEY"
  set_env_value .env LICENSE_SERVER_URL "${LICENSE_SERVER_URL:?LICENSE_SERVER_URL is required with LICENSE_KEY}"
fi
[[ -n "${SALES_CONTACT:-}" ]] && set_env_value .env SALES_CONTACT "$SALES_CONTACT"

chmod 600 .env 2>/dev/null || true

echo "Created .env with generated secrets (mode: ${MODE})."
echo "  Admin login:  ${ADMIN_USERNAME:-admin} / ${ADMIN_PASSWORD}"
if [[ "$MODE" == "platform" ]]; then
  echo "  This account is also your developer account for /developer/."
fi
