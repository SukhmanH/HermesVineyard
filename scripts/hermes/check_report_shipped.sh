#!/usr/bin/env bash
# Watchdog: did the grower report actually SHIP this morning?
#
# Why this exists: from 2026-08-31 to 2026-09-07 nobody received a daily report
# for eight consecutive days, and every cron job reported last_status=ok the
# whole time. The composer ran, the emitter correctly REFUSED to send unusable
# output, and a refusal is a successful script run - exit 0, status ok. The
# alarm had nowhere to ring.
#
# So this checks the thing that actually matters - did real report text reach
# an owner today - rather than whether the jobs "ran". Prints nothing when the
# report shipped (no_agent jobs send nothing on empty stdout), and shouts only
# when a human needs to intervene.
#
# Runs after the emitters (05:20) have had time to finish.

set -uo pipefail

EMITTERS="${EMITTERS:-5680a0754207 b378f1a53116}"
OUT_ROOT="${HOME}/.hermes/cron/output"
today="$(date +%Y-%m-%d)"

shipped=0
failed_names=()

for jid in $EMITTERS; do
  d="${OUT_ROOT}/${jid}"
  [[ -d "$d" ]] || { failed_names+=("${jid} (no output dir)"); continue; }

  # Today's newest run transcript for this emitter.
  f="$(ls -t "${d}/${today}"_*.md 2>/dev/null | head -n1)"
  if [[ -z "$f" ]]; then
    failed_names+=("${jid} (did not run today)")
    continue
  fi

  name="$(grep -m1 '^# Cron Job:' "$f" | sed 's/^# Cron Job: //')"
  [[ -n "$name" ]] || name="$jid"

  # The emitter prints its refusal banner starting with the warning sign.
  # Anything containing that is a report that did NOT reach the owner.
  if grep -q '⚠️' "$f"; then
    reason="$(grep -m1 -o '⚠️[^$]*' "$f" | head -c 130)"
    failed_names+=("${name}: ${reason}")
  else
    shipped=$((shipped + 1))
  fi
done

# Silence = success. Only speak when someone must act.
if (( ${#failed_names[@]} > 0 )); then
  printf '🚨 GROWER REPORT DID NOT SHIP (%s)\n\n' "$today"
  for m in "${failed_names[@]}"; do
    printf '%s\n\n' "$m"
  done
  printf 'Nobody received a spray verdict from those jobs this morning.\n'
  printf 'Composer output: ~/.hermes/cron/output/1c4e3ae8eb61/\n'
  printf 'Emitter: ~/.hermes/scripts/emit_grower_report.sh\n'
fi

exit 0
