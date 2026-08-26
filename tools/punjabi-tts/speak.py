"""Punjabi text-to-speech via Google Cloud Text-to-Speech.

    python speak.py "ਸਤ ਸ੍ਰੀ ਅਕਾਲ" --out brief.wav

Runs in its OWN venv, deliberately. `hermes update` replaces the Hermes venv wholesale;
keeping TTS separate means an upgrade cannot silently take Punjabi speech away. Hermes calls
this as a subprocess through the `terminal` tool rather than importing it. The venv is now
tiny (google-cloud-texttospeech only) — the 2.5 GB torch stack went out with IndicF5, which
this tool replaced on 2026-08-23 (see STATUS.md).

Why Google Cloud TTS and not the previous choices:
  * Edge TTS has no pa-IN voice at all.
  * Meta's mms-tts-pan is CC-BY-NC — disqualified for a commercial vineyard (docs/01 §D3).
  * IndicF5 was MIT but measured 47–79 s per NOVEL phrase in production (fresh process each
    call pays full model load), and quality was poor enough that the owner called it unusable.
  * Google Cloud TTS Chirp3-HD renders in ~1–2 s over the network, has 38 pa-IN voices, and
    the first 1M characters/month are free — this project's traffic stays far inside that.

Output is 24 kHz mono WAV, same as before, so nothing downstream changes.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

# The voice Hermes speaks Punjabi in. Chirp3-HD is Google's newest generation; Puck is male.
# Swap by editing this string — both cache layers key on it (see README "Changing the voice").
VOICE = "pa-IN-Chirp3-HD-Puck"
LANGUAGE = "pa-IN"
SAMPLE_RATE = 24000

# Gap inserted between sentences, in milliseconds. Spoken Punjabi at full conversational clip
# outruns a listener who does not read it fluently; the break is where comprehension happens.
PAUSE_MS = 500

_cache_client = None


def _fail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _client():
    """Build the TTS client, with a clear message when credentials are the problem.

    Auth comes from Application Default Credentials: `gcloud auth application-default login`.
    A service-account JSON via GOOGLE_APPLICATION_CREDENTIALS works identically. That failure
    is otherwise cryptic, and it is the single most likely reason this script does not work on
    a fresh machine — so it gets the same explicit treatment the old HF_TOKEN gate got.
    """
    global _cache_client
    if _cache_client is not None:
        return _cache_client

    from google.cloud import texttospeech

    try:
        _cache_client = texttospeech.TextToSpeechClient()
        return _cache_client
    except Exception as exc:
        text = str(exc)
        if any(
            marker in text.lower()
            for marker in ("credentials", "adc", "could not automatically", "application_default")
        ):
            _fail(
                "Google Cloud TTS could not authenticate.\n"
                "One-time setup:\n"
                "  1. gcloud auth application-default login\n"
                f"     (as an account on the billing project; see {HERE / 'README.md'})\n"
                "  2. Re-run this command.\n"
                "\nUnderlying error: " + text[:200],
                code=2,
            )
            raise  # unreachable; _fail exits
        raise


def _to_spoken(text: str) -> str:
    """Rewrite symbols into the Punjabi words they should sound like.

    The voice reads Latin symbols the English way - '%' comes out as 'percent', '°' as
    'degrees', 'km/h' as English letters - which is noise to someone who does not speak
    English. Templates keep the compact forms for TEXT; this is where speech gets the words.
    """
    import re

    # 24-48 / 24 - 48 -> "24 ਤੋਂ 48". A bare hyphen between numbers is read as one glued
    # number ("200400 hours") - the dash must become the spoken word for "to".
    text = re.sub(r"(\d(?:[\d.,]*\d)?)\s*[-–—]\s*(\d(?:[\d.,]*\d)?)", r"\1 ਤੋਂ \2", text)
    # 40% / 40 % -> "40 ਪ੍ਰਤੀਸ਼ਤ"; a stray % still becomes the word, never English
    text = re.sub(r"(\d(?:[\d.,]*\d)?)\s*%", r"\1 ਪ੍ਰਤੀਸ਼ਤ", text)
    text = text.replace("%", " ਪ੍ਰਤੀਸ਼ਤ")
    # 20°C / 20° -> "20 ਡਿਗਰੀ"
    text = re.sub(r"(\d(?:[\d.,]*\d)?)\s*°\s*[CFcf]?", r"\1 ਡਿਗਰੀ", text)
    text = text.replace("°", " ਡਿਗਰੀ")
    # km/h (any case) -> the full phrase
    text = re.sub(r"\bkm\s*/\s*h\b", "ਕਿਲੋਮੀਟਰ ਪ੍ਰਤੀ ਘੰਟਾ", text, flags=re.IGNORECASE)
    return text


# Keep punctuation that shapes speech: sentence ends, commas, brackets. Everything else that
# is not a letter, a digit, or Gurmukhi gets dropped - emoji, variation selectors, ZWJ, arrows.
_KEEP_PUNCT = ".,!?%()-():;'\"।"

# Bumped whenever _to_spoken/_strip_unspeakables change behaviour, so caches keyed on the RAW
# input can never serve audio rendered under the old rules.
PREP_VERSION = 1


def _strip_unspeakables(text: str) -> str:
    """Remove everything a TTS voice would speak aloud but should not.

    The plugin strips emoji on its path, but Hermes also calls this tool directly with raw
    template text, and multi-codepoint emoji survive naive category filters anyway: 🌧️ is base
    symbol + U+FE0F, whose category is Mn - the same category as the Gurmukhi vowel signs we
    must NOT delete. So the allowlist is explicit: letters and digits of any script, combining
    marks only inside the Gurmukhi block, whitespace, and known punctuation.
    """
    import unicodedata

    out = []
    for ch in text:
        if ch in _KEEP_PUNCT or ch.isspace():
            out.append(ch)
            continue
        cat = unicodedata.category(ch)[0]
        if cat in ("L", "N"):
            out.append(ch)
        elif 0x0A00 <= ord(ch) <= 0x0A7F:
            out.append(ch)  # Gurmukhi block incl. vowel signs (Mn) - the ਮੌਸਮ guard
    return "".join(out)


def _prepare(text: str) -> str:
    """Everything that turns incoming text into what should actually be voiced."""
    cleaned = _strip_unspeakables(_to_spoken(text))
    # collapse runs of blanks left by removals, and trim around the common joins
    return " ".join(cleaned.split())


def _to_ssml(text: str, pause_ms: int) -> str | None:
    """Wrap the text in SSML with a breath between sentences.

    Chirp3-HD reads sentence runs at full conversational clip; a crew member parsing spoken
    Punjabi needs the gaps. Splitting on sentence punctuation (Gurmukhi danda included) and
    inserting <break> between parts is the one SSML feature we need — deliberately nothing
    fancier, because every extra tag is another compatibility risk on these voices.

    Returns None when there is nothing to space out (single sentence) or no split points, so
    the caller sends plain text instead.
    """
    import re

    parts = [p.strip() for p in re.split(r"[।.!?\n]+", text) if p.strip()]
    if len(parts) < 2:
        return None

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    brk = f'<break time="{pause_ms}ms"/>'
    return "<speak>" + f" {brk} ".join(esc(p) for p in parts) + "</speak>"


def synthesize(text: str, out: Path, voice_name: str = VOICE,
               use_cache: bool = True, pause_ms: int = PAUSE_MS) -> Path:
    """Render `text` to a 24 kHz WAV.

    Text is prepared first (symbols -> Punjabi words, ranges spoken, emoji stripped), and the
    cache is keyed on the PREPARED text plus PREP_VERSION - so identical prepared inputs share
    renders, and a future rule change cannot serve audio made under the old ones. Templated
    broadcasts - the REI warning, the all-clear - are byte-identical every time; a cache hit is
    instant where a fresh call takes seconds.
    """
    from google.cloud import texttospeech as tts

    text = _prepare(text)
    if not text.strip():
        _fail("nothing speakable left after cleaning (was it all emoji/symbols?)", code=6)

    key = hashlib.sha256(
        f"v{PREP_VERSION}|{text}|{voice_name}|{LANGUAGE}|{SAMPLE_RATE}|{pause_ms}".encode()
    ).hexdigest()[:20]
    cached = CACHE / f"{key}.wav"

    out.parent.mkdir(parents=True, exist_ok=True)

    if use_cache and cached.exists():
        out.write_bytes(cached.read_bytes())
        print("[gcloud-tts] cache hit", file=sys.stderr)
        return out

    client = _client()
    ssml = _to_ssml(text, pause_ms)
    try:
        response = client.synthesize_speech(
            input=(tts.SynthesisInput(ssml=ssml) if ssml else tts.SynthesisInput(text=text)),
            voice=tts.VoiceSelectionParams(language_code=LANGUAGE, name=voice_name),
            audio_config=tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16,
                sample_rate_hertz=SAMPLE_RATE,
            ),
        )
    except Exception:
        # SSML support varies by voice family. A rejected <speak> must degrade to plain text,
        # never kill the reply - the pauses are a nicety, the words are the message.
        if not ssml:
            raise
        print("[gcloud-tts] SSML rejected - falling back to plain text", file=sys.stderr)
        response = client.synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=LANGUAGE, name=voice_name),
            audio_config=tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16,
                sample_rate_hertz=SAMPLE_RATE,
            ),
        )
    audio = response.audio_content
    if not audio or len(audio) < 1000:
        _fail("Google returned no usable audio for this text.", code=4)

    CACHE.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    if use_cache:
        cached.write_bytes(audio)
    return out


def setup() -> int:
    """Verify credentials and API access. No model to download any more."""
    voices = _client().list_voices(language_code=LANGUAGE)
    names = [v.name for v in voices.voices]
    if VOICE not in names:
        _fail(
            f"Configured voice {VOICE} is not in the {LANGUAGE} voice list.\n"
            f"Available: {', '.join(sorted(names))}",
            code=5,
        )
    print(f"credentials OK; {len(names)} {LANGUAGE} voices visible; {VOICE} available.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text", nargs="?", help="Gurmukhi text to speak")
    ap.add_argument("--out", type=Path, help="output .wav path")
    ap.add_argument("--voice", default=VOICE, help="override the configured voice name")
    ap.add_argument("--pause", type=int, default=PAUSE_MS,
                    help="gap between sentences in ms (0 disables SSML breaks)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--setup", action="store_true",
                    help="one-time: verify Google Cloud credentials and voice access")
    args = ap.parse_args()

    if args.setup:
        return setup()
    if not args.text or not args.text.strip():
        _fail("nothing to say (or pass --setup)")
    if not args.out:
        _fail("--out is required")

    path = synthesize(args.text.strip(), args.out, voice_name=args.voice,
                      use_cache=not args.no_cache, pause_ms=max(0, args.pause))
    # stdout is the file path ONLY, so Hermes can use it directly: a bare absolute path in a
    # response auto-delivers as media.
    print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
