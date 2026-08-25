---
name: correction
description: Fix an already-committed spray or task record without ever mutating it. Triggered by CORREGIR or any "me equivoque" message. Produces a superseding row and leaves the original byte-identical.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, compliance, spanish, corrections]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard]
---

# Corrections

The record is append-only. You do not edit history; you supersede it, and both rows survive for
the auditor. The database triggers enforce this even if you try otherwise, so a failed UPDATE is
the system working, not a bug to route around.

## Triggers

CORREGIR, "me equivoque", "fueron 6 kg no 8", "no fue el bloque 3 era el 4", or a worker
correcting you mid-confirmation.

## Flow

1. `find_recent_logs(wa_phone, limit)` to get their recent records.
2. Pick the target. If it is ambiguous, **ask** with a short numbered list rather than guessing.
   Correcting the wrong row creates two wrong records instead of one.
3. `draft_correction(log_id, changes)` pre-fills a new draft from the old row with the change
   applied and returns a fresh `confirm_token`.
4. Confirmation card in their language, same three-step gate as any commit:
   `present_confirmation`, send the card, wait, then commit with their reply.
5. `commit_spray_log(confirm_token)` or `commit_task_log(...)` inserts a new row with
   `corrects_log_id` set to the old id.

## Tone

A worker correcting a record is doing exactly what you want them to do. Thank them plainly and do
not make it feel like an incident report.

If corrections cluster around one field such as rates, times, or block codes, that is a signal
your *questions* are unclear, not that the worker is careless. Write the better phrasing into
`/spray-log` and see `/self-improvement`.

## What managers see

Reports and exports read the `*_current` views, so a corrected record shows the corrected value.
The **compliance export includes both rows**, with the superseded one flagged
`SUPERSEDED-BY <id>`. Do not describe a correction as a deletion to anyone: nothing was deleted,
and saying otherwise misrepresents the record.
