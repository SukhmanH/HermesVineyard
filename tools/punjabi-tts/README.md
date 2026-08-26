# Punjabi text-to-speech

Speaks Gurmukhi. Used for `pa` contacts, whose language has no free hosted voice in Edge TTS
or any local model that is both licensed for commerce and actually good. Speech now comes from
**Google Cloud Text-to-Speech**, voice `pa-IN-Chirp3-HD-Puck`.

    python speak.py --setup                          # once: verifies credentials + voice
    python speak.py "ਸਤ ਸ੍ਰੀ ਅਕਾਲ" --out brief.wav    # thereafter

Prints the output path on stdout and nothing else, so Hermes can pass it straight through — a
bare absolute path in a reply auto-delivers as media.

## Building the environment

    bash setup.sh

Creates a tiny venv (one package, `google-cloud-texttospeech`). It stays separate because
`hermes update` replaces the Hermes venv wholesale — isolation means an upgrade cannot
silently remove Punjabi speech.

## One-time setup: Google Cloud credentials

Speech is billed per character to a GCP project, so the machine needs Application Default
Credentials:

1. `gcloud auth application-default login` — with an account on the billing project
   (`psyched-coast-506220-n2`; billing must be attached, which is also how the API got enabled)
2. `python speak.py --setup` — confirms auth works and the configured voice exists

On a server, a service-account JSON via `GOOGLE_APPLICATION_CREDENTIALS` is the equivalent.
`speak.py` detects a missing-credentials failure and prints these steps itself.

## Cost

Chirp3-HD voices are free up to **1M characters/month**, then US$30 per 1M. Templated
broadcasts are cached and re-rendered never, and total crew traffic sits orders of magnitude
under the allowance — expect an actual bill of $0, but it is no longer unconditional the way
self-hosting was. Track usage at console.cloud.google.com → APIs → Text-to-Speech.

## Why this engine

| | Why not / why yes |
|---|---|
| Edge TTS | No `pa-IN` voice at all |
| Piper | Voice list has Hindi, Urdu, Bengali, Marathi — **no Punjabi** |
| Meta `mms-tts-pan` | **CC-BY-NC.** A vineyard management business is commercial use, so this is disqualified for exactly the reason Open-Meteo's free tier was (docs/01 §D3) |
| AI4Bharat IndicF5 | MIT and official Punjabi, **but replaced 2026-08-23**: novel phrases measured 47–79 s per render (fresh process each call pays full model load), quality was poor enough that the owner rejected it outright |
| **Google Cloud TTS Chirp3-HD** | ~1–2 s per render over the network, 38 `pa-IN` voices, 1M chars/month free. Chosen |

The license argument that chose IndicF5 over mms-tts-pan still holds; what changed is that the
latency and quality costs of self-hosting were judged worse than a cloud dependency whose bill
stays at zero at this scale. The full decision trail is docs/01 §D11.

## Changing the voice

The live path (the `punjabi-voice` plugin) always uses the default in `speak.py`, so changing
the voice for real means editing one line there:

    VOICE = "pa-IN-Chirp3-HD-Puck"

38 `pa-IN` voices exist (30 Chirp3-HD, 4 Wavenet, 4 Standard); preview them at
<https://console.cloud.google.com/speech/text-to-speech>. A manual run can override without
editing: `python speak.py "..." --voice pa-IN-Wavenet-A --out test.wav`.

**Both cache layers invalidate automatically.** `speak.py` keys its cache on the voice name,
and the plugin keys on speak.py's *contents* (which is where the voice lives). You do not need
to clear anything by hand.

This was wrong once already under IndicF5: caches keyed on text alone kept answering in a
voice that had been replaced. The fix is structural now — the voice *is* part of the key.

## Caching

Output is cached by a hash of (text, voice). Templated broadcasts — the REI warning, the
all-clear — are byte-identical every time, so they are synthesised once and replayed. Use
`--no-cache` to force a re-render.
