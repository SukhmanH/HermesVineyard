#!/usr/bin/env bash
# Print the listings_frost messages ONE owner has not had yet, for a cron job to deliver.
#   emit_listings_frost.sh <recipient>      (a per-owner wrapper in ~/.hermes/scripts passes it)
#
# Why this exists: a cron job delivers to one target, and Hermes tells every agent run not to
# deliver anything itself, so listings_frost composes once with --deliver local and one job per
# owner passes that same text on, as emit_grower_report.sh does for the morning report. Composing
# once per owner would let four model runs tell four owners different things about a listing.
#
# Unlike the morning report, silence is the normal case here: most listings_frost runs end
# [SILENT], and a message must reach each owner once, not on every tick. So this prints NOTHING
# (cron then sends nothing) unless a finished listings_frost run newer than this owner's marker
# holds a real message. The marker ($STATE_DIR/<recipient>) names the newest finished run already
# handed on; run transcripts are named YYYY-MM-DD_HH-MM-SS.md, so names sort in time order.
#
# Quiet hours belong to the emit jobs' schedule (06:00-20:30, config/settings.yaml
# autonomy.quiet_hours): a run composed at night waits for the first morning tick.

set -uo pipefail

RECIPIENT="${1:-}"
[[ "$RECIPIENT" =~ ^[a-z0-9_-]+$ ]] || { echo "usage: emit_listings_frost.sh <recipient>" >&2; exit 2; }

COMPOSER_JOB_ID="${COMPOSER_JOB_ID:-dcfe2736bd46}"
OUT_DIR="${HOME}/.hermes/cron/output/${COMPOSER_JOB_ID}"
STATE_DIR="${STATE_DIR:-${HOME}/.hermes/cron/emit-state/listings_frost}"
# A real message is a handful of short lines. Tens of KB is the model narrating its reasoning,
# which would bury the listing; the morning report still ranks it, so that run is dropped.
MAX_BYTES="${MAX_BYTES:-6000}"
# A transcript younger than this may still be being written.
MIN_AGE_S="${MIN_AGE_S:-60}"
# Catching up after an outage: the newest few messages, not a flood.
MAX_MESSAGES=3

mkdir -p "$STATE_DIR"
marker="$STATE_DIR/$RECIPIENT"
last="$(cat "$marker" 2>/dev/null || true)"
last="${last:-0}"                       # no marker yet: every finished run is new

ls "$OUT_DIR"/*.md >/dev/null 2>&1 || exit 0

trim_lower() { tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

# Hermes' own rule (gateway.response_filters): [SILENT], SILENT, NO_REPLY or NO REPLY as the whole
# response or as its own first or last line means "send nothing".
is_silent() {
  local first final
  first="$(printf '%s\n' "$1" | awk 'NF {print; exit}' | trim_lower)"
  final="$(printf '%s\n' "$1" | awk 'NF {l = $0} END {print l}' | trim_lower)"
  for s in "$first" "$final"; do
    case "$s" in ""|"[silent]"|"silent"|"no_reply"|"no reply") return 0 ;; esac
  done
  return 1
}

now="$(date +%s)"
newest=""
messages=()
while IFS= read -r f; do
  base="$(basename "$f")"
  [[ "$base" > "$last" ]] || continue
  (( now - $(stat -c %Y "$f") >= MIN_AGE_S )) || break    # still being written: next tick
  grep -q '^## Response$' "$f" || continue                 # crashed before answering
  newest="$base"
  # the last "## Response" section, to the end of the file, without blank lines around it
  body="$(awk '/^## Response$/ {n = NR} {line[NR] = $0}
               END {s = n + 1; while (s <= NR && line[s] ~ /^[[:space:]]*$/) s++
                    e = NR;    while (e >= s && line[e] ~ /^[[:space:]]*$/) e--
                    for (i = s; i <= e; i++) print line[i]}' "$f")"
  if [[ "$(printf '%s\n' "$body" | awk 'NF {print; exit}')" == "[CRON_FAILURE]" ]]; then
    echo "skip $base: listings_frost reported a failure" >&2
    continue
  fi
  is_silent "$body" && continue
  if (( ${#body} > MAX_BYTES )); then
    echo "skip $base: ${#body} bytes reads like narration, not a message" >&2
    continue
  fi
  messages+=("$body")
done < <(ls "$OUT_DIR"/*.md | sort)

[[ -n "$newest" ]] || exit 0
printf '%s\n' "$newest" > "$marker.tmp" && mv "$marker.tmp" "$marker"

(( ${#messages[@]} )) || exit 0
start=$(( ${#messages[@]} > MAX_MESSAGES ? ${#messages[@]} - MAX_MESSAGES : 0 ))
for (( i = start; i < ${#messages[@]}; i++ )); do
  (( i > start )) && printf '\n'
  printf '%s\n' "${messages[i]}"
done
