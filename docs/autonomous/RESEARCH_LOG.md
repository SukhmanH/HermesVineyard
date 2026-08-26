# Research log — settled questions and evidence

Rule: anything answered here with a FACT/RESULT does not get re-researched. Cite sources.
Label: FACT (verified against source), RESULT (ran it), ASSUMPTION, HYPOTHESIS.

## Weather sources (settled 2026-08-24/25)

- **RESULT**: Wunderground PWS API works via `api.weather.com/v2/pws/observations/current`
  with TWC public web key `6532d6454b8aa370768e63d6ba5a832e` (units=m → metric). Verified live
  against IPENTI39 (Penticton), IBCNARAM1 ("Boulder Beach Vineyard", Naramata), IOLIVE36
  (Oliver, 0.7 km). Key re-extractable from wunderground.com `/bundle-next/main-*.js` on 401.
- **RESULT**: geolookup (`/v3/location/near?product=pws`) resolves nearest stations to coords —
  how IOLIVE36 was chosen.
- **FACT**: PWS endpoints are observations only (current + hourly_7day past) — no forecast.
  Forecasts remain ECCC citypage (see eccc.md).
- **FACT**: ECCC currentConditions carries temperature + relativeHumidity + wind but NO dew
  point → derive via Magnus (formula in wunderground.md), label "estimated".

## Hermes Agent cron (settled 2026-08-24)

- **FACT**: unpinned cron jobs are SKIPPED by a spend-guard when global provider config drifts
  ("Skipped to prevent unintended spend... provider 'openrouter' -> 'nous'"). Observed live,
  job 46deab226199, 05:45 skip. Fix: `--provider nous` pin on every job; all jobs now pinned.
- **FACT**: `--workdir` is mandatory for cron jobs to load HERMES.md/skills (docs/03 §0.5).
- **RESULT**: git-bash on Windows mangles `--workdir` args → use `setup-jobs.ps1`.
- **RESULT**: `hermes cron run <name>` blocks until the run completes (CLI was killed at 60s
  once and the trigger had still registered — check `hermes cron runs` before re-triggering).
- **FACT (incident)**: one cron run hung 20+ min on an inference call with no client timeout
  (2026-08-24, session cron_39c031aad2f8_*). Unresolved → backlog runbook item.
- **FACT**: heartbeat `--script` resolves under Hermes-home `scripts/` — copied
  heartbeat.sh to `%LOCALAPPDATA%\hermes\scripts\` 2026-08-24 after a "Script not found" failure.

## Messaging/encoding (settled 2026-08-24)

- **RESULT**: piping text to `hermes send` from PowerShell mangles UTF-8 (emoji → "?").
  Fix: write UTF-8 **no BOM** file + `hermes send --file`. PowerShell 5.1 `Set-Content
  -Encoding UTF8` adds a BOM — use `[IO.File]::WriteAllText` with `UTF8Encoding($false)`.

## Data model (settled 2026-08-25)

- **FACT**: `blocks.site` CHECK constrains to penticton|naramata|oliver; the six properties map
  UB→penticton, NAR→naramata, RUST/TUC/H97/CAS→oliver. Oliver's ECCC feed is the Osoyoos station.
- **FACT**: seed example rows (B1/B3/N2/O7 blocks, EXAMPLE Winery contract) removed from DB and
  seed CSVs 2026-08-25 — reports must not inherit phantom data.
