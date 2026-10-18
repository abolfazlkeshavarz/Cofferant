#!/usr/bin/env bash
#
# Shared helpers sourced by the other scripts. Not meant to be run directly.

# load_env <file>
#
# Loads a .env-style file WITHOUT `source`, which would execute every line as a
# shell command. Only well-formed KEY=VALUE lines are exported; anything else
# is reported and skipped. Inline "  # comments" after a value are stripped.
load_env() {
  local file="${1:-.env}"
  if [[ ! -f "$file" ]]; then
    echo "Error: $file not found." >&2
    return 1
  fi
  set -a
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      line="$(sed -E 's/[[:space:]]+#.*$//' <<<"$line")"
      export "$line"
    else
      echo "Warning: ignoring malformed line in $file: $line" >&2
    fi
  done < "$file"
  set +a
}

# port_in_use <port> — true if anything on this host is listening on it.
port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -Htln "( sport = :$port )" 2>/dev/null | grep -q .
    return $?
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && { exec 3>&-; return 0; }
  return 1
}

# find_free_port <start> — first free port at or above <start>.
find_free_port() {
  local port="${1:-8081}"
  while port_in_use "$port"; do
    port=$((port + 1))
  done
  echo "$port"
}

# rand_secret <bytes> — URL/shell-safe random string.
rand_secret() {
  local bytes="${1:-32}"
  openssl rand -base64 "$bytes" | tr -d '\n=+/'
}

# set_env_value <file> <KEY> <value> — replace KEY=… (or append it).
set_env_value() {
  local file="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value//|/\\|}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}


# apply_domain_env <env-file> <new-domain> <mode> <old-domain> <keep-old: 1|0>
#
# Points an .env at a new domain. With keep-old=1 the previous domain keeps working: it stays in the allowed
# hosts and, in platform mode, becomes an alias so customers' old sub-domains and the license-check address
# of self-hosted installs don't break.
apply_domain_env() {
  local file="$1" new="$2" mode="$3" old="${4:-}" keep="${5:-1}"
  local hosts="${new},localhost,127.0.0.1" origins="https://${new}" aliases=""
  if [[ "$mode" == "platform" ]]; then
    aliases="$(grep -E '^PLATFORM_ALIAS_DOMAINS=' "$file" | head -1 | cut -d= -f2- | tr -d '\r' || true)"
  fi
  [[ "$keep" == "1" ]] || aliases=""   # dropping the old domain drops every earlier alias too
  if [[ "$keep" == "1" && -n "$old" && "$old" != "$new" ]]; then
    hosts="${new},${old},localhost,127.0.0.1"
    origins="https://${new},https://${old}"
    aliases="${aliases:+$aliases,}${old}"
  fi
  hosts="$(tr ',' '\n' <<<"$hosts" | awk 'NF && !seen[$0]++' | paste -sd, -)"
  origins="$(tr ',' '\n' <<<"$origins" | awk 'NF && !seen[$0]++' | paste -sd, -)"
  if [[ "$mode" == "platform" ]]; then
    # unique, and never list the new domain as its own alias
    aliases="$(tr ',' '\n' <<<"$aliases" | grep -v -x -e '' -e "$new" | awk '!seen[$0]++' | paste -sd, - || true)"
    set_env_value "$file" PLATFORM_DOMAIN "$new"
    set_env_value "$file" PLATFORM_ALIAS_DOMAINS "$aliases"
  fi
  set_env_value "$file" APP_DOMAIN "$new"
  set_env_value "$file" DJANGO_ALLOWED_HOSTS "$hosts"
  set_env_value "$file" DJANGO_CSRF_TRUSTED_ORIGINS "$origins"
}

# valid_hostname <name> — plain DNS name such as menu.example.com
valid_hostname() {
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]
}


# custom_domains — customers' own domains registered in the running app (one per line).
# Django's shell prints an "objects imported" notice on stdout, so keep only real host names.
custom_domains() {
  "${DOCKER:-docker}" compose exec -T app python manage.py shell --no-imports -c "
from licensing.models import License
print('\\n'.join(License.objects.filter(mode='hosted', deleted_at__isnull=True).exclude(domain='').values_list('domain', flat=True)))
" 2>/dev/null | tr -d '\r' | grep -E '^([a-z0-9-]+\.)+[a-z]{2,}$' || true
}
