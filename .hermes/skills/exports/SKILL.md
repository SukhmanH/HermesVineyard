---
name: exports
description: How to build every export this operation produces — nightly workbooks + backups, the weekly Payworks-ready hours sheet, and the monthly compliance workbook. Load when any exports/backup job runs or when a manager asks for a spreadsheet of anything.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, exports, excel, backup, payroll, payworks]
    category: vineyard-ops
    requires_toolsets: [code_execution]
---

# Exports and backups

## Nightly (21:30 job — `nightly_export_backup`)

Run the engine; it is deterministic and needs no judgement:

    python tools/build_exports.py

It rebuilds `spray_log.xlsx` / `task_log.xlsx` from the append-only kernel (current views —
corrected rows superseded, never deleted), runs an online SQLite `.backup`, snapshots the
WhatsApp session dir, and rotates per the retention windows at the top of the file
(14 nightly workbook archives / 14 DB backups / 7 session snapshots).

Your job on top of the script: **verify it actually ran.** Read its output; confirm today's
files exist in `data/exports/` and `data/backups/`. A backup job that silently did nothing is
worse than no backup job, because it is trusted. Report only failures; otherwise `[SILENT]`.
If openpyxl is missing, `pip install openpyxl` into the runtime env and note it.

## Weekly hours for payroll (Sun 18:00 — `weekly_hours_export`)

Payroll runs through **Payworks**. The workbook exists to be typed (or imported) into it, so
lay it out for clean entry:

- One row per worker per day within the pay period; columns: date, worker name, property,
  task, hours (decimal, not H:MM), notes.
- Pay-period dates in the header. BC SAWP crews are typically paid per the pay period the
  manager set in Payworks — use the dates from `query_logs`, never guess the period.
- Per-worker totals row. Flag (do not silently fill) any worker-day with missing or zero hours
  when the worker otherwise worked that week — that gap is a question for the manager, not a
  number you invent.
- Hours come from `task_log` only (CREW-hours are already per-worker in `task_workers`; a
  3-person × 4 h day is 4 h per worker, not 12). Cross-check totals against `task_cadence`.

Email to managers; attach, don't paste tables.

## Monthly compliance workbook (1st, 07:00 — `monthly_compliance_export`)

`spray_log` for the month with: every column of the record, superseded rows flagged
`SUPERSEDED-BY <id>` in a visible column (an auditor must see the correction trail, not just
the current view), plus an `audit_log` sheet for the month. Retain forever — BC expects
pesticide records available for at least three years, and this file is the record.

## Rules that apply to every export

- Exports are READ-ONLY views of the kernel. Never write back to the DB from an export script.
- Name files `compliance-YYYY-MM.xlsx`, `hours-YYYY-Www.xlsx`, nightly workbooks dated —
  a file whose name doesn't say what period it covers will be trusted wrongly.
- If the data is incomplete, export it anyway with the gaps marked; a missing column gets
  questioned, a silently-empty column gets trusted.
