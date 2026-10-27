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

## Skill update preference order

When a learning opportunity signals a skill update, apply the preference order below — the
first matching action wins. Do not skip to a later step if an earlier one fits.

1. **UPDATE A CURRENTLY-LOADED SKILL.** If any skill is loaded (via skill_view or was loaded
   earlier in the session) and its topic covers the new learning, patch it first. Reload it
   with skill_view during the review to get its current content before editing.

2. **UPDATE AN EXISTING UMBRELLA SKILL.** If no loaded skill fits, check skills_list for an
   existing class-level skill that covers the territory. Patch it — add a subsection, a pitfall,
   or broaden a trigger. Do not create a new skill if an existing one can be extended.

3. **ADD A SUPPORT FILE under an existing umbrella.** If the learning is better suited to a
   support file rather than SKILL.md body, add it under the relevant umbrella's directory:
   `references/<topic>.md` for topical depth (decision tables, recipes, provider quirks,
   condensed domain notes), `templates/<name>.<ext>` for starter files meant to be copied, or
   `scripts/<name>.<ext>` for statically re-runnable actions the skill can invoke directly.
   The umbrella's SKILL.md must gain a one-line pointer to any new support file.

4. **CREATE A NEW CLASS-LEVEL UMBRELLA SKILL** when no existing skill covers the class. The
   name must be at the class level — not a PR number, error string, feature codename, or
   'fix-X / debug-Y / audit-Z-today' session artifact. If the name only makes sense for
   today's task, it is wrong — fall back to (1), (2), or (3).

## Read-before-write enforcement

Before you patch or edit an existing skill's SKILL.md:

- Call `skill_view(name)` for that skill during this review to obtain current content.
- If the write is refused with a read-before-write error, call `skill_view` once for the
  named target and retry the write once. Do not loop.
- Content quoted earlier in the conversation transcript does NOT count as having read the
  skill — a fresh skill_view call is required.

New skill creation or new supporting files need no prior read. The guard exists so that SKILL.md
patches always operate on the latest loaded content, preventing stale edits.

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
