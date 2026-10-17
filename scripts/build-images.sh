#!/usr/bin/env bash
#
# Builds the application image HERE, on your own machine, and packs it into one
# tarball to carry to the server — so a small VPS (1 core / 1 GB) never has to run
# pip install / the build, which is slow at best and OOM-killed at worst.
#
#   make images-bundle
#
# Options (environment variables):
#   PLATFORM=linux/arm64     target architecture if the server is not x86-64
#   VERSION=1.2.0            image tag (default: latest)
#   OUT=path/to/file.tar.gz  where to write the bundle
set -euo pipefail

cd "$(dirname "$0")/.."

PLATFORM="${PLATFORM:-linux/amd64}"
VERSION="${VERSION:-latest}"
OUT="${OUT:-dist/cofferant-images.tar.gz}"
IMAGES=("cofferant-app:${VERSION}")

echo "==> Building the image for ${PLATFORM}"
DOCKER_DEFAULT_PLATFORM="$PLATFORM" docker build -t "cofferant-app:${VERSION}" .

echo ""
echo "==> Verifying the image really is ${PLATFORM}"
# A wrong architecture loads fine and then dies at start with "exec format error".
want="${PLATFORM##*/}"
for img in "${IMAGES[@]}"; do
  got="$(docker image inspect "$img" --format '{{.Architecture}}')"
  if [[ "$got" != "$want" ]]; then
    echo "Error: ${img} is ${got}, expected ${want}. Check your Docker buildx setup." >&2
    exit 1
  fi
  echo "    ${img}: ${got}"
done

echo ""
echo "==> Packing into ${OUT}"
mkdir -p "$(dirname "$OUT")"
docker save "${IMAGES[@]}" | gzip -1 > "$OUT"

echo ""
echo "Built $(du -h "$OUT" | cut -f1) -> ${OUT}"
echo ""
echo "Next:"
echo "  scp ${OUT} USER@SERVER:/opt/cofferant/"
echo "  ssh USER@SERVER 'cd /opt/cofferant && make load-images && make up-prebuilt'"
