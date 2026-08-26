---
name: spray-log
description: Run the spray-report interview (Spanish for the crew, English for the applicator) and commit a BC-compliant pesticide application record. Use whenever a worker reports having sprayed, fumigated, or applied a product. Ends in a legal record, so the confirmation step is non-negotiable.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, compliance, spanish, english, spray]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard]
---

# Spray report to compliance record

This is the flow the whole system exists for. It ends in a record that must survive a BC audit
three years from now.

**Always 1:1, never in the group.** Group gating is per-group, not per-sender, so the group
cannot establish who is speaking, and the applicator identity is a required field.

> **The spray applicator is Punjabi-speaking but types his spray reports in English**, by his own
> choice (§D11). Run this page normally in English for him. That is the safety property the whole
> Punjabi design rests on: the one flow that ends in a legal record involves no transcription and
> no translation, and BC wants the record in English anyway.
>
> If a `pa` contact sends a **spray** report as a Punjabi voice note anyway — busy day, hands full
> — do not refuse it and do not push the raw transcript through. Load `/punjabi-intake`, confirm
> every field individually with read-back, and mention that typing it in English is more reliable
> for sprays. Then let him decide. Everything else on this page — the draft, the obligations, the
> confirmation gate, the commit — is identical either way.

## 1. Extract

Take what the worker actually said, in whichever language they said it.

From the **Spanish crew**: colloquial Mexican Spanish, often a voice-note transcript with no
punctuation and creative spelling (asufre, asufre en el 3, le di al bloque tres).

From the **applicator**: typed English, usually terse and often already well-formed. Do not
over-interrogate a report that already has everything — the fastest correct interview is zero
follow-up questions.

**Never invent a value.** Omit it and let the tool report it missing. A plausible guess that
commits is worse than a question: a wrong rate is a wrong legal record, and nobody will ever know
it was a guess.

Date defaults to today **only** if the message uses past tense of today (hice, termine, acabo de)
with no other date cue. "El martes" is a date cue. If tense is ambiguous, ask.

## 2. Draft

`draft_spray_log(wa_phone, extraction)` returns `{confirm_token, draft, missing_fields}`.

It resolves block codes fuzzily (el 3, bloque tres to B3), matches products, auto-fills the
applicator from the sender, acreage from the block, and weather from `weather_cache` at the block
site and start time. It fills REI/PHI from the product **only if `verified = 1`**; otherwise
`label_rei` comes back in `missing_fields` and you ask the applicator to read the label.

Required for a spray: product, block, rate **or** total, start/end time.

## 3. Ask, bundled, not one at a time (Spanish crew)

Ask the returned `missing_fields` as **bundled questions, 2 messages typical**. Someone with
gloves on in a row of vines is not filling in a form. Use the wording in `templates/es.yaml`.

Good, one message:

> Cuanto azufre usaste y a que hora terminaste?

Bad: six messages, six notifications, one annoyed worker.

For the applicator in English, same principle, his register: bundle, stay brief, skip what he
already told you.

You have latitude over wording, bundling, order, and register. Skip a question you can already
infer from context. Accept a rambling voice note whole. If someone answers in fragments across
three messages, merge them into the draft.

## 4. Confirm — three separate acts, and they may not be collapsed

This is obligation 1, and it is the step most easily skipped by accident.

1. `present_confirmation(confirm_token)` — tells the kernel you are about to show the card.
2. **Send the card**, verbatim from the template. Then **stop.** End your turn. Wait for the
   worker to actually reply. Do not continue in the same breath.
3. `commit_spray_log(confirm_token, worker_reply, wa_phone)` — where `worker_reply` is **their
   own affirmative words, verbatim**: «sí», «yes that's right», «ਹਾਂ» — and `wa_phone` is the
   sender's number you resolved at step 0 (`resolve_contact`). The commit is REFUSED if the
   confirmation came from a different number than the draft was opened with. That gate stops a
   forwarded card from being confirmed by someone else; if it fires, the reply did not come
   from your worker — do not retry with a different number, tell the manager.

**Never invent `worker_reply`.** It is stored on the record permanently as the worker's
signature. Writing words nobody said is falsifying a legal document, and because it is recorded
it is the kind of thing that gets found later.

If they have not replied yet, wait. If the interview is interrupted, the draft is still there
tomorrow.

## 5. Commit

- On a clear yes → commit as above. Send the acknowledgement, then post the REI warning to the
  **crew group** (NO ENTRAR: Bloque B3 hasta el jueves 14:00) and the English equivalent to
  managers.
- On anything else, treat it as a correction to the draft. Re-draft, present again, re-confirm.
  Do not argue with the worker about what they said; they are correcting you, which is exactly
  right.

Refusals and what each one means:

| Error | You did this | Do this instead |
|---|---|---|
| `not_presented` | Went straight from draft to commit | Present the card, wait for a reply |
| `no_worker_confirmation` | Passed an empty or placeholder reply | Wait for their actual words |
| `draft_not_ready` | Fields still missing | Ask for them |
| `token_already_used` | Committed twice | Stop — the record exists |

Every one of these is the gate working. Go back a step; never retry the same call.

## If the product is unverified

Do not state an REI. Ask the applicator to read the re-entry interval off the label, record their
answer as `label_rei` in the draft, and flag the product to managers for verification. A guessed
REI is the one failure in this system that injures a person rather than a record.

**"Someone read the label" is not verification.** `verify_product` requires the **PCP
registration number and the re-entry interval read off the container**, and it rejects
placeholders. If the person cannot tell you those two things, they did not read the label —
record their `label_rei` for this one application and leave the product unverified.

## If the rate looks high

A rate well above the product's label rate comes back as `rate_confirmed` in `missing_fields`
with the comparison attached. **Ask.** An over-application is a label violation and a residue
problem, and it is the kind of thing people mean to say and forget to.

If they confirm it was deliberate, pass `rate_confirmed: true` and it commits — with the
discrepancy recorded on the row, not erased.

## Weather is a required field

BC wants prevailing conditions on the record. Wind and temperature are pre-filled from the cache
when a forecast was fetched; when they are missing, **ask the worker** rather than leaving them
blank — that is what `weather_source: worker-reported` exists for.

## Drafts expire

Drafts older than 24 h expire. Send the polite Spanish note from the template rather than letting
one vanish silently. A worker who answered three questions deserves to know the fourth never
arrived.
