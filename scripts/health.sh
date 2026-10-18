#!/usr/bin/env bash
# Health check for Cofferant.
#
#   bash scripts/health.sh                               # the local docker stack
#   API_URL=https://x REMOTE=1 bash scripts/health.sh    # only the public side of a deployment
#
# Exits non-zero if anything required is down, so it works as a post-deploy gate.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source scripts/lib.sh
[[ -f .env ]] && load_env .env 2>/dev/null

API_URL="${API_URL:-http://127.0.0.1:${WEB_PORT:-8081}}"
REMOTE="${REMOTE:-}"
DOCKER="${DOCKER:-docker}"
COMPOSE=("$DOCKER" compose)

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
failures=0; warnings=0
ok()   { echo "  ${GREEN}[OK]${NC}   $1"; }
bad()  { echo "  ${RED}[FAIL]${NC} $1"; failures=$((failures + 1)); }
warn() { echo "  ${YELLOW}[WARN]${NC} $1"; warnings=$((warnings + 1)); }

http_code() { local c; c=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null) || c=000; echo "${c:-000}"; }

check_public() {
  echo ""
  echo "Cofferant ($API_URL)"
  local code
  code=$(http_code "$API_URL/healthz")
  [[ "$code" == "200" ]] && ok "GET /healthz -> 200" || { bad "GET /healthz -> $code"; return; }

  code=$(http_code "$API_URL/")
  [[ "$code" == "200" ]] && ok "front page served" || bad "GET / -> $code"

  code=$(http_code "$API_URL/vendor/")
  [[ "$code" == "302" || "$code" == "402" ]] && ok "vendor panel requires sign-in" || bad "GET /vendor/ anonymous -> $code (expected 302)"

  code=$(http_code "$API_URL/static/app/app.css")
  [[ "$code" == "200" ]] && ok "static files served" || bad "GET /static/app/app.css -> $code (collectstatic problem?)"

  code=$(http_code "$API_URL/admin/login/")
  [[ "$code" == "200" ]] && ok "admin login reachable" || warn "GET /admin/login/ -> $code"
}

echo ""
echo "Cofferant health check"
echo "======================"

if [[ -n "$REMOTE" ]]; then
  check_public
else
  echo ""
  echo "Container"
  if ! command -v "$DOCKER" >/dev/null 2>&1; then
    warn "docker not found; skipping container checks"
  else
    cid="$("${COMPOSE[@]}" ps -q app 2>/dev/null | head -1)"
    if [[ -z "$cid" ]]; then
      bad "app is not running (try: make up)"
    else
      state="$("$DOCKER" inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)"
      health="$("$DOCKER" inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)"
      if [[ "$state" == "running" && ( "$health" == "healthy" || "$health" == "none" ) ]]; then
        ok "app ($state${health:+, $health})"
      elif [[ "$state" == "running" ]]; then
        warn "app running but health=$health"
      else
        bad "app is $state"
      fi

      echo ""
      echo "Data"
      plan="$("$DOCKER" exec "$cid" python manage.py showmigrations --plan 2>/dev/null || true)"
      if grep -q '^\[ \]' <<<"$plan"; then
        bad "there are unapplied migrations (restart the container: make restart)"
      else
        ok "all migrations applied"
      fi
      if [[ "${DEPLOYMENT_MODE:-standalone}" == "platform" ]]; then
        n="$("$DOCKER" exec "$cid" sh -c 'ls /app/data/tenants 2>/dev/null | wc -l' | tr -d '\r')"
        ok "hosted customer databases: ${n:-0}"
      fi
    fi
  fi
  check_public
fi

echo ""
echo "======================"
if (( failures > 0 )); then
  echo "${RED}${failures} failed${NC}, ${warnings} warning(s)"; exit 1
fi
echo "${GREEN}All required checks passed${NC}, ${warnings} warning(s)"
