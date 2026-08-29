# Windows twin of setup-jobs.sh - run THIS on Windows hosts (git-bash mangles --workdir args).
#
# FLAGS VERIFIED against the installed Hermes CLI on 2026-08-24 (see setup-jobs.sh header for
# the full story): hermes cron create <schedule> <prompt> --name X --deliver Y --workdir Z
#   --skill S --provider P. --workdir is NOT optional (jobs run blind without it - no HERMES.md).
# --provider AND --model must BOTH be pinned. The spend-guard watches the whole inference
# config: on 2026-08-29 the global MODEL drifted (poolside/laguna-s-2.1:free ->
# stepfun/step-3.7-flash:free) and grower_daily_report was skipped despite a pinned provider.
# A job pinned on only one half still counts as unpinned.
#
# Jobs do NOT fire until the gateway runs: hermes gateway status (read the text, exit code lies).

param(
    [string]$CrewGroupJid = $env:CREW_GROUP_JID,
    [string]$GrowerWa = $env:GROWER_WA,
    [string]$JobProvider = $env:HERMES_JOB_PROVIDER,
    [string]$JobModel = $env:HERMES_JOB_MODEL,
    [string]$Repo = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

# No defaults for these two on purpose. An implicit model is the bug this guard exists to
# prevent: a default silently goes stale the next time the global config moves, and the failure
# mode is a job that stops running rather than one that errors.
if (-not $JobProvider) {
    Write-Error "Set HERMES_JOB_PROVIDER (or -JobProvider). See: hermes config get model.provider"
    exit 1
}
if (-not $JobModel) {
    Write-Error "Set HERMES_JOB_MODEL (or -JobModel). See: hermes config get model.model"
    exit 1
}

if (-not $GrowerWa) {
    # Fall back to the Hermes home .env (C:\Users\<u>\AppData\Local\hermes\.env on Windows).
    $envFile = Join-Path $env:LOCALAPPDATA "hermes\.env"
    if (Test-Path $envFile) {
        $line = (Select-String -Path $envFile -Pattern '^GROWER_WA=' | Select-Object -First 1).Line
        if ($line) { $GrowerWa = ($line -split '=', 2)[1].Trim() }
    }
}

if ($CrewGroupJid) { $Group = "whatsapp:$CrewGroupJid" } else {
    Write-Host "NOTE: CREW_GROUP_JID unset - group jobs deliver to 'local'."
    $Group = "local"
}
if ($GrowerWa) { $GrowerDest = "whatsapp:$GrowerWa" } else {
    Write-Host "NOTE: GROWER_WA unset - grower_daily_report delivers to 'local'."
    $GrowerDest = "local"
}

function J {
    param([string]$Schedule, [string]$Prompt, [string]$Name, [string]$Deliver, [string[]]$Skills)
    $args = @("cron", "create", $Schedule, $Prompt, "--name", $Name, "--deliver", $Deliver,
              "--workdir", $Repo, "--provider", $JobProvider, "--model", $JobModel)
    foreach ($s in $Skills) { $args += @("--skill", $s) }
    & hermes @args
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed creating $Name"; exit 1 }
}

# 04:30 - the grower's daily report + the day's FIRST weather fetch (cached for everyone else).
J "30 4 * * *" `
  "Compose and send the grower's daily report. Check for fresh cached forecasts first and reuse them; only fetch what is missing or stale, then cache. LEAD WITH SPRAY RECOMMENDATIONS: spray_status for days-of-cover-remaining, spray_options candidates with rotation reasoning, verdicts per site with best hours, PHI countdowns against expected harvest dates, and a next-window outlook beyond 24h clearly labelled as such. Then run the computed extras per the skill: mildew_risk per site, water_balance deficits (et0 from daily min/max), sulfur-burn hour counts, rain-washoff check on yesterday's sprays, GDD pace. Then weather summary - forecast per site naming borrowed stations, PLUS current conditions from each site's local Wunderground station (temp, humidity, dew point, wind, Celsius, convert F if needed) - active Restricted Entry Intervals (never the acronym in report text; write it in full, same for Pre-Harvest Interval), yesterday's work grouped by property, watch-list (frost risk in season, crew heat-stress flag above 30C, seasonal equipment gates, unverified-product nag), new properties/listings, and grants + drought/water-restriction lines from your grants_watch notepad (only changes or deadlines inside 30 days). One message, English, decision-first, TERSE with AIR: one line per item, a blank line between every item and section, empty sections say 'no records', uncomputable ones say 'not set up' - no narration; recommendations are proposals with your lean - log them. If today is genuinely uneventful, say so in one line." `
  "grower_daily_report" $GrowerDest @("grower-daily-report", "weather-fetch", "advisory", "standing-duties")

# 05:45 - gather. No delivery; populates weather_cache for the 06:00 brief.
J "45 5 * * *" `
  "Fetch today's forecast for all three sites, walk the degrade ladder if a source is down, compute the spray-window verdict per site, and cache both. Pass tz so the window is in LOCAL time, and set age_hours from the file's publish timestamp. Name the source and its age." `
  "weather_fetch" "local" @("weather-fetch")

# 06:00 - the brief. Reads weather_cache via get_situation (there is no context_from).
J "0 6 * * *" `
  "Compose and send the morning brief. Spanish to the crew group, Gurmukhi for pa contacts, English to manager DMs. Lead with the spray verdict. List every block still under REI. Name the reporting station when it is not the site's own. If today is unusual, say the unusual thing even though the template has no field for it." `
  "morning_brief" $Group @("morning-brief", "standing-duties")

# 12:00 - think again. Often correctly sends nothing.
J "0 12 * * *" `
  "Re-fetch the forecast and decide whether anyone needs to hear about it. Send only if the verdict flipped or conditions moved materially for the remaining daylight. If not: call skip_job with your reasoning, then reply exactly [SILENT]." `
  "midday_recheck" $Group @("weather-fetch", "standing-duties")

# 17:00 - nudges, 1:1 only.
J "0 17 * * *" `
  "Check who has not logged anything today and decide who actually needs a nudge. Skip anyone on a day off, anyone who already reported, and anyone who replied ALTO. 1:1 only, staggered, never in the group. Log who you skipped and why. If nobody needs one, skip_job then [SILENT]." `
  "eod_worker_nudge" "whatsapp" @("standing-duties")

# 19:00 - the manager report.
J "0 19 * * *" `
  "Compose and send the end-of-day report to managers, with the email backup. Include the Hermes notes line: what you decided on your own today and why. Empty is a valid value there; padding it is not. Attach the full workbook on Fridays." `
  "eod_manager_report" "whatsapp" @("eod-report", "standing-duties")

# 20:00 - frost. Seasonal; Hermes decides whether it is in season.
J "0 20 * * *" `
  "If we are inside a frost window (Mar 1-May 31, Sep 15-Nov 15), check every site's overnight minimum. Any site at or below 2 C is an immediate alert to the crew group and managers, in every worker language. Out of season, [SILENT]." `
  "frost_watch" $Group @("weather-fetch")

# 21:30 - nightly housekeeping.
J "30 21 * * *" `
  "Rebuild the nightly workbooks, run the SQLite .backup, back up the WhatsApp session directory, git-commit the skills directory, and rotate per the retention policy. Report only if something failed; otherwise [SILENT]." `
  "nightly_export_backup" "local" @("exports")

# every 30m - listings. Uses the job NOTEPAD for dedupe memory (there is no `continuity`).
J "every 30m" `
  "Read the listings inbox, extract and dedupe real listings, and decide whether anything is worth interrupting the owner for today rather than holding for the EOD digest. Default to the digest. Use your cron notepad to remember MLS numbers already seen across runs. Nothing new: [SILENT]." `
  "listings_poll" "local" @("listings-triage")

# Sun 18:00 - payroll support.
J "0 18 * * 0" `
  "Build the hours-by-worker-by-day workbook for the week and email it to managers for SAWP payroll. We run payroll through PAYWORKS - lay the workbook out for clean entry into it: one row per worker per day within the pay period, hours as decimals, pay-period dates in the header, totals per worker. Flag any day with missing or zero hours for a worker who otherwise worked." `
  "weekly_hours_export" "local" @("exports")

# Mon 05:00 - weekly grants + water-restriction scan; notepad feeds the daily report.
J "0 5 * * 1" `
  "Run the grants-watch scan per the skill: fetch each funding-program page AND the BC Drought Information Portal for the Okanagan basin level, compare against your notepad's last-seen state, update it, and decide whether anything is worth flagging to the grower now (new openings, deadlines inside 30 days, prerequisite gaps like no current EFP, drought-level changes or new agricultural restrictions). Nothing changed: skip_job then [SILENT]." `
  "grants_watch" "local" @("grants-watch")

# 1st of month 07:00 - the legal one.
J "0 7 1 * *" `
  "Build compliance-YYYY-MM.xlsx including superseded rows flagged SUPERSEDED-BY and the audit sheet. Email it to managers. Then run the monthly learning review: summarize what you learned, what you were corrected on, and what you are still unsure about." `
  "monthly_compliance_export" "local" @("exports", "self-improvement")

# every 15m - heartbeat. NO LLM: it must work when the provider is down.
# NOTE: --script paths resolve under the Hermes home scripts/ dir; bootstrap copies it there.
# The .py twin, not the .sh: on Windows the runtime's bash can resolve to a WSL bash that
# cannot read C:\ paths, which is the whole reason the Python port exists.
& hermes cron create "every 15m" --name heartbeat --deliver local --no-agent --script "heartbeat.py"

Write-Host ""
Write-Host "Created. Verify:  hermes cron list"
Write-Host "Jobs do NOT fire unless the gateway is running (read the status TEXT, exit code lies):"
Write-Host "  hermes gateway status;  hermes cron status"

