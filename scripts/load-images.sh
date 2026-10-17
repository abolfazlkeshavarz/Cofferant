#!/usr/bin/env bash
#
# Loads the bundle made by scripts/build-images.sh. Run this ON THE SERVER.
#
#   make load-images                       (looks in ./ and ./dist)
#   make load-images FILE=path/to/bundle.tar.gz
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION="${VERSION:-latest}"

BUNDLE="${1:-}"
if [[ -z "$BUNDLE" ]]; then
  for candidate in cofferant-images.tar.gz dist/cofferant-images.tar.gz; do
    [[ -f "$candidate" ]] && { BUNDLE="$candidate"; break; }
  done
fi

if [[ -z "$BUNDLE" || ! -f "$BUNDLE" ]]; then
  echo "Error: image bundle not found." >&2
  echo "Build it on your own machine (make images-bundle) and scp it here." >&2
  exit 1
fi

echo "==> Loading images from ${BUNDLE}"
gunzip -c "$BUNDLE" | docker load

host_arch="$(docker info --format '{{.Architecture}}' 2>/dev/null || uname -m)"
case "$host_arch" in x86_64|amd64) host_arch=amd64 ;; aarch64|arm64) host_arch=arm64 ;; esac

for img in "cofferant-app:${VERSION}"; do
  got="$(docker image inspect "$img" --format '{{.Architecture}}' 2>/dev/null || echo missing)"
  if [[ "$got" == "missing" ]]; then
    echo "Error: ${img} is not in the bundle (built with another VERSION? use VERSION=tag)." >&2
    exit 1
  fi
  if [[ "$got" != "$host_arch" ]]; then
    echo "Error: ${img} is ${got} but this server is ${host_arch}; rebuild with PLATFORM=linux/${host_arch}." >&2
    exit 1
  fi
  echo "    ${img}: ${got} — matches this server"
done

echo ""
echo "Image loaded. Start without building:  make up-prebuilt"
