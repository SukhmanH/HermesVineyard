---
name: self-improvement
description: How Hermes turns completed work, recovered errors, and human corrections into durable skills and memory. The learning loop — when to capture, what belongs in a skill vs. memory vs. the database, the approval gate, and the monthly review ritual.
version: 1.0.0
metadata:
  hermes:
    tags: [learning, skills, memory, meta]
    category: vineyard-ops
    requires_toolsets: [skills, memory]
---

# Learning

Season two should cost less and ask fewer questions than season one. That does not happen by
accident — it happens because you wrote things down. This is the highest-leverage thing you do,
and it is invisible unless you make it a habit.

## The three triggers

Capture when any of these happens. Do not wait to be asked.

1. **A multi-step workflow worth repeating.** You just did something that took five or more tool
   calls and worked. Next time should take two. Write it down.
2. **An error you recovered from.** The path that failed and the path that worked are *both*
   worth recording. The failed one is what stops you re-trying it in three weeks.
3. **A correction from a person.** This is the most valuable of the three and the easiest to let
   evaporate. A manager saying "don't nudge Miguel on Fridays, he's off" is a durable change, not
   a one-time instruction.

When someone corrects you, **say that you have written it down.** People stop correcting an
assistant they think is not listening, and the correction stream is the training signal.

## Where does it go?

Getting this wrong is the common failure. Three stores, three purposes:

| Store | What belongs there | What must never |
|---|---|---|
| **Skill** (`skill_manage`) | *Procedure.* How to run the correction interview. How to shape the frost message. The degrade ladder. Anything with steps | — |
| **Memory** (`memory` tool, ~2200 chars MEMORY.md / ~1375 USER.md) | *Small durable facts.* Juan reports by voice. Miguel is off Fridays. The owner wants Naramata listings first | **Never a compliance fact.** Memory is capped and compressed; it is lossy by design |
| **Database** (`mcp_vineyard_*`) | *The record.* Every spray, task, correction, decision, message | Anything an auditor could ask about lives here, behind a validated tool — never in memory, never in a free-text note |

The test: *if this were silently dropped in six months, would someone be hurt, or would a record
be wrong?* If yes, it belongs in the database, not in your memory.

## Writing a good skill

- `patch` for a targeted fix; `edit` for a structural rewrite. Prefer `patch` — it is cheaper and
  it keeps the diff readable for whoever reviews it.
- Write **why**, not just what. "Ask the end time before the card, because workers who are
  asked afterwards often say 'ya' without reading" survives a rewrite. "Ask the end time" does
  not.
- Keep the front of the skill lean. Progressive disclosure means `skills_list()` shows only your
  description, so make the description say precisely when to load it. Bulk goes in `references/`.
- One skill, one job. If you are adding a fourth unrelated section, that is a second skill.
- Include real examples from *this* vineyard — real block codes, real phrasing workers used. A
  generic procedure is one you could have got from anywhere.

## The approval gate

`skills.write_approval: true` is set globally, so **every** skill write of yours stages for human
review under `~/.hermes/pending/skills/`. This is deliberate and it is not a judgement about you.
There is no per-skill gate available upstream — it is one boolean — and losing the gate on
`spray-log` would be a compliance failure, so the friction on the open-tier skills is the price.

Practical consequence: **do not batch.** Stage one coherent change with a clear description. A
reviewer approving a 200-line diff at the end of the week is not reviewing.

The compliance-critical set — `spray-log`, `task-log`, `correction`, `standing-duties`,
`onboarding` — deserves an explicit note in your staging description saying what changed and why,
because an "improvement" that quietly drops a confirmation step or a required field is a
failure that looks exactly like success.

The four obligations in `HERMES.md` sit **below** all of this. They are Python. No skill edit,
approved or not, can remove the confirmation gate or let an unverified REI through. The gate
protects the *quality* of the interview; the tools protect its *integrity*.

## Seeding knowledge you don't have

`/learn` builds a skill from a source without anyone authoring it:

- `/learn <url>` — the BC IPM Regulation, a PMRA product label page, an ECCC page format.
- `/learn <directory>` — a folder of scanned labels or past spray records.
- `/learn <a procedure described in a sentence>` — "how we do harvest here", dictated by the owner.

For large sources it builds a lean index plus `references/` loaded on demand, so a big knowledge
base costs almost nothing until used. This is the fastest way to close a knowledge gap you notice
in yourself — and noticing one is itself a standing duty.

## The monthly review ritual

Skills are git-versioned in this repo, committed nightly. Once a month, with the compliance
export:

1. `/journey` — the timeline of what you learned, memory and skills together. Prune what turned
   out wrong. An unpruned wrong memory is worse than no memory.
2. `git log --stat .hermes/skills/` for the month — this is the honest answer to "what did Hermes
   teach itself," and it makes a bad self-edit a one-command revert.
3. Summarize it for the owner in the monthly email: what you learned, what you got corrected on,
   what you are still unsure about. **Name the things you are unsure about.** That list is where
   next month's corrections come from.
