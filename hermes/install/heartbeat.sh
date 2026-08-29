#!/usr/bin/env bash
# 15-minute liveness check. Runs as `--no-agent --script`: NO LLM in the loop, because this must
# keep working precisely when the model provider is the thing that is broken.
#
# Installed to $HERMES_HOME/scripts/heartbeat.sh by bootstrap.sh - `--script` resolves paths
# there, not in the repo.
#
# ── The watchdog paradox, stated plainly ────────────────────────────────────────────────────
# This script is itself a cron job. If the ticker stops, THIS DOES NOT RUN, so it cannot be the
# thing that tells you cron died. That is what healthchecks.io is for: it is a dead-man's switch
# living on someone else's computer. We ping it while healthy; the ABSENCE of a ping is what
# raises the alarm. Never "improve" this by making the alerting depend only on this script.
#
# So there are two jobs here:
#   1. Ping healthchecks.io while things are fine  -> covers total death (nothing runs at all)
#   2. Detect a gateway that is down while cron still ticks -> covers partial failure, and
#      alerts by EMAIL, because WhatsApp is exactly what is broken
#
# Empty output = silent tick. Non-zero exit = Hermes raises an alert.

set -uo pipefail

# HEALTHCHECKS_URL is the complete ping URL healthchecks.io hands you, and is what the .py
# twin and the live .env use. HEALTHCHECKS_BASE_URL is the older base form kept working here
# so an existing install does not silently stop pinging on upgrade.
HC_URL="${HEALTHCHECKS_URL:-}"
if [ -z "$HC_URL" ] && [ -n "${HEALTHCHECKS_BASE_URL:-}" ]; then
  HC_URL="${HEALTHCHECKS_BASE_URL%/}/heartbeat"
fi
ALERT_EMAIL="${OWNER_EMAIL:-}"
HH="${HERMES_HOME:-$HOME/.hermes}"
TICKER="$HH/cron/ticker_heartbeat"
MAX_TICKER_AGE=300      # ticker wakes ~every 60s; 5 min stale means it has stopped

problems=""

# ── 1. Is cron actually ticking? ────────────────────────────────────────────────────────────
# VERIFIED 2026-08-22: this file holds a unix epoch, refreshed each ticker wake. It asserts the
# OUTCOME we care about (jobs fire) rather than the proxy (a process exists).
if [ -f "$TICKER" ]; then
  now=$(date +%s)
  last=$(cut -d. -f1 < "$TICKER" 2>/dev/null || echo 0)
  age=$(( now - last ))
  if [ "$age" -gt "$MAX_TICKER_AGE" ]; then
    problems="${problems}CRON TICKER STALE: last tick ${age}s ago (expected <60s)"$'\n'
  fi
else
  problems="${problems}CRON TICKER FILE MISSING: $TICKER"$'\n'
fi

# ── 2. Is the gateway connected? ────────────────────────────────────────────────────────────
# VERIFIED 2026-08-22: `hermes gateway status` EXITS 0 EVEN WHEN THE GATEWAY IS DOWN, so the
# exit code is worthless here and we must read the text. It prints "Gateway is not running" when
# down. Match the negative explicitly rather than hunting for a positive word - an earlier
# version grepped for "connected", which the command never prints, so it reported failure
# forever. A watchdog that cries wolf every 15 minutes gets muted, and then the real outage is
# the one nobody sees.
status="$(hermes gateway status 2>&1 || true)"
if grep -qiE "not running|not connected|✗" <<<"$status"; then
  problems="${problems}GATEWAY DOWN"$'\n'"$status"$'\n'
fi

# ── Report ──────────────────────────────────────────────────────────────────────────────────
if [ -n "$problems" ]; then
  printf '%s' "$problems"

  if [ -n "$ALERT_EMAIL" ] && command -v mail >/dev/null 2>&1; then
    printf 'Hermes health check failed.\n\n%s\nScheduled jobs may not be firing.\n' \
      "$problems" | mail -s "Hermes: HEALTH CHECK FAILED" "$ALERT_EMAIL"
  fi

  # Deliberately do NOT ping healthchecks: a missed ping is what makes it email the owner
  # independently of anything running on this machine.
  exit 1
fi

[ -n "$HC_URL" ] && curl -fsS -m 10 --retry 3 "$HC_URL" >/dev/null 2>&1
exit 0
