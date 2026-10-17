#!/usr/bin/env bash
#
# Zero-to-deployed on a fresh Ubuntu/Debian VPS: installs Docker, writes .env
# with generated secrets, builds (or loads) the image, starts the app, then
# configures the host's nginx + a Let's Encrypt certificate.
#
# Runs happily next to OTHER projects on the same server: only this project's
# container is touched, and TLS reuses the host's single nginx/certbot (see
# scripts/deploy-host-nginx.sh) instead of fighting for port 443.
#
# Two ways to deploy:
#
#  A) YOUR OWN SaaS domain — every customer gets <slug>.yourdomain.com and you manage licenses
#     at https://yourdomain.com/developer/
#       MODE=platform DOMAIN=cofferant.ir LETSENCRYPT_EMAIL=me@example.com ./scripts/bootstrap-vps.sh
#     (needs a wildcard DNS record  *.cofferant.ir -> this server; wildcard TLS via CHALLENGE=cloudflare
#      with CF_API_TOKEN, or CHALLENGE=dns for a manual TXT record)
#
#  B) A CUSTOMER's own domain — the licence key comes from your developer panel
#       MODE=standalone DOMAIN=menu.mycafe.com LETSENCRYPT_EMAIL=owner@mycafe.com \
#       LICENSE_KEY=CFR-XXXX-XXXX-XXXX-XXXX LICENSE_SERVER_URL=https://cofferant.ir ./scripts/bootstrap-vps.sh
#
# Another project already uses 8081? Pick the local port yourself:
#   WEB_PORT=8082 ./scripts/bootstrap-vps.sh
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/lib.sh

if [[ "$(id -u)" != "0" ]]; then
  echo "==> Root access is required to install Docker; re-running with sudo"
  exec sudo -E bash "$0" "$@"
fi

REAL_USER="${SUDO_USER:-root}"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This script is written only for Ubuntu/Debian (apt)." >&2
  exit 1
fi

# --------------------------------------------------------- base packages
echo "==> Installing base packages"
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg make openssl git

# --------------------------------------------------------------- Docker Engine
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker Engine"
  install -m 0755 -d /etc/apt/keyrings
  # shellcheck disable=SC1091
  . /etc/os-release
  distro="${ID:-ubuntu}"; [[ "$distro" == "debian" ]] || distro="ubuntu"
  curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo "==> Docker is already installed"
fi

if [[ "$REAL_USER" != "root" ]] && ! id -nG "$REAL_USER" | grep -qw docker; then
  echo "==> Adding $REAL_USER to the docker group (log out/in to use docker without sudo)"
  usermod -aG docker "$REAL_USER"
fi

# --------------------------------------------------------------- mode, domain, email
if [[ -z "${MODE:-}" ]]; then
  echo ""
  echo "How will this server be used?"
  echo "  1) platform   — my own SaaS domain: customers get <name>.mydomain.com, I manage licenses"
  echo "  2) standalone — one cafe on its own domain (a customer's server, or a single cafe of mine)"
  read -r -p "Choose [1/2]: " m
  case "$m" in 1) MODE=platform ;; *) MODE=standalone ;; esac
fi
[[ "$MODE" == "platform" || "$MODE" == "standalone" ]] || { echo "MODE must be platform or standalone" >&2; exit 1; }

if [[ "$MODE" == "platform" ]]; then
  [[ -z "${DOMAIN:-}" ]] && read -r -p "Your root domain (A record AND wildcard *.domain -> this server): " DOMAIN
else
  [[ -z "${DOMAIN:-}" ]] && read -r -p "Domain whose A record points to this server: " DOMAIN
fi
[[ -z "${LETSENCRYPT_EMAIL:-}" ]] && read -r -p "Email for Let's Encrypt expiry warnings: " LETSENCRYPT_EMAIL
: "${DOMAIN:?DOMAIN is required}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL is required}"

if [[ "$MODE" == "standalone" && -z "${LICENSE_KEY:-}" && ! -f .env ]]; then
  echo ""
  echo "No LICENSE_KEY given. Without one the license check is OFF — fine for your own cafe,"
  echo "but a customer install should pass LICENSE_KEY and LICENSE_SERVER_URL from your developer panel."
fi

if [[ -z "${WEB_PORT:-}" ]]; then
  WEB_PORT="$(find_free_port 8081)"
  if [[ -d /etc/nginx || -x /usr/sbin/nginx ]]; then
    echo ""
    echo "nginx is already on this server (another project is probably deployed)."
    echo "Cofferant will listen privately on 127.0.0.1:${WEB_PORT} (auto-picked as free)."
    read -r -p "Local port for Cofferant [${WEB_PORT}]: " reply
    WEB_PORT="${reply:-$WEB_PORT}"
  fi
fi

# ------------------------------------------------------------------- .env
if [[ ! -f .env ]]; then
  echo "==> Creating .env with generated secrets"
  MODE="$MODE" DOMAIN="$DOMAIN" LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL" bash scripts/init-env.sh
  set_env_value .env WEB_BIND 127.0.0.1
  set_env_value .env WEB_PORT "$WEB_PORT"
  GENERATED_ENV=1
else
  echo "==> .env already exists — leaving it as is"
  load_env .env
fi

[[ "$REAL_USER" != "root" ]] && chown "$REAL_USER":"$REAL_USER" .env
chmod 600 .env
load_env .env

# --------------------------------------------------------------------- image
VERSION="${VERSION:-latest}"
if docker image inspect "cofferant-app:${VERSION}" >/dev/null 2>&1; then
  echo "==> Prebuilt image found; skipping the build"
  make up-prebuilt
else
  echo "==> Building the image (slow on a small server). If it runs out of memory, build on"
  echo "    your own machine instead: make images-bundle, scp it over, make load-images."
  make up
fi

# --------------------------------------------------------------- TLS + nginx
echo "==> Obtaining the SSL certificate and configuring host nginx"
make ssl

echo ""
echo "================================================================"
echo " Cofferant is live at https://${DOMAIN}   (mode: ${DEPLOYMENT_MODE:-$MODE})"
echo "================================================================"
echo "  Panel login:  https://${DOMAIN}/users/login/   (user: ${ADMIN_USERNAME:-admin})"
[[ "${GENERATED_ENV:-0}" == "1" ]] && echo "  Password:     ${ADMIN_PASSWORD}   (also stored in .env)"
if [[ "${DEPLOYMENT_MODE:-$MODE}" == "platform" ]]; then
  echo "  Developer panel (licenses, customers, revenue):  https://${DOMAIN}/developer/"
  echo "  Make sure DNS has a wildcard record:  *.${DOMAIN}  ->  this server"
fi
echo "  Health check: make deploy-health HOST=https://${DOMAIN}"
