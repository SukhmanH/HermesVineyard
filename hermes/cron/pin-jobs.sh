#!/usr/bin/env bash
# Pin EXISTING cron jobs to an explicit provider + model.
#
# WHY THIS EXISTS, separate from setup-jobs.sh: setup-jobs.sh CREATES jobs. Running it again
# against a host that already has them mints a second full set of duplicates - every report sent
# twice. Repairing already-created jobs is `hermes cron edit`, and that is what this does.
#
# THE FAILURE IT REPAIRS (seen live 2026-08-29): the spend-guard watches the WHOLE inference
# config, not just the provider. The global model drifted
# (poolside/laguna-s-2.1:free -> stepfun/step-3.7-flash:free) and every job created with only
# --provider pinned was treated as unpinned and silently skipped:
#     "Skipped to prevent unintended spend: global inference config drifted"
# The guard alerts ONCE per job and then stays quiet, so the jobs stay dark without further
# warning. Pin both halves.
#
# Dry-run by default. Nothing is changed until you pass --apply.
#
# Usage:
#   hermes/cron/pin-jobs.sh <provider> <model>            # show what would change
#   hermes/cron/pin-jobs.sh <provider> <model> --apply    # do it
#
# Find the current values with:  hermes config get model.provider ; hermes config get model.model

set -euo pipefail

PROVIDER="${1:-}"
MODEL="${2:-}"
APPLY="${3:-}"

if [ -z "$PROVIDER" ] || [ -z "$MODEL" ]; then
  echo "usage: $0 <provider> <model> [--apply]" >&2
  exit 2
fi

JOBS_FILE="${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json"
if [ ! -f "$JOBS_FILE" ]; then
  echo "ERROR: no jobs file at $JOBS_FILE" >&2
  echo "       (set HERMES_HOME if Hermes lives elsewhere on this host)" >&2
  exit 1
fi

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import json" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "ERROR: no working python3 on PATH" >&2; exit 1; }

# Read id/name straight from jobs.json rather than parsing `hermes cron list` table output:
# the file is the source of truth (docs/01, docs/03) and its shape does not move with CLI
# cosmetics. Script-only jobs (heartbeat: --no-agent) make no inference call, so the guard does
# not apply to them and `cron edit --model` has nothing to pin - they are skipped.
JOBS="$("$PY" - "$JOBS_FILE" <<'PYEOF'
import json, sys

raw = json.load(open(sys.argv[1], encoding="utf-8"))
if isinstance(raw, dict):
    items = raw.get("jobs", raw)
    entries = list(items.values()) if isinstance(items, dict) else list(items)
    # a dict keyed by id still carries the id as the key when the value omits it
    if isinstance(items, dict):
        for k, v in items.items():
            if isinstance(v, dict):
                v.setdefault("id", k)
else:
    entries = list(raw)

for job in entries:
    if not isinstance(job, dict):
        continue
    jid = job.get("id") or job.get("job_id") or job.get("uuid")
    name = job.get("name") or job.get("job_name") or "?"
    if not jid:
        continue
    # skip non-agent jobs however this version spells it
    if job.get("script") or job.get("no_agent") or job.get("agent") is False:
        continue
    print("%s\t%s\t%s\t%s" % (jid, name, job.get("provider") or "-", job.get("model") or "-"))
PYEOF
)"

if [ -z "$JOBS" ]; then
  echo "No agent jobs found in $JOBS_FILE - nothing to pin." >&2
  exit 1
fi

printf '%-14s %-26s %-14s %s\n' JOB_ID NAME PROVIDER MODEL
echo "$JOBS" | while IFS=$'\t' read -r jid name prov mod; do
  printf '%-14s %-26s %-14s %s\n' "$jid" "$name" "$prov" "$mod"
done
echo

if [ "$APPLY" != "--apply" ]; then
  echo "DRY RUN. Would pin every job above to: provider=$PROVIDER model=$MODEL"
  echo "Re-run with --apply to make the change."
  exit 0
fi

# Fed by here-string, not a pipe: a piped `while` runs in a SUBSHELL, so the failure count would
# be discarded and a partial repair would exit 0 looking clean.
fails=0
while IFS=$'\t' read -r jid name prov mod; do
  echo "pinning $name ($jid) -> $PROVIDER / $MODEL"
  if ! hermes cron edit "$jid" --provider "$PROVIDER" --model "$MODEL"; then
    echo "  FAILED: $name ($jid)" >&2
    fails=$((fails + 1))
  fi
done <<< "$JOBS"

echo
if [ "$fails" -gt 0 ]; then
  echo "$fails job(s) FAILED to pin - those are STILL skipped. Fix the cause and re-run." >&2
  exit 1
fi
echo "Done. Verify, and confirm the gateway is actually ticking:"
echo "  hermes cron list"
echo "  hermes cron status"
echo "A skipped job stays skipped until pinned - check tomorrow's 04:30 run landed:"
echo "  hermes cron runs"
