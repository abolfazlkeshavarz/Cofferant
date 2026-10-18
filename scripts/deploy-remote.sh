#!/usr/bin/env bash
#
# Deploy the PLATFORM to your server by building the image HERE (on your PC) and pushing it over SSH.
# The server never builds anything and does not need the repository (no git, no source checkout).
#
#   make deploy-remote HOST=root@your-server                      # build, upload, backup, switch, health-check
#   make deploy-remote HOST=root@your-server DIR=/opt/cofferant   # a different folder on the server
#   make rollback-remote HOST=root@your-server                    # go back to the previous version
#
# Options (environment variables)
#   HOST        required: user@server (SSH key login recommended)
#   DIR         folder on the server (default /opt/cofferant)
#   PLATFORM    server CPU architecture: linux/amd64 (default) or linux/arm64
#   SSH_PORT    default 22          SSH_KEY   path to a private key (optional)
#   SKIP_BUILD  1 = reuse the image already built on this PC
#
# First deployment on a brand-new server: the same command uploads everything, installs Docker, and then tells
# you the one command to finish (or runs it for you if you pass MODE=platform DOMAIN=... LETSENCRYPT_EMAIL=...).
#
# What it does on the server, in order: back up (if the app is running) -> keep the old image as "previous"
# -> load the new image -> restart -> wait until healthy. A failed health check tells you how to roll back.
# Your .env, databases, photos and backups are never touched.
set -euo pipefail

cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1   # Git Bash on Windows must not rewrite /opt/... arguments

HOST="${HOST:-}"
DIR="${DIR:-/opt/cofferant}"
PLATFORM="${PLATFORM:-linux/amd64}"
SSH_PORT="${SSH_PORT:-22}"
DOCKER="${DOCKER:-docker}"
ROLLBACK=0; [[ "${1:-}" == "--rollback" ]] && ROLLBACK=1

