#!/usr/bin/env bash
#
# Installs Docker Engine + the compose plugin on Ubuntu/Debian (does nothing if Docker is already there).
# Used by the customer package's install.sh before it loads the application image.
set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then exec sudo -E bash "$0" "$@"; fi
command -v apt-get >/dev/null 2>&1 || { echo "This installer supports Ubuntu/Debian (apt) only." >&2; exit 1; }

if command -v docker >/dev/null 2>&1; then
  echo "==> Docker is already installed"
  exit 0
fi

echo "==> Installing Docker Engine"
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg make openssl
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
echo "==> Docker installed"
