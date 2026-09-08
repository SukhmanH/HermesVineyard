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

## What the daily report reads from your notepad

The 04:30 grower report includes a project-idea line under each open program we plausibly
qualify for. That idea has to be **cached with the program state**, not recomputed each
morning — recomputing each morning means re-reading blocks and water balance at 04:30,
which is the wrong shape for a 2-minute report.

So when you write notepad state, do the project-idea work HERE on the Monday scan, while
you already have the full operational picture:

- For each OPEN program, walk the operation: `get_blocks`, `water_balance` (which blocks
  have real ET deficit → irrigation-efficiency BMP), fruit samples (any quality angle →
  CAF nitrogen/cover cropping), task log (any replant, soil work, or improvement task
  recently logged → ERP, BMP), spray log (food-safety / traceability angle).
- Match qualifying practice to qualifying program. Don't manufacture fit.
- Cache the result in the notepad alongside the program status, e.g.:

      {
        "BMP": {
          "status": "open-until-2026-08-31",
          "stream": "Extreme Weather",
          "cost_share": "50%",
          "project": {
            "block": "B5 Naramata",
            "acres": 3.2,
            "practice": "drip retrofit",
            "est_cost_cad": 8000,
            "est_share_cad": 4000,
            "qualifies_because": "irrigation efficiency BMP, current deficit 22 mm/week on B5"
          }
        },
        "drought": "3"
      }

- The daily report renders `{grant_lines}` from this cache. If a program is open but no
  project idea is cached, render the program line only and say "no qualifying project on
  the books" rather than fabricate one. Re-scan if you need a fresh project idea.

Cadence is weekly, but project-idea work is heavier than status checks — keep the
Monday scan honest about that cost.

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
