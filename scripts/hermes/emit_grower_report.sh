#!/usr/bin/env bash
# Emit the most recent VALID composed grower report on stdout, for a --no-agent
# cron job to deliver verbatim.
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
# exiting quietly when the report is missing or unusable.
#
# Three failures this script has actually seen in production, and what it now
# does about each:
#
#  1. RACE. The emitter fired while the composer was still running, so the
#     transcript had no "## Response" section yet and every owner got
#     "came out empty" for a week. A wall-clock minute budget could not fix
#     this: the composer legitimately takes 12-43 min, so any limit tight
#     enough to catch a stale report also rejected good ones. So the freshness
#     test is now the CALENDAR DAY the report was composed, not its age in
#     minutes. Today's report is fresh at any hour; yesterday's never ships.
#
#  2. NEWEST FILE IS A FAILED RUN. A crashed run still writes a transcript,
#     which is newer than the good one from a successful earlier attempt. So
#     this walks candidates newest-first and takes the first one that actually
#     contains a report, instead of trusting the newest blindly.
#
#  3. NARRATION DUMP. When the model reasons in its final message, "## Response"
#     held 40 KB of "Let me analyze each: **Penticton hourly forecast**..."
#     instead of the report. That is worse than silence - it buries the spray
#     verdict. So the report is extracted from its first template anchor (an
#     emoji section header) and rejected if it fails a sanity check.

set -uo pipefail

COMPOSER_JOB_ID="${COMPOSER_JOB_ID:-1c4e3ae8eb61}"
OUT_DIR="${HOME}/.hermes/cron/output/${COMPOSER_JOB_ID}"

# How many days back to accept. 0 = today only. Kept as a knob because on a
# travel day or a router outage the grower may still prefer a labelled
# yesterday's report over nothing - but that has to be a deliberate choice.
MAX_AGE_DAYS="${MAX_AGE_DAYS:-0}"

# How many transcripts back to search for a usable report.
SCAN_DEPTH="${SCAN_DEPTH:-6}"

# A real report leads with the spray section. This is the template anchor from
# templates/en.yaml (grower_report) and the single most reliable marker that we
# are looking at a rendered report rather than model narration.
ANCHOR='🧪'

fail() { printf '%s\n' "$1"; exit 0; }

[[ -d "$OUT_DIR" ]] && ls "${OUT_DIR}"/*.md >/dev/null 2>&1 \
  || fail "⚠️ Daily report unavailable: the composing job (${COMPOSER_JOB_ID}) has produced no output. Nobody received a report this morning."

today="$(date +%Y-%m-%d)"
oldest_ok="$(date -d "-${MAX_AGE_DAYS} days" +%Y-%m-%d)"

newest_seen=""
rejected_narration=0

while IFS= read -r f; do
  base="$(basename "$f")"
  # Transcripts are named YYYY-MM-DD_HH-MM-SS.md. Prefer that date over mtime:
  # mtime changes if a file is touched or copied, the composed date does not.
  fdate="${base:0:10}"
  [[ "$fdate" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fdate="$(date -r "$f" +%Y-%m-%d)"
  [[ -z "$newest_seen" ]] && newest_seen="$fdate"

  # Too old to ship. Files are newest-first, so everything after this is older.
  [[ "$fdate" < "$oldest_ok" ]] && break

  grep -q '^## Response$' "$f" || continue

  # Take everything from the first emoji section header onward. This drops any
  # preamble the model wrote above the report ("Now I have all three sites'
  # data, let me analyze...") without needing the model to behave perfectly.
  body="$(awk -v anchor="$ANCHOR" '
    /^## Response$/ { inresp=1; next }
    inresp && !started && index($0, anchor) { started=1 }
    started { print }
  ' "$f")"

  if [[ -z "${body//[[:space:]]/}" ]]; then
    # There was a Response section but no report anchor in it. If that section
    # has real bulk, the model answered with prose instead of the report -
    # name that, because it is a prompt/skill problem, not a missing run.
    resp_bytes=$(awk '/^## Response$/{f=1;next} f' "$f" | wc -c)
    (( resp_bytes > 400 )) && rejected_narration=1
    continue
  fi

  # Sanity check. A rendered report is a few KB of short lines. A narration dump
  # is tens of KB of prose. Shipping that at 04:30 buries the spray verdict in
  # reasoning the grower did not ask for, so treat it as a compose failure.
  bytes=${#body}
  if (( bytes > 12000 )); then
    rejected_narration=1
    continue
  fi

  # A report with no weather section is a partial compose, not a quiet day.
  #
  # Match the WORD, not a specific emoji. On 2026-09-07 a complete, correct
  # report was suppressed for every owner because the composer wrote
  # "🌡 WEATHER:" while this check grepped for "🌤" - the template says 🌤️,
  # the model reached for the thermometer, and one codepoint of drift beat a
  # guardrail whose whole job is to prevent silence. Emoji choice is model
  # discretion; the section heading is the contract.
  grep -qi 'weather' <<<"$body" || { rejected_narration=1; continue; }

  printf '%s\n' "$body"
  exit 0
done < <(ls -t "${OUT_DIR}"/*.md 2>/dev/null | head -n "$SCAN_DEPTH")

if (( rejected_narration )); then
  fail "⚠️ Daily report was composed but came out unusable (model narration instead of the report format, or missing the weather section). Not sending it. Today's spray verdict is unknown — check the composing job's run output."
fi

if [[ -n "$newest_seen" && "$newest_seen" < "$oldest_ok" ]]; then
  fail "⚠️ No daily report for ${today} — the newest one on file is from ${newest_seen}. The composing job did not run this morning. Not sending a stale report; today's spray verdict is unknown."
fi

fail "⚠️ Daily report unavailable: the composing job produced output for ${today} but no readable report in it. Nobody received a report this morning."
