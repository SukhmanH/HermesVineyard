#!/usr/bin/env bash
# Rebuild the dev database on the current schema. Safe: the old file is kept.
# REQUIRES: no `hermes chat` session running (it holds the MCP server, which holds the DB).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null
ts=$(date +%Y%m%d_%H%M%S)
if [ -f data/hermes.db ]; then
  mv data/hermes.db "data/hermes.db.bak.$ts" || {
    echo "DB is locked - exit your 'hermes chat' session first, then re-run."; exit 1; }
fi
rm -f data/hermes.db-wal data/hermes.db-shm
python -m vineyard_mcp init-db
python -m vineyard_mcp import-seed seed/
python -m vineyard_mcp doctor || true
echo "Done. Old database kept at data/hermes.db.bak.$ts"
