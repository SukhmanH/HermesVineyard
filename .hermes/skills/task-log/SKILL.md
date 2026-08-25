---
name: task-log
description: Log non-spray vineyard work such as pruning, leaf removal, shoot thinning, irrigation, mowing, wire work, and harvest. Lighter than the spray interview but the same append-only record and the same confirmation gate. Feeds the weekly payroll hours export.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, spanish, tasks, payroll]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard]
---

# Task report to task log

Same shape as `/spray-log` but lighter: no product, no REI. It is not a pesticide record,
so do not run a pesticide interview over it. Two questions is usually plenty.

## Task types

`poda` (pruning), `deshoje` (leaf removal), `desbrote` (shoot thinning), `riego` (irrigation),
`corte_pasto` (mowing), `alambre` (wire work), `cosecha` (harvest), `otro`.

## Flow

1. Extract: task type, block, hours, who worked, optional quantity (14 hileras).
2. `draft_task_log(wa_phone, extraction)` returns a confirm token and `missing_fields`.
3. Bundle the questions. Usually only hours and block are missing.
4. `present_confirmation(token)`, send the card from the template, **end your turn and wait**,
   then `commit_task_log(token, worker_reply)` with their own words. Never invent the reply —
   it is stored on the record as their signature.

## Hours are payroll

`hours_total` is **crew-hours**, not elapsed time: three people for four hours is 12, not 4. It
drives the weekly SAWP payroll export, so getting it wrong costs someone money. When a worker
reports for a crew, confirm the headcount explicitly rather than assuming they worked alone.

Record every participant in `task_workers`, not just the person who messaged.

## Watch for the REI collision

If the block was under re-entry interval during the reported window, that is an **REI near-miss**,
a safety incident rather than a data problem. Commit the record honestly, then tell the managers
the same day per `/standing-duties`. Do not quietly adjust the times to make it look clean.
