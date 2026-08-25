---
name: eod-report
description: The 19:00 manager report. Work done by whom and where, sprays with REI expiries, tomorrow spray window, new listings, anomalies, and what you decided on your own today. WhatsApp primary, email backup with Excel on Fridays.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, reporting, managers, english]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard, code_execution, messaging]
---

# End-of-day manager report, 19:00

Written for two or three people who have been working outside all day. Dense, scannable, English.
Lead with anything that needs a decision.

## Assemble

Start with `get_situation`, then compose from `query_logs`, `rei_active`, new listings, and the
day's `agent.decision` rows. Never state a logged fact you did not read back from a tool.

## Sections

1. **Work done** by worker, block, hours. Anything unusual about the distribution.
2. **Sprays** committed today, with REI expiry times, and which blocks are still closed tomorrow.
3. **Tomorrow's spray window**, per site, with the verdict and best hours.
4. **New listings** worth their attention. Most belong here rather than in a same-day interrupt.
5. **Anomalies** from `/standing-duties`. Name them plainly with the block, worker, and dates.
6. **Your own decisions.** The one-line summary of what you chose to do or not do today, and why.
   Skipped the midday recheck, verdict unchanged. Nudged Miguel but not Juan, Juan logged at
   14:20. Flagged B7, second sulfur application in six days.

## Section 6 is not optional

It is the price of the latitude you have. The owner grants broad autonomy because every choice is
reconstructable, so a wrong pattern is visible within a day rather than discovered at audit. A
report that hides a judgement call is worse than one that admits an awkward one.

## Judgement

The template is a floor. If something matters and no field exists for it, say it anyway. If the
day was genuinely uneventful, say that in one line rather than padding six sections to look
thorough. Managers who learn your reports are padded will start skimming them, and then the REI
near-miss in section 5 gets skimmed too.

Anything genuinely urgent should already have been sent hours ago. If you are learning about it
here first, that is a bug in your standing duties, not a feature of the report.

## Delivery

Manager DMs in English, primary. Email backup carries attachments: full Excel workbook on
Fridays, the monthly compliance workbook on the 1st. Build the workbooks yourself with `openpyxl`
via `execute_code` and see `/exports`.
