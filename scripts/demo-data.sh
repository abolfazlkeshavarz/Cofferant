#!/usr/bin/env bash
#
# Loads a demo menu, six tables and sample orders so the dashboard has something to show.
# Local/dev (or a demo server) only — it writes into whichever database the target uses.
#
#   make demo               # local development database
#   PROD=1 make demo        # the running container (use only on a demo server)
#
# Safe to re-run: existing products/tables are kept and sample orders are only created once.
set -euo pipefail
cd "$(dirname "$0")/.."

exec bash scripts/admin.sh seed_demo
