#!/usr/bin/env bash
# Rebuild the static panel from the live database and deploy it to Vercel.
#
# Prerequisites (one-time, done by you):
#   vercel login
#   cd data/exports/panel && vercel link
#
# Usage:
#   scripts/deploy_panel.sh            # rebuild + deploy to production
#   scripts/deploy_panel.sh --preview  # deploy to a preview URL instead
#
# Safe to run from cron. Exits non-zero on any failure so a silent
# no-op never masquerades as a successful deploy.

set -euo pipefail

REPO="/home/waris/hermes-vineyard"
PANEL="$REPO/data/exports/panel"
PYTHON="$REPO/.venv/bin/python"
export PATH="$HOME/.local/bin:$PATH"

TARGET="--prod"
if [[ "${1:-}" == "--preview" ]]; then
    TARGET=""
fi

echo "[$(date -Is)] Rebuilding static panel from live database..."
"$PYTHON" "$REPO/tools/build_panel_static.py" --out "$PANEL"

# Refuse to deploy a snapshot that failed to render its data. A panel showing
# an empty page is worse than no panel, because it will be trusted.
"$PYTHON" - "$PANEL/dashboard.json" <<'PYCHECK'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
for key in ("sections", "metrics", "alerts"):
    if not isinstance(data.get(key), list):
        sys.exit(f"FATAL: {key} is not a list - dashboard.js would reject this snapshot.")
if not data["sections"]:
    sys.exit("FATAL: snapshot contains zero sections - refusing to deploy an empty panel.")
rows = sum(len(s.get("rows") or []) for s in data["sections"])
if rows == 0:
    sys.exit("FATAL: snapshot contains zero rows across all sections - refusing to deploy.")
print(f"  preflight OK: {len(data['sections'])} sections, {rows} rows")
PYCHECK

if [[ ! -f "$PANEL/.vercel/project.json" ]]; then
    echo "ERROR: $PANEL is not linked to a Vercel project." >&2
    echo "Run once:  cd $PANEL && vercel link" >&2
    exit 1
fi

echo "[$(date -Is)] Deploying to Vercel..."
cd "$PANEL"
vercel deploy $TARGET --yes

echo "[$(date -Is)] Done."
