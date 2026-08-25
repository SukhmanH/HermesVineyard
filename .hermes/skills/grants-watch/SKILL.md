---
name: grants-watch
description: Weekly scan of BC vineyard funding programs (EFP, BMP, Enhanced Replant, CAF, water infrastructure, AgriStability) AND Okanagan drought/water-restriction notices. Load on the weekly scan, when the owner asks about funding or water restrictions, or whenever the daily report needs its grants line explained.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, grants, funding, bc, drought, water]
    category: vineyard-ops
    requires_toolsets: [code_execution]
---

# Watching for grants and water notices

The owner runs six vineyards in a capital-hungry business in a province that cost-shares exactly
the work this operation needs (irrigation efficiency, replant after freeze damage, environmental
plans). Programs open and close on intake windows; a missed window is a year lost. And in the
same valley, provincial drought levels decide how much water those vines get — restriction
notices land there first.

## The watchlist is the source of truth

**Read `references/bc-funding-watchlist.md` first** — it lists the programs and the drought/water
sources with their URLs, plus the judgement rules for reporting them. The web page you fetch at
check-time beats anything written in the reference, including its status column.

## How to run a scan

1. Fetch each watchlist URL with `execute_code` (plain HTTP GET; these are public pages).
2. Look for intake status changes: "applications open", deadlines posted, new program years.
3. Check the BC Drought Information Portal for the Okanagan basin level and any new
   agricultural restriction notices from the relevant water purveyors.
4. Compare against your **cron notepad** (`hermes cron notepad grants_watch get state`) — it
   stores last-seen status per program and the last-seen drought level, so "NEW since last scan"
   means something.
5. Write back what you saw (`... set state '{"BMP": "open-until-2026-08-31", "drought": "3"}'`).

## Cadence

Daily scans would be noise — programs move monthly, not daily. **Scan weekly (Mondays) and on
demand**; the 04:30 grower report reads your notepad's cached state and adds lines only when
something changed, a deadline is inside 30 days, or the drought level moved. If asked directly
about funding or water restrictions, scan live rather than answering from cache.

## What makes a grant worth interrupting for

- A deadline inside ~14 days for something we plausibly qualify for (ERP after a freeze event,
  BMP for irrigation work we already planned).
- A NEW program opening that matches work already on the books.
- A prerequisite gap we can close free/cheap NOW (e.g., no current EFP number while BMP money
  sits behind it). Say that plainly and once.
