#!/usr/bin/env bash
# Emit the most recent composed grower report on stdout, for a --no-agent cron
# job to deliver verbatim.
#
# Why this exists: an agent cron job cannot deliver to more than one person -
# --deliver takes a single target - and Hermes injects "do NOT deliver the
# output yourself" into every agent run, so the composing job cannot fan out
# either. Composing once per owner instead would mean two model runs that can
# disagree about what to spray on the same morning. So one agent job composes
# (--deliver local) and one of these runs per owner prints that same text.
#
# Silence is the failure mode that matters here. A grower who gets nothing
# assumes there was nothing to say, so this prints a loud line rather than
# exiting quietly when the report is missing or stale.

set -uo pipefail

COMPOSER_JOB_ID="${COMPOSER_JOB_ID:-1c4e3ae8eb61}"
OUT_DIR="${HOME}/.hermes/cron/output/${COMPOSER_JOB_ID}"
MAX_AGE_MIN="${MAX_AGE_MIN:-45}"

if [[ ! -d "$OUT_DIR" ]]; then
  echo "⚠️ Daily report unavailable: no output directory for the composing job (${COMPOSER_JOB_ID}). Nobody received a report this morning."
  exit 0
fi

latest="$(ls -t "${OUT_DIR}"/*.md 2>/dev/null | head -1)"
if [[ -z "$latest" ]]; then
  echo "⚠️ Daily report unavailable: the composing job has produced no output. Nobody received a report this morning."
  exit 0
fi

# Refuse to ship a stale report. Yesterday's spray verdict read as today's is
# worse than an obvious gap - someone could spray on a window that has closed.
age_min=$(( ( $(date +%s) - $(stat -c %Y "$latest") ) / 60 ))
if (( age_min > MAX_AGE_MIN )); then
  echo "⚠️ Daily report is ${age_min} min old (limit ${MAX_AGE_MIN}) - the composing job did not run this morning. Not sending a stale report; today's spray verdict is unknown."
  exit 0
fi

# The cron output file is the whole run transcript: the skill text and prompt
# are echoed above the report itself, under a "## Response" heading. Only the
# part after that heading is the report.
body="$(awk '/^## Response$/{found=1; next} found' "$latest")"

if [[ -z "${body//[[:space:]]/}" ]]; then
  echo "⚠️ Daily report composed but came out empty. Check the composing job's run output."
  exit 0
fi

printf '%s\n' "$body"
