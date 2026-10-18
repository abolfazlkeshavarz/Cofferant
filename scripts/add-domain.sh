#!/usr/bin/env bash
#
# Lets a hosted customer use THEIR OWN domain (e.g. menu.mycafe.com) while their site still runs on
# your server: gets a free Let's Encrypt certificate for that domain and adds an nginx entry that
# forwards it to the app. Only that domain's own files are created; nothing else is touched.
#
# Before running it:
#   1. In the developer panel, open the customer and save the domain under "Custom domain".
#   2. The customer points the domain's DNS  A record  to THIS server's IP address.
#
#   make add-domain DOMAIN=menu.mycafe.com
#   ./scripts/add-domain.sh menu.mycafe.com [--www]     # --www also covers www.menu.mycafe.com
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(id -u)" != "0" ]]; then
  echo "==> Root access is required to configure nginx/certbot; re-running with sudo"
  exec sudo -E bash "$0" "$@"
fi

# shellcheck disable=SC1091
source scripts/lib.sh
load_env .env || exit 1

CUSTOM="${1:-}"
WITH_WWW=0; [[ "${2:-}" == "--www" ]] && WITH_WWW=1
[[ -n "$CUSTOM" ]] || { echo "Usage: add-domain.sh <domain> [--www]" >&2; exit 1; }
CUSTOM="$(tr 'A-Z' 'a-z' <<<"$CUSTOM" | sed -E 's#^https?://##; s#/.*$##')"
[[ "$CUSTOM" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { echo "'$CUSTOM' is not a valid domain name." >&2; exit 1; }

ROOT="${APP_DOMAIN:-${PLATFORM_DOMAIN:-}}"
if [[ -n "$ROOT" && ( "$CUSTOM" == "$ROOT" || "$CUSTOM" == *".$ROOT" ) ]]; then
  echo "$CUSTOM already belongs to the platform (covered by the wildcard certificate)." >&2
  exit 1
fi
: "${LETSENCRYPT_EMAIL:?Set LETSENCRYPT_EMAIL in .env}"
APP_HTTP_PORT="${WEB_PORT:-8081}"

SERVER_NAMES="$CUSTOM"
DOMAIN_ARGS=(-d "$CUSTOM")
if [[ "$WITH_WWW" == "1" ]]; then SERVER_NAMES="$CUSTOM www.$CUSTOM"; DOMAIN_ARGS+=(-d "www.$CUSTOM"); fi

VHOST_PATH="/etc/nginx/sites-available/${CUSTOM}.conf"
VHOST_LINK="/etc/nginx/sites-enabled/${CUSTOM}.conf"
CERT_PATH="/etc/letsencrypt/live/${CUSTOM}"
WEBROOT="/var/www/certbot"

echo "==> Installing nginx/certbot if needed (existing installs are left alone)"
apt-get update
apt-get install -y --no-install-recommends nginx certbot gettext-base
systemctl enable --now nginx
mkdir -p "$WEBROOT"

echo "==> Checking that ${CUSTOM} points to this server"
server_ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
domain_ip="$(getent hosts "${CUSTOM}" | awk '{print $1}' | head -1 || true)"
if [[ -z "$domain_ip" ]]; then
  echo "${CUSTOM} has no DNS record yet. Ask the customer to add an A record to ${server_ip:-the IP address of this server}, wait a few minutes, then run this again." >&2
  exit 1
fi
if [[ -n "$server_ip" && "$server_ip" != "$domain_ip" ]]; then
  echo "Warning: ${CUSTOM} resolves to ${domain_ip}, this server is ${server_ip}."
  read -r -p "Continue anyway? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || exit 1
fi

if [[ ! -d "$CERT_PATH" ]]; then
  echo "==> Writing a temporary HTTP-only entry for the certificate challenge"
  cat > "$VHOST_PATH" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};
    location ^~ /.well-known/acme-challenge/ { root ${WEBROOT}; default_type "text/plain"; }
    location / { proxy_pass http://127.0.0.1:${APP_HTTP_PORT}; proxy_set_header Host \$host; }
}
EOF
  ln -sf "$VHOST_PATH" "$VHOST_LINK"
  nginx -t && systemctl reload nginx

  echo "==> Requesting the certificate"
  certbot certonly --webroot -w "$WEBROOT" \
    --email "${LETSENCRYPT_EMAIL}" "${DOMAIN_ARGS[@]}" \
    --agree-tos --no-eff-email --non-interactive
else
  echo "==> A certificate for ${CUSTOM} already exists — re-writing the nginx entry only"
fi

echo "==> Writing the HTTPS entry from deploy/nginx/app.conf.template"
SERVER_NAMES="$SERVER_NAMES" CERT_NAME="$CUSTOM" APP_HTTP_PORT="$APP_HTTP_PORT" \
  envsubst '${SERVER_NAMES} ${CERT_NAME} ${APP_HTTP_PORT}' < deploy/nginx/app.conf.template > "$VHOST_PATH"
ln -sf "$VHOST_PATH" "$VHOST_LINK"
nginx -t
systemctl reload nginx

echo ""
echo "Done: https://${CUSTOM} now reaches the customer's site on this server."
echo "Make sure the domain is saved on the customer's page in the developer panel — the app only answers domains registered there."
echo "The certificate renews automatically."
