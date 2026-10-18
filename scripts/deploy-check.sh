#!/usr/bin/env bash
# Pre-flight checks to run BEFORE deploying Cofferant.
#
#   make deploy-check
#
# Catches the mistakes that are cheap to find now and expensive in production:
# committed secrets, weak or default values, failing tests, wrong mode settings.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source scripts/lib.sh

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in .venv/Scripts/python.exe .venv/bin/python python3 python; do
    if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then PY="$c"; break; fi
  done
fi

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
errors=0; warnings=0
ok()   { echo "  ${GREEN}[OK]${NC}    $1"; }
bad()  { echo "  ${RED}[BLOCK]${NC} $1"; errors=$((errors + 1)); }
warn() { echo "  ${YELLOW}[WARN]${NC}  $1"; warnings=$((warnings + 1)); }

echo ""
echo "Cofferant deploy pre-flight"
echo "==========================="

echo ""
echo "1. Secrets"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  bad ".env is tracked by git — it holds credentials (fix: git rm --cached .env)"
else
  ok ".env is not tracked"
fi

if [[ ! -f .env ]]; then
  warn ".env not found — create it with: make env"
else
  load_env .env 2>/dev/null
  MODE="${DEPLOYMENT_MODE:-standalone}"
  ok "mode: ${MODE}"
  [[ ${#DJANGO_SECRET_KEY} -ge 40 && "$DJANGO_SECRET_KEY" != change-me* ]] && ok "DJANGO_SECRET_KEY is ${#DJANGO_SECRET_KEY} chars" || bad "DJANGO_SECRET_KEY must be a random value of 40+ characters (make env generates one)"
  if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
    bad "ADMIN_PASSWORD is empty — nobody could sign in to the panel"
  elif [[ ${#ADMIN_PASSWORD} -lt 12 ]]; then
    bad "ADMIN_PASSWORD must be at least 12 characters"
  else
    ok "ADMIN_PASSWORD is strong enough"
  fi
  [[ -n "${APP_DOMAIN:-}" ]] && ok "APP_DOMAIN=${APP_DOMAIN}" || bad "APP_DOMAIN is empty"
  [[ "${DJANGO_ALLOWED_HOSTS:-}" == *"${APP_DOMAIN:-__none__}"* ]] && ok "DJANGO_ALLOWED_HOSTS includes the domain" || warn "DJANGO_ALLOWED_HOSTS does not list ${APP_DOMAIN:-the domain}"
  [[ "${DJANGO_CSRF_TRUSTED_ORIGINS:-}" == https://* ]] && ok "CSRF trusted origins are https" || warn "DJANGO_CSRF_TRUSTED_ORIGINS should be https://${APP_DOMAIN:-your.domain}"
  [[ -n "${LETSENCRYPT_EMAIL:-}" ]] && ok "LETSENCRYPT_EMAIL set" || warn "LETSENCRYPT_EMAIL is empty (needed by make ssl)"

  [[ -n "${BACKUP_REMOTE:-}" ]] && ok "off-server backups: ${BACKUP_REMOTE}" || warn "no off-server backup copy (BACKUP_REMOTE): losing this server would lose the backups too — make backup-remote-setup REMOTE=user@host:/path"

  if [[ "$MODE" == "platform" ]]; then
    [[ "${PLATFORM_DOMAIN:-localhost}" != "localhost" ]] && ok "PLATFORM_DOMAIN=${PLATFORM_DOMAIN}" || bad "platform mode needs PLATFORM_DOMAIN (your root domain)"
    [[ -n "${CF_API_TOKEN:-}" ]] && ok "CF_API_TOKEN set (wildcard certificate can auto-renew)" || warn "no CF_API_TOKEN: the wildcard certificate needs CHALLENGE=dns and manual renewal"
  else
    if [[ "${LICENSE_ENFORCE:-0}" == "1" ]]; then
      [[ -n "${LICENSE_KEY:-}" && -n "${LICENSE_SERVER_URL:-}" ]] && ok "license enforcement configured" || bad "LICENSE_ENFORCE=1 needs LICENSE_KEY and LICENSE_SERVER_URL"
    else
      warn "LICENSE_ENFORCE is off — correct for your own cafe, not for a customer's install"
    fi
  fi
fi

echo ""
echo "2. Build"
if [[ -n "$PY" ]]; then
  if "$PY" manage.py check >/dev/null 2>&1; then ok "django check passes"; else bad "django check fails ($PY manage.py check)"; fi
  if "$PY" manage.py makemigrations --check --dry-run >/dev/null 2>&1; then ok "no missing migrations"; else bad "models changed without a migration (manage.py makemigrations)"; fi
  if "$PY" manage.py test --noinput >/dev/null 2>&1; then ok "test suite passes"; else bad "tests fail ($PY manage.py test)"; fi
else
  warn "python not found; skipping the django checks"
fi
if command -v docker >/dev/null 2>&1; then
  docker compose config -q >/dev/null 2>&1 && ok "docker-compose.yml is valid" || warn "docker compose config reported a problem (is .env complete?)"
fi
for f in scripts/*.sh docker/entrypoint.sh; do bash -n "$f" 2>/dev/null || bad "syntax error in $f"; done
ok "shell scripts parse"

echo ""
echo "3. Repository hygiene"
tracked_bad="$(git ls-files 2>/dev/null | grep -E '(^|/)(\.env|\.venv/|winenv/|node_modules/|dist/|data/|staticfiles/|media/)|\.sqlite3$|\.log$' | grep -v '\.env\.example' | head -5)"
if [[ -n "$tracked_bad" ]]; then
  bad "files that should never be committed are tracked:"; sed 's/^/           /' <<<"$tracked_bad"
else
  ok "no env files, virtualenvs, databases or uploads are tracked"
fi
uncommitted="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
[[ "$uncommitted" != "0" ]] && warn "$uncommitted uncommitted change(s) — the server builds what you push"

echo ""
echo "==========================="
if (( errors > 0 )); then
  echo "${RED}${errors} blocker(s)${NC}, ${warnings} warning(s) — do not deploy yet"
  exit 1
fi
echo "${GREEN}No blockers${NC}, ${warnings} warning(s)"
echo ""
echo "Next, on the server:  MODE=platform|standalone DOMAIN=... LETSENCRYPT_EMAIL=... ./scripts/bootstrap-vps.sh"
echo "Low-resource VPS:     make images-bundle  ->  scp  ->  make load-images  ->  ./scripts/bootstrap-vps.sh"