[[ -n "$HOST" ]] || { echo "HOST is required, e.g.  make deploy-remote HOST=root@203.0.113.10" >&2; exit 1; }
[[ "$HOST" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+$ ]] || { echo "HOST must look like user@server" >&2; exit 1; }
[[ "$DIR" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "DIR must be an absolute path such as /opt/cofferant" >&2; exit 1; }
command -v ssh >/dev/null 2>&1 || { echo "ssh is required on this machine." >&2; exit 1; }

SSH_ARGS=(-p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
[[ -n "${SSH_KEY:-}" ]] && SSH_ARGS+=(-i "$SSH_KEY")
remote() { ssh "${SSH_ARGS[@]}" "$HOST" "$@"; }

echo "==> Checking the SSH connection to ${HOST}"
remote "echo connected" >/dev/null 2>&1 || {
  echo "Cannot log in to ${HOST} with a key. Set up key login first:  ssh-copy-id ${HOST}   (or pass SSH_KEY=path)" >&2
  exit 1
}

# ------------------------------------------------------------------------------------------ rollback
if [[ "$ROLLBACK" == "1" ]]; then
  echo "==> Rolling back to the previous image on ${HOST}"
  remote "bash -s" -- "$DIR" <<'REMOTE'
set -euo pipefail
cd "$1"
docker image inspect cofferant-app:previous >/dev/null 2>&1 || { echo "There is no previous version to go back to." >&2; exit 1; }
docker tag cofferant-app:latest cofferant-app:rolled-back-from 2>/dev/null || true
docker tag cofferant-app:previous cofferant-app:latest
docker compose up -d --no-build --force-recreate app backup </dev/null
for _ in $(seq 1 90); do
  [ "$(docker compose ps app --format '{{.Health}}' 2>/dev/null | head -1)" = "healthy" ] && { echo "app is healthy on the previous version"; exit 0; }
  sleep 1
done
echo "The app did not become healthy; check: docker compose logs --tail=50 app" >&2; exit 1
REMOTE
  echo "Done. Database changes are forward-only: if the newer version changed data, restore a backup (make restore-latest on the server)."
  exit 0
fi

# ------------------------------------------------------------------------------------------ build locally
REV="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"
DIRTY=""; [[ -n "$(git status --porcelain 2>/dev/null)" ]] && DIRTY="-dirty"
TAG="${REV}${DIRTY}"
OUT="dist/deploy"; TAR="cofferant-app-${TAG}.tar.gz"
mkdir -p "$OUT"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  [[ -z "$DIRTY" ]] || echo "NOTE: you have uncommitted changes; they are included in this build (version tag: ${TAG})."
  echo "==> Building the image on this machine (${PLATFORM}), version ${TAG}"
  DOCKER_DEFAULT_PLATFORM="$PLATFORM" "$DOCKER" build -t "cofferant-app:${TAG}" -t "cofferant-app:latest" .
  got="$("$DOCKER" image inspect "cofferant-app:latest" --format '{{.Architecture}}')"
  [[ "$got" == "${PLATFORM##*/}" ]] || { echo "Image architecture is ${got}, expected ${PLATFORM##*/}." >&2; exit 1; }
  echo "==> Packing the image"
  "$DOCKER" save "cofferant-app:${TAG}" "cofferant-app:latest" | gzip -1 > "$OUT/$TAR"
fi
[[ -s "$OUT/$TAR" ]] || { echo "No image file at $OUT/$TAR (build first, or unset SKIP_BUILD)." >&2; exit 1; }
echo "    $(du -h "$OUT/$TAR" | cut -f1)  $OUT/$TAR"

# ------------------------------------------------------------------------------------------ upload
echo "==> Uploading to ${HOST}:${DIR}"
remote "mkdir -p '$DIR/incoming'"
# small support files (compose, Makefile, scripts) - never .env, data, media or backups
tar -czf - docker-compose.yml Makefile .env.example scripts deploy | remote "cd '$DIR' && tar xzf -"
remote "cat > '$DIR/incoming/$TAR.part'" < "$OUT/$TAR"
LOCAL_SUM="$( (sha256sum "$OUT/$TAR" 2>/dev/null || shasum -a 256 "$OUT/$TAR") | cut -d' ' -f1)"
REMOTE_SUM="$(remote "sha256sum '$DIR/incoming/$TAR.part'" | cut -d' ' -f1)"
[[ "$LOCAL_SUM" == "$REMOTE_SUM" ]] || { echo "The uploaded file is damaged (checksum differs). Try again." >&2; exit 1; }
remote "mv '$DIR/incoming/$TAR.part' '$DIR/incoming/$TAR'"
echo "    checksum verified"

# ------------------------------------------------------------------------------------------ switch over
echo "==> Installing on the server"
STATUS="$(remote "bash -s" -- "$DIR" "$TAR" <<'REMOTE'
set -euo pipefail
cd "$1"; TAR="$2"
if ! command -v docker >/dev/null 2>&1; then
  echo "[server] installing Docker" >&2
  bash scripts/install-docker.sh >&2
fi

# NOTE: every docker command below gets </dev/null: this script itself arrives on stdin, and a command that
# reads stdin (docker compose exec does) would swallow the rest of it and the script would end silently.
if [ -f .env ] && [ -n "$(docker compose ps -q app 2>/dev/null </dev/null | head -1)" ]; then
  echo "[server] backing up before the switch" >&2
  docker compose exec -T app python manage.py backup >&2 </dev/null || { echo "[server] BACKUP FAILED - not switching" >&2; echo "BACKUP_FAILED"; exit 0; }
fi

PREV=0
if docker image inspect cofferant-app:latest >/dev/null 2>&1; then
  docker tag cofferant-app:latest cofferant-app:previous
  PREV=1
fi
echo "[server] loading the image" >&2
gunzip -c "incoming/$TAR" | docker load >&2
rm -f "incoming/$TAR"
{ ls -1t incoming/*.tar.gz 2>/dev/null || true; } | tail -n +3 | xargs -r rm -f --   # keep the 2 newest uploads

if [ ! -f .env ]; then echo "NEEDS_SETUP"; exit 0; fi

docker compose up -d --no-build >&2 </dev/null
for _ in $(seq 1 120); do
  [ "$(docker compose ps app --format '{{.Health}}' 2>/dev/null | head -1)" = "healthy" ] && { docker image prune -f >/dev/null 2>&1 || true; echo "HEALTHY PREV=$PREV"; exit 0; }
  sleep 1
done
echo "UNHEALTHY"
REMOTE
)" || { echo "The step on the server failed (see the messages above). Nothing was left half-done that a re-run cannot fix." >&2; exit 1; }

case "$STATUS" in
  *BACKUP_FAILED*)
    echo "" >&2
    echo "The automatic backup before the switch failed, so nothing was changed (the image was NOT loaded)." >&2
    echo "Check the app on the server ('docker compose logs --tail=50 app'), then run this again." >&2
    exit 1 ;;
  *NEEDS_SETUP*)
    echo ""
    echo "The server has no .env yet, so this is a first deployment. The image and scripts are in place."
    if [[ -n "${MODE:-}" && -n "${DOMAIN:-}" && -n "${LETSENCRYPT_EMAIL:-}" ]]; then
      echo "==> Finishing the setup (certificate + nginx)"
      ssh -t "${SSH_ARGS[@]}" "$HOST" "cd '$DIR' && MODE='$MODE' DOMAIN='$DOMAIN' LETSENCRYPT_EMAIL='$LETSENCRYPT_EMAIL' ./scripts/bootstrap-vps.sh"
    else
      echo "Finish it with ONE command on the server:"
      echo "    ssh ${HOST} \"cd ${DIR} && MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@example.com ./scripts/bootstrap-vps.sh\""
      echo "(or re-run this command with MODE=platform DOMAIN=... LETSENCRYPT_EMAIL=... and it will do that for you)"
    fi
    exit 0 ;;
  *UNHEALTHY*)
    echo "" >&2
    echo "The new version did not become healthy. Look:   ssh ${HOST} 'cd ${DIR} && docker compose logs --tail=60 app'" >&2
    echo "Go back to the previous version with:           make rollback-remote HOST=${HOST}" >&2
    exit 1 ;;
  *HEALTHY*) ;;
  *) echo "Unexpected answer from the server: ${STATUS}" >&2; exit 1 ;;
esac

echo ""
echo "================================================================"
echo " Deployed ${TAG} to ${HOST}:${DIR}"
echo "================================================================"
case "$STATUS" in *PREV=1*) echo "  Previous version kept as cofferant-app:previous  ->  make rollback-remote HOST=${HOST}" ;; esac
echo "  Check the public site:  make deploy-health HOST=https://yourdomain.com"
