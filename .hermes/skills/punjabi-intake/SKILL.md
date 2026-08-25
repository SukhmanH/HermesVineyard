---
name: punjabi-intake
description: Full two-way Punjabi. Workers speak Punjabi voice notes and Hermes transcribes them; Hermes replies in Gurmukhi text and can speak Punjabi aloud via Google Cloud TTS (pa-IN-Chirp3-HD-Puck). Load whenever a contact has lang = pa, or when a manager asks for something that must reach a Punjabi worker.
version: 2.0.0
metadata:
  hermes:
    tags: [punjabi, voice, asr, tts, accessibility]
    category: vineyard-ops
    requires_toolsets: [code_execution, mcp-vineyard]
---

# Punjabi, both directions

Several crew members speak Punjabi, including the spray applicator. Their profile:

| | |
|---|---|
| **Speak Punjabi** | Yes — this is their working language, and voice is how they report |
| **Read Gurmukhi** | Yes — so text replies work |
| **Write Punjabi** | No — never ask them to type Punjabi |
| **Read English** | No — an English message is not a fallback, it is a dead end |

**The applicator is the exception on one path only:** he types his **spray reports in English**. See
"The spray path is English" below — it matters more than anything else on this page.

**Never send a Punjabi contact English text.** If you cannot produce Punjabi, ask a manager to
relay in person rather than sending something unreadable and assuming it landed.

## Listening: Punjabi voice notes in

The gateway transcribes inbound voice with faster-whisper. Pin **`large-v3`** — the small model is
roughly 87% WER on Punjabi versus ~55% for large, and that gap is the difference between usable
and not.

**Measured on this machine, 2026-08-22** (real Punjabi audio, `large-v3` on GPU): language
detected correctly but at only 0.51 confidence, 71% word error by exact match — yet **83%
character similarity**, and the errors were almost entirely **vowel diacritics**, not invented
words:

| said | heard |
|---|---|
| ਵਿੱਚ | ਵੀਚ |
| ਦੇ | ਦੀ |
| ਅਤੇ | ਅਤੀ |
| ਮੈਨੂੰ | ਮੇ ਨੂ |

Content words survived intact. That tells you what to distrust: **the meaning usually comes
through; the precise spelling does not.** So do not quote a worker's Punjabi back to them
verbatim as though it were exact, and never treat a transcript as a signature.

Even at its best this is rough. General Whisper is ~55% WER on Punjabi against ~5% on Spanish, and
the errors cluster on **numbers, product names, and units**. So:

- **Never commit a number you are not sure you heard.** Read it back and ask.
- **Ask one field per message.** Short utterances transcribe far better than long ones. This is
  the opposite of the bundled Spanish flow, and it is deliberate.
- Prefer questions with a small answer space. "How many hours?" survives a bad transcript because
  a number is recoverable; "tell me about the job" does not.
- If a transcript reads like nonsense, **say so plainly and ask them to repeat.** People repeat
  themselves happily when they know why. Do not silently guess and put it on a card.
- Keep the raw transcript in `media.transcript` regardless. The transcript, not the audio, is what
  the extraction saw, so it is the audit-relevant artefact.

**The Gurmukhi confirmation card is what makes this safe.** They read it. A mistranscribed «8» for
«6» is seen and corrected before anything commits. That is why rough transcription costs extra
turns here rather than producing wrong records — and it is why nobody may "streamline" the
confirmation step away.

### ⚠ Always re-transcribe with the language FORCED

**This is now a standing rule in `HERMES.md`, not something specific to this skill** — resolve
every sender with `resolve_contact` before reasoning about their message at all, found necessary
after a real deployment bug: four Punjabi voice notes in a row were auto-detected as Portuguese
and Polish, because nothing ever looked up who was speaking. Details below are Punjabi-specific;
the resolve-first rule applies to every contact regardless of language.

The gateway uses auto-detect, because the crew speaks three languages and there is no per-contact
setting upstream. **Auto-detect is not reliable for Punjabi on short clips**, and vineyard voice
notes are short. Measured here on real Punjabi audio:

| clip | mode | result |
|---|---|---|
| 3 s | auto | detected **Kannada**, confidence 0.25 |
| 3 s | forced `pa` | correct |
| 8 s | auto | `pa`, confidence 0.51 - barely |
| 8 s | forced `pa` | byte-identical to auto |

A live 3-second note was decoded as **Portuguese** and delivered that way.

Understand the failure properly: the acoustic model hears roughly the same sounds either way -
what changes is **the script it writes them in**. Punjabi rendered in Kannada is not a degraded
message, it is an unreadable one. And nothing errors; a fluent sentence in the wrong language
arrives looking like a real answer.

