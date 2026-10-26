#!/usr/bin/env bash
# Print the daily listings table (scripts/listings_table.py) for a --no-agent cron job to deliver.
# One job per owner runs this at the same time; the output depends only on the CSV and the clock,
# so every owner gets the same message. Installed to ~/.hermes/scripts/ (--script resolves there).
#
# A failure prints a loud line rather than nothing: an owner who gets no table assumes there was
# nothing to show.

set -uo pipefail
REPO="${REPO:-${HOME}/hermes-vineyard}"
cd "$REPO" || { echo "⚠️ Listings table unavailable: no repo at $REPO"; exit 0; }
out="$(python3 scripts/listings_table.py 2>&1)" \
  || { echo "⚠️ Listings table failed: $(printf '%s' "$out" | tail -1)"; exit 0; }
printf '%s\n' "$out"
