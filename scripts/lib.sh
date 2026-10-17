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