So for any contact whose `lang` you already know, **never let Whisper guess**:

    python tools/transcribe.py <audio path> --lang pa --json

Forcing costs nothing when auto would have been right (see the 8 s rows), so there is no reason
to skip it. The `--json` output carries `very_short`; when that is true the transcript deserves
more suspicion, not less - ask for a repeat rather than guessing at a one-word answer.

**If a transcript arrives in an unexpected language or script, that is a signal the audio was too
short or too noisy.** Do not interpret it and do not translate it. Ask them to say it again.


## The spray path is English

The spray applicator types his spray reports **in English**, by choice. This is the single most
important safety property in the Punjabi design:

- No transcription between what he reports and what is logged.
- No translation between his words and a legal record that BC wants in English anyway.
- The compliance flow does not depend on Punjabi ASR at all.

So when a `pa` contact reports a **spray**, run `/spray-log` normally in English. Everything else
he receives — REI warnings, briefs, frost alerts — is still Gurmukhi, because reading English is a
separate skill from typing a report in it, and he does not read it.

Punjabi voice notes are for **task reports** (`/task-log`), questions, and ordinary conversation.
Those are not legally binding, so a rough transcript is an annoyance rather than a hazard.

If a `pa` contact sends a **spray** report as a Punjabi voice note anyway — busy day, hands full —
do not refuse it and do not push it through the transcript. Take it, confirm every field
individually with read-back, and say plainly that typing it in English is more reliable for
sprays. Then let him decide.

## Speaking: Punjabi audio out

**Never call `text_to_speech` for a `pa` contact** — Edge TTS has no `pa-IN` voice and will fail
or come out in the wrong language.

Punjabi speech comes from Google Cloud Text-to-Speech (voice `pa-IN-Chirp3-HD-Puck`). Shell out
to it with `terminal`:

    tools/punjabi-tts/.venv/Scripts/python.exe tools/punjabi-tts/speak.py "<Gurmukhi text>"         --out <path>.wav

It prints the output path and nothing else, so pass that straight through — a bare absolute path
in a reply auto-delivers as media. Add `[[audio_as_voice]]` so it arrives as a native voice
bubble rather than a file attachment.

- **Voice goes in addition to the Gurmukhi text, never instead of it.** Text is the durable
  record of what was said; audio is the accessibility layer on top.
- **Write what will be spoken in simple, spoken Punjabi.** The voice reads your text verbatim,
  so formal or literary wording arrives as formal speech. Short everyday sentences — the register
  rule in `HERMES.md` §Language applies doubly here, because a worker hears this once and cannot
  re-read it. Sentence gaps are handled for you: speak.py inserts a breath between sentences
  automatically (`--pause N` to change the ms; default 500).
- **Symbols and emoji are handled at synthesis, not by you.** speak.py rewrites `%` → ਪ੍ਰਤੀਸ਼ਤ,
  `°`/`°C` → ਡਿਗਰੀ, `km/h` → ਕਿਲੋਮੀਟਰ ਪ੍ਰਤੀ ਘੰਟਾ, number ranges `24-48` → "24 ਤੋਂ 48", and strips
  emoji before rendering. Do not pre-convert them yourself — the templates keep compact forms for
  TEXT, and double conversion would just make noise.
- **Output is cached** by a hash of the text and voice: a repeated REI warning returns instantly.
  A novel sentence takes a second or two. Do not pass `--no-cache` to "get a fresh render" —
  there is nothing fresh to get.
- **If it fails, send the text and say so plainly.** Do not retry in a loop; a worker is waiting.
  The text alone is complete — they read Gurmukhi.
- **Never substitute a Hindi or Urdu voice.** The scripts differ and the result is unintelligible.
- **Never use `facebook/mms-tts-pan`**, even though it would "just work": it is
  CC-BY-NC, and this is a commercial operation. Same reason Open-Meteo's free tier was rejected.

## Group broadcasts are bilingual

The crew group holds Spanish and Punjabi speakers both, so safety broadcasts carry **both
languages in one message** — REI «NO ENTRAR», frost, all-clears. Never split safety information
across two group messages hoping the right people read the right one.

## If free transcription proves too rough

Watch for the signal: correction turns per report climbing, or workers giving up and telling a
manager instead. The documented upgrade is a Punjabi-capable ASR API — Sarvam (Saaras) or
ElevenLabs Scribe — called from `execute_code` on the stored audio, roughly $3–10/mo at this
volume. Key goes in `SARVAM_API_KEY`. It is a one-line change and deliberately not required.
