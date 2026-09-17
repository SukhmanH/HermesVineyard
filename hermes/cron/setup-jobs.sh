#!/usr/bin/env bash
# Create the vineyard's scheduled triggers.
#
# ⚠ FLAGS VERIFIED against the installed Hermes on 2026-08-22. The earlier version of this file
#   used --schedule, --prompt, --context-from and --continuity, taken from documentation.
#   NONE of those exist. Real form is:
#       hermes cron create <schedule> <prompt> --name X --deliver Y --workdir Z --skill S
#   Re-check with `hermes cron create --help` after any upstream update.
#
# ⚠ --workdir IS NOT OPTIONAL. Without it a cron job loads NO project context files, which means
#   no HERMES.md - and HERMES.md is the only place a scheduled session learns its authority, its
#   obligations, and that its first call is get_situation. Verified: with --workdir the job reads
#   both HERMES.md and SOUL.md; the help text's "omit to preserve old behaviour" means exactly
#   "run blind".
#
# ⚠ THE GATEWAY TICKS CRON. `hermes cron list` warns when it is not running, and it is currently
#   not. Nothing below fires until:
#       hermes gateway install            # or, on the Linux host:
#       sudo hermes gateway install --system
#       hermes cron status
#
# A trigger hands Hermes a SITUATION, not a script. Every prompt says "decide", never "send".
#
# [SILENT] — the runtime injects its own convention: replying with exactly "[SILENT]" suppresses
# delivery. Use it together with skip_job, not instead of it: skip_job writes the reasoning to
# audit_log (accountability), [SILENT] stops the message going out (etiquette). Doing only the
# second makes a deliberate hold indistinguishable from a crash.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CREW="${CREW_GROUP_JID:-}"
if [ -z "$CREW" ]; then
  echo "NOTE: CREW_GROUP_JID unset - group jobs will deliver to 'local' instead of the crew group."
  GROUP="local"
else
  GROUP="whatsapp:${CREW}"
fi

# The spend-guard watches BOTH halves of the inference config. Pinning only --provider is NOT
# enough: on 2026-08-29 the global MODEL drifted (poolside/laguna-s-2.1:free ->
# stepfun/step-3.7-flash:free) and grower_daily_report was skipped even though its provider was
# pinned. Pin --provider AND --model on every agent job, or the guard treats it as unpinned.
#
# No defaults here on purpose. An implicit model is the bug this block exists to prevent: a
# default silently goes stale the next time the global config moves, and the failure mode is a
# job that stops running rather than one that errors. Set both explicitly.
: "${HERMES_JOB_PROVIDER:?set HERMES_JOB_PROVIDER (see: hermes config get model.provider)}"
: "${HERMES_JOB_MODEL:?set HERMES_JOB_MODEL to a pinned model id (see: hermes config get model.model)}"

j() {
  hermes cron create "$@" --workdir "$REPO" \
    --provider "$HERMES_JOB_PROVIDER" --model "$HERMES_JOB_MODEL"
}

# 04:30 — the grower's daily report, and the day's FIRST weather fetch: it caches the forecast so
# every later job and question reads weather_cache instead of re-fetching. Runs inside quiet hours
# by the grower's own request (autonomy.quiet_hours_exempt_jobs in config/settings.yaml).
GROWER="${GROWER_WA:-}"
if [ -z "$GROWER" ]; then
  echo "NOTE: GROWER_WA unset - grower_daily_report will deliver to 'local' instead of a DM."
  GROWER_DEST="local"
else
  GROWER_DEST="whatsapp:${GROWER}"
fi
j "30 4 * * *" \
  "Compose and send the grower's daily report. Check for fresh cached forecasts first and reuse them; only fetch what is missing or stale, then cache. LEAD WITH SPRAY RECOMMENDATIONS: spray_status for days-of-cover-remaining, spray_options candidates with rotation reasoning, verdicts per site with best hours, PHI countdowns against expected harvest dates, and a next-window outlook beyond 24h clearly labelled as such. Then run the computed extras per the skill: mildew_risk per site, water_balance deficits (et0 from daily min/max), sulfur-burn hour counts, rain-washoff check on yesterday's sprays, GDD pace. Then weather summary - forecast per site naming borrowed stations, PLUS current conditions from each site's local Wunderground station (temp, humidity, dew point, wind, Celsius, convert F if needed) - active Restricted Entry Intervals (never the acronym in report text; write it in full, same for Pre-Harvest Interval), yesterday's work grouped by property, watch-list (frost risk in season, crew heat-stress flag above 30C, seasonal equipment gates, unverified-product nag), new properties/listings, and grants + drought/water-restriction lines from your grants_watch notepad (only changes or deadlines inside 30 days). For each OPEN grant program we plausibly qualify for, render a concrete project-idea line citing the property/block, the qualifying practice, and rough scale — that idea is cached in the grants_watch notepad by the Monday scan; do NOT recompute projects at 04:30, just read the cache. If a program is open but no project is cached, render the program line only with 'no qualifying project on the books' rather than fabricate. One message, English, decision-first, TERSE with AIR: one line per item, a blank line between every item and section, empty sections say 'no records', uncomputable ones say 'not set up' - no narration; recommendations are proposals with your lean - log them. If today is genuinely uneventful, say so in one line." \
  --name grower_daily_report --deliver "$GROWER_DEST" --skill grower-daily-report --skill weather-fetch --skill advisory --skill standing-duties

