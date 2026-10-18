#!/usr/bin/env bash
#
# Builds the CUSTOMER package: a locked, compiled image plus a small folder with an installer — no source code,
# no repository. This is what you send a customer who runs Cofferant on their own server.
#
#   make release VERSION=1.0.0 LICENSE_SERVER_URL=https://cofferant.ir
#   -> dist/release/cofferant-customer-1.0.0.tar.gz
#
# Options (environment variables)
#   VERSION             required, e.g. 1.0.0
#   LICENSE_SERVER_URL  required, your platform address; it is BAKED INTO the image (the customer cannot change it)
#   PLATFORM            target CPU architecture, default linux/amd64 (linux/arm64 for ARM servers)
#
# NOTE: this tags the image cofferant-app:<VERSION> and cofferant-app:latest on THIS machine too;
# run `make up` afterwards if you want your development image back.
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${VERSION:-}"
LICENSE_SERVER_URL="${LICENSE_SERVER_URL:-}"
[[ -n "$VERSION" ]] || { echo "VERSION is required, e.g. make release VERSION=1.0.0 LICENSE_SERVER_URL=https://cofferant.ir" >&2; exit 1; }
[[ -n "$LICENSE_SERVER_URL" ]] || { echo "LICENSE_SERVER_URL is required (your platform address)" >&2; exit 1; }
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "VERSION may only contain letters, digits, dots, dashes and underscores" >&2; exit 1; }
LICENSE_SERVER_URL="${LICENSE_SERVER_URL%/}"
PLATFORM="${PLATFORM:-linux/amd64}"
DOCKER="${DOCKER:-docker}"

OUT="dist/release"
PKG="cofferant-customer-${VERSION}"
IMAGE="cofferant-app:${VERSION}"
rm -rf "${OUT:?}/${PKG}" "${OUT:?}/${PKG}.tar.gz"
mkdir -p "$OUT/$PKG"

echo "==> Building the locked release image ${IMAGE} (${PLATFORM})"
DOCKER_DEFAULT_PLATFORM="$PLATFORM" "$DOCKER" build -f Dockerfile.release \
  --build-arg "LICENSE_SERVER_URL=${LICENSE_SERVER_URL}" --build-arg "VERSION=${VERSION}" \
  -t "$IMAGE" -t "cofferant-app:latest" .

echo "==> Verifying the image"
want="${PLATFORM##*/}"
got="$("$DOCKER" image inspect "$IMAGE" --format '{{.Architecture}}')"
[[ "$got" == "$want" ]] || { echo "Image is ${got}, expected ${want}." >&2; exit 1; }
echo "    architecture: $got"

leftover="$("$DOCKER" run --rm --entrypoint sh "$IMAGE" -c "find /app -name '*.py' ! -name manage.py | head -5")"
if [[ -n "$leftover" ]]; then
  echo "Python source files are still inside the image:" >&2; echo "$leftover" >&2; exit 1
fi
echo "    no Python source files inside"

baked="$("$DOCKER" run --rm --entrypoint python "$IMAGE" -c 'from config import edition; print(edition.EDITION, edition.LOCKED_LICENSE_SERVER_URL)')"
[[ "$baked" == "standalone ${LICENSE_SERVER_URL}" ]] || { echo "Edition lock missing: got '$baked'" >&2; exit 1; }
echo "    edition lock: ${baked}"

echo "==> Saving the image"
"$DOCKER" save "$IMAGE" "cofferant-app:latest" | gzip -1 > "$OUT/$PKG/cofferant-images.tar.gz"

echo "==> Assembling the package"
mkdir -p "$OUT/$PKG/scripts" "$OUT/$PKG/deploy/nginx"
# compose without the build section (the customer has no source to build from)
sed '/^    build: \.$/d' docker-compose.yml > "$OUT/$PKG/docker-compose.yml"
# Makefile: no building, and "update" installs a new image file instead of using git
awk 'BEGIN{skip=0} /^update:/{skip=1; next} skip && /^$/ {skip=0} !skip{print}' Makefile \
  | sed 's/up -d --build/up -d --no-build/' > "$OUT/$PKG/Makefile"
cat >> "$OUT/$PKG/Makefile" <<'EOF'

update: ## Install a new version: make update FILE=/path/to/cofferant-images.tar.gz
	@test -n "$(FILE)" || { echo "FILE is required: make update FILE=/path/to/cofferant-images.tar.gz"; exit 1; }
	@$(MAKE) backup
	@bash scripts/load-images.sh "$(FILE)"
	$(COMPOSE) up -d --no-build
EOF
cp .env.example "$OUT/$PKG/.env.example"
cp deploy/nginx/app.conf.template "$OUT/$PKG/deploy/nginx/"
for f in scripts/*.sh; do
  case "$(basename "$f")" in
    build-release.sh|build-images.sh|deploy-check.sh|demo-data.sh) continue ;;
  esac
  cp "$f" "$OUT/$PKG/scripts/"
done
sed "s|@LICENSE_SERVER_URL@|${LICENSE_SERVER_URL}|" packaging/install.sh.template > "$OUT/$PKG/install.sh"
cp packaging/README-CUSTOMER.txt "$OUT/$PKG/README.txt"
# Unix line endings everywhere (a Windows working copy has CRLF, which breaks scripts on Linux)
find "$OUT/$PKG" -type f \( -name '*.sh' -o -name 'Makefile' -o -name '*.yml' -o -name '*.template' -o -name '.env.example' -o -name '*.txt' \) \
  -exec sed -i 's/\r$//' {} +
chmod +x "$OUT/$PKG/install.sh" "$OUT/$PKG"/scripts/*.sh

echo "==> Packing"
tar -czf "$OUT/$PKG.tar.gz" -C "$OUT" "$PKG"

echo ""
echo "Package ready: $OUT/$PKG.tar.gz  ($(du -h "$OUT/$PKG.tar.gz" | cut -f1))"
echo ""
echo "Send the customer:"
echo "  1. $PKG.tar.gz            (no source code inside)"
echo "  2. their license key       (developer panel -> the customer -> mode 'install on the customer's domain')"
echo "They run:   tar xzf $PKG.tar.gz && cd $PKG && sudo ./install.sh"
echo "Updates:    send a new package; they run 'make update FILE=cofferant-images.tar.gz' from the new folder's file."
