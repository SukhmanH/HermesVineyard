---
name: onboarding
description: Enrol a new worker or manager into the system. Consent, language, voice preference, name, role, and the one-page explanation of what Hermes does and what it will never do. Run when a manager adds someone or an unknown number is enrolled.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, onboarding, spanish, consent]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard, messaging]
---

# Onboarding a person

Enrolment is a **manager decision**, never a self-service flow. `unauthorized_dm_behavior` is set
to `ignore`, so a stranger messaging the bot starts nothing. If an unknown number messages you,
tell a manager; do not enrol them yourself.

## What you need

- `wa_phone` in E.164, `full_name`, `short_name` (how you will address them).
- `lang`: `es` for Spanish crew, `pa` for Punjabi workers (**including the applicator**), `en`
  for managers. All three are live — `pa` is not a future phase (§D11).
- For a `pa` contact, load `/punjabi-intake` before the first conversation. Their profile:
  speak Punjabi, **read** Gurmukhi, do **not** write it, do **not** read English. So never ask
  them to type Punjabi, and never send them English as a fallback.
- **Ask the applicator directly** which language he wants for briefs and alerts. He types spray
  reports in English, but typing a report and reading a frost warning are different skills — do
  not infer one from the other. Record the answer; do not assume it.
- `role`: worker, manager, or owner.
- `voice_replies`: **ask them directly.** Some people would much rather listen than read, and
  nobody volunteers that unprompted. Ask it as a normal preference question, not as an
  accessibility assessment. Available for both `es` (Edge TTS) and `pa` (Google Cloud TTS via
  `tools/punjabi-tts`).
- **Verify the literacy assumption per person, gently.** `pa` contacts are assumed to read
  Gurmukhi, and the whole confirmation-card design rests on that. Confirm it early with a real
  message rather than a quiz — send something they must act on and see whether they act.
- `consent_ts_utc`: when they first messaged you. Without it you may not message them at all.

## The first conversation, in their language

Keep it to four things:

1. **What you do.** You send the morning weather and spray window, you take their work reports,
   and you tell everyone when a block is closed after spraying.
2. **How to report.** By text or by voice note, whichever is easier. Voice is fine and it is not
   second best. They do not need a format; they can just say what they did.
3. **That you will ask follow-up questions**, because the government requires certain details on
   spray records, and that you will keep it to a couple of questions.
4. **That corrections are welcome and easy.** CORREGIR, or just tell you what was wrong. Say this
   explicitly at onboarding: a worker who thinks a mistake is permanent will hide the next one.

Also tell them: ALTO stops the non-urgent messages, and safety warnings will still come through
because those are not optional.

## What to say about privacy

Their work reports go to managers. Their mistakes and corrections stay 1:1. Safety warnings go to
the whole crew group. Say this plainly at the start rather than letting someone discover it.

## Then learn them

Over the first weeks, notice how this person actually works: voice or text, morning or evening
reporter, terse or chatty, whether they need a nudge or never do. Put it in memory. Adapting to
the person is most of what makes this tolerable to use every day.