# 05:45 — gather. No delivery; this only populates weather_cache.
j "45 5 * * *" \
  "Fetch today's forecast for all three sites, walk the degrade ladder if a source is down, compute the spray-window verdict per site, and cache both. Pass tz so the window is in LOCAL time, and set age_hours from the file's publish timestamp. Name the source and its age." \
  --name weather_fetch --deliver local --skill weather-fetch

# 06:00 — the brief. Reads weather_cache via get_situation (there is no context_from).
j "0 6 * * *" \
  "Compose and send the morning brief. Spanish to the crew group, Gurmukhi for pa contacts, English to manager DMs. Lead with the spray verdict. List every block still under REI. Name the reporting station when it is not the site's own. If today is unusual, say the unusual thing even though the template has no field for it." \
  --name morning_brief --deliver "$GROUP" --skill morning-brief --skill standing-duties

# 12:00 — think again. Often correctly sends nothing.
j "0 12 * * *" \
  "Re-fetch the forecast and decide whether anyone needs to hear about it. Send only if the verdict flipped or conditions moved materially for the remaining daylight. If not: call skip_job with your reasoning, then reply exactly [SILENT]." \
  --name midday_recheck --deliver "$GROUP" --skill weather-fetch --skill standing-duties

# 17:00 — nudges, 1:1 only.
j "0 17 * * *" \
  "Check who has not logged anything today and decide who actually needs a nudge. Skip anyone on a day off, anyone who already reported, and anyone who replied ALTO. 1:1 only, staggered, never in the group. Log who you skipped and why. If nobody needs one, skip_job then [SILENT]." \
  --name eod_worker_nudge --deliver whatsapp --skill standing-duties

# 19:00 — the manager report.
j "0 19 * * *" \
  "Compose and send the end-of-day report to managers, with the email backup. Include the Hermes notes line: what you decided on your own today and why. Empty is a valid value there; padding it is not. Attach the full workbook on Fridays." \
  --name eod_manager_report --deliver whatsapp --skill eod-report --skill standing-duties

# 20:00 — frost. Seasonal; Hermes decides whether it is in season.
j "0 20 * * *" \
  "If we are inside a frost window (Mar 1-May 31, Sep 15-Nov 15), check every site's overnight minimum. Any site at or below 2 C is an immediate alert to the crew group and managers, in every worker language. Out of season, [SILENT]." \
  --name frost_watch --deliver "$GROUP" --skill weather-fetch

# 21:30 — nightly housekeeping.
j "30 21 * * *" \
  "Rebuild the nightly workbooks, run the SQLite .backup, back up the WhatsApp session directory, git-commit the skills directory, and rotate per the retention policy. Report only if something failed; otherwise [SILENT]." \
  --name nightly_export_backup --deliver local --skill exports

# every 30m — listings. Uses the job NOTEPAD for dedupe memory (there is no `continuity`).
j "every 30m" \
  "Read the listings inbox, extract and dedupe real listings, and decide whether anything is worth interrupting the owner for today rather than holding for the EOD digest. Default to the digest. Use your cron notepad to remember MLS numbers already seen across runs. Nothing new: [SILENT]." \
  --name listings_poll --deliver local --skill listings-triage

# Sun 18:00 — payroll support.
j "0 18 * * 0" \
  "Build the hours-by-worker-by-day workbook for the week and email it to managers for SAWP payroll. We run payroll through PAYWORKS - lay the workbook out for clean entry into it: one row per worker per day within the pay period, hours as decimals, pay-period dates in the header, totals per worker. Flag any day with missing or zero hours for a worker who otherwise worked." \
  --name weekly_hours_export --deliver local --skill exports

# Mon 05:00 — weekly grants + water-restriction scan. Caches state in the notepad for the daily report.
j "0 5 * * 1" \
  "Run the grants-watch scan per the skill: fetch each funding-program page (the core stack AND the aggregate hubs bciaf.ca/programs/ and bcwgc.org/funding-opportunities/, then grapegrowers.bc.ca/funding and the gov.bc.ca agriculture programs page) AND the BC Drought Information Portal for the Okanagan basin level, compare against your notepad's last-seen state, update it, and decide whether anything is worth flagging to the grower now (new openings, deadlines inside 30 days, prerequisite gaps like no current EFP, drought-level changes or new agricultural restrictions). For each OPEN program we plausibly qualify for, work out a concrete project idea HERE while you have the full operational picture (get_blocks, water_balance, fruit samples, task/spray logs) and cache the idea alongside program status in the notepad — the 04:30 daily report reads this cache and renders the project-idea line, it does NOT recompute projects at 04:30. Match qualifying practice to qualifying program; do not manufacture fit; if no qualifying project exists for an open program, cache that fact so the report renders 'no qualifying project on the books' rather than fabricates. Nothing changed: skip_job then [SILENT]." \
  --name grants_watch --deliver local --skill grants-watch

# 1st of month 07:00 — the legal one.
j "0 7 1 * *" \
  "Build compliance-YYYY-MM.xlsx including superseded rows flagged SUPERSEDED-BY and the audit sheet. Email it to managers. Then run the monthly learning review: summarize what you learned, what you were corrected on, and what you are still unsure about." \
  --name monthly_compliance_export --deliver local --skill exports --skill self-improvement

# every 15m — heartbeat. NO LLM: it must work when the provider is down.
# NOTE: --script paths resolve under ~/.hermes/scripts/, NOT the repo. bootstrap.sh copies it.
hermes cron create "every 15m" \
  --name heartbeat --deliver local --no-agent --script "heartbeat.sh"

echo
echo "Created. Verify:  hermes cron list"
echo "Jobs do NOT fire until the gateway runs:"
echo "  hermes gateway install        (or: sudo hermes gateway install --system)"
echo "  hermes cron status"

