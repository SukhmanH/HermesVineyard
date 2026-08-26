"""Speak Punjabi replies aloud: Gurmukhi text in, an audio file riding alongside it.

Hermes already answers Punjabi speakers in Gurmukhi. This is a thin layer on top: take that
text, run it through the Google Cloud TTS voice, and append a ``MEDIA:`` tag so the gateway
delivers the wav as a native audio message. The reply still goes out as text — the audio rides
alongside, it does not replace anything.

## Why a plugin rather than a skill instruction

Because asking did not work. Twice, instructions to shell out to a tool sat in a skill and in
HERMES.md and simply never fired — the model has to *decide* to consult them, and on a short
message there is nothing to trigger that. A plugin hook fires on every response, no decision
involved.

## Why a plugin rather than a shell hook

A shell hook *cannot* do this, and fails silently when you try. Two independent blockers in
Hermes 0.20.4, both verified by reading the source:

  * ``agent/shell_hooks.py:_parse_response`` only ever returns ``{"context": ...}`` for a
    non-blocking event. A shell hook's ``{"response_text": ...}`` is parsed, found
    uninteresting, and dropped on the floor.
  * ``agent/turn_finalizer.py`` only applies a hook result when ``isinstance(result, str)``,
    but the shell-hook bridge is typed ``Optional[Dict[str, Any]]`` and can never return a
    bare string.

There is no error in either path. ``hermes hooks doctor`` reports the hook healthy, because it
checks that the script emits valid JSON — not that the JSON would ever be applied. The hook
runs on every reply, does its work, and its output is discarded.

Worth knowing for the next person: ``_serialize_payload`` also nests everything except a fixed
set of top-level keys under ``extra``, so ``response_text`` arrives at a shell hook as
``payload["extra"]["response_text"]``, not ``payload["response_text"]``.

## Deliberately conservative

Speaks only when ALL of these hold, because the failure modes are worse than staying silent:

  * the text actually contains Gurmukhi — never guess at a language
  * it is short enough to be worth hearing (a long report is better read)
  * synthesis succeeds within a timeout

Any failure returns the text UNCHANGED. A missing voice note is a small loss; a dropped reply
because this crashed is a worker left waiting with nothing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent.parent
SPEAK = REPO / "tools" / "punjabi-tts" / "speak.py"


def _venv_python() -> Path:
    """The punjabi-tts venv interpreter — NOT the Hermes venv.

    The TTS tool lives in its own environment on purpose: `hermes update` replaces the Hermes
    venv wholesale, so isolation is what stops an upgrade from silently removing Punjabi
    speech. The venv used to hold a 2.5 GB torch stack for IndicF5; since the Google Cloud TTS
    swap it holds one small package, but the isolation property still holds.
    """
    win = REPO / "tools" / "punjabi-tts" / ".venv" / "Scripts" / "python.exe"
    return win if win.exists() else REPO / "tools" / "punjabi-tts" / ".venv" / "bin" / "python"


def _isolated_env() -> dict[str, str]:
    """The child's environment, with the parent's Python resolution stripped out.

    Running the TTS venv's interpreter is NOT enough on its own. A subprocess inherits the
    caller's environment, and the caller here is the Hermes gateway running on its own venv —
    so `PYTHONPATH` drags Hermes' `site-packages` onto the child's `sys.path` ahead of the TTS
    venv's own.

    That is not a hypothetical. Hermes ships `tokenizers 0.23.1`; the old IndicF5 venv pinned
    `0.22.2`, and synthesis worked perfectly from a shell while failing every time from the
    gateway, with an ImportError naming a version that was not even installed in the venv it
    named. Same command, same interpreter, different parent. The scrub stays even though the
    new dependency set no longer collides — it is free insurance against the next one.

    `PYTHONNOUSERSITE` additionally keeps the per-user site directory out, which is the other
    way a stray package reaches a venv it was never installed in.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env["PYTHONNOUSERSITE"] = "1"
    return env


OUT_DIR = Path(tempfile.gettempdir()) / "hermes-punjabi-voice"

# The voice identity now lives entirely inside speak.py (the VOICE constant). There are no
# reference clips any more — that was IndicF5's voice-cloning mechanism.
def _voice_fingerprint() -> str:
    """Identify the voice a render was made in, so the cache cannot outlive it.

    The plugin-side cache is keyed on text, and text alone is not enough. Change the voice in
    speak.py — which is exactly what happened on 2026-08-23, IndicF5 to Google Chirp3-HD — and
    every phrase Hermes has already spoken would keep answering in the old voice, indefinitely,
    with nothing in the output to say why. Clearing the cache by hand is not a plan anyone
    remembers at the moment it matters.

    Hashing speak.py's CONTENTS covers everything that defines the voice: it is where the
    VOICE constant lives, and any edit to the file moves the hash. mtime alone would miss an
    edit made within the same clock tick or restored from git with times preserved.
    """
    try:
        return hashlib.sha256(SPEAK.read_bytes()).hexdigest()[:20]
    except OSError:
        return "no-speak"  # synthesize() reports a missing tool properly


# Gurmukhi block. Detecting the script is exact; guessing the language is not.
GURMUKHI = range(0x0A00, 0x0A7F + 1)

# Long text is better read than heard, and synthesis time scales with length.
MAX_CHARS = 600

# Synthesis runs inline in the gateway turn, so this is a ceiling on how long one reply can be
# delayed. A fresh render is ~1-3 s (network round-trip); a cache hit is ~0 s.
SYNTH_TIMEOUT_S = 60

# A wav under this size is a truncated or failed synthesis, not speech.
MIN_WAV_BYTES = 1000


def has_gurmukhi(text: str) -> bool:
    return any(ord(ch) in GURMUKHI for ch in text)


def speakable(text: str) -> str:
    """Strip things that read badly aloud: markdown, emoji, bullets, headings.

    Filters by Unicode CATEGORY, not str.isalnum(). Gurmukhi vowel signs are combining marks
    (category Mn), and isalnum() reports False for those — an earlier version silently deleted
    them, turning ਮੌਸਮ into ਮਸਮ. Mangled input to a TTS model produces mangled speech, which is
    worse than no speech at all because it still sounds confident.
    """
    keep_punct = ".,?!:%-()"
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("•-*# ").replace("**", "").replace("__", "")
        line = "".join(
            ch for ch in line
            # L* letters, M* marks (the diacritics), N* numbers.
            if unicodedata.category(ch)[0] in ("L", "M", "N")
            or ch.isspace() or ch in keep_punct
        ).strip()
        if line:
            out.append(line)
    return " ".join(out)


def synthesize(spoken: str) -> Path | None:
    """Render ``spoken`` to a wav, reusing an identical earlier render.

    Content-addressed by hash, so a repeated phrase (a daily brief, a standard reply) costs
    nothing the second time. Returns None on any failure — callers must treat that as
    "send the text without audio".
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{spoken}|{_voice_fingerprint()}"
    out_path = OUT_DIR / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".wav")

    if out_path.exists() and out_path.stat().st_size > MIN_WAV_BYTES:
        return out_path

    try:
        subprocess.run(
            [str(_venv_python()), str(SPEAK), spoken, "--out", str(out_path)],
            capture_output=True, timeout=SYNTH_TIMEOUT_S, check=True,
            env=_isolated_env(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("punjabi-voice: synthesis exceeded %ss — sending text only", SYNTH_TIMEOUT_S)
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "punjabi-voice: synthesis failed (rc=%s): %s",
            exc.returncode, (exc.stderr or b"")[-400:].decode("utf-8", "replace"),
        )
        return None
    except OSError as exc:
        logger.warning("punjabi-voice: could not run the TTS venv: %s", exc)
        return None

    if not out_path.exists() or out_path.stat().st_size <= MIN_WAV_BYTES:
        logger.warning("punjabi-voice: synthesis produced no usable audio")
        return None
    return out_path


def transform(response_text: str) -> str | None:
    """Return the reply with an audio attachment appended, or None to leave it unchanged.

    None (not the original string) is the "no change" signal Hermes expects — returning the
    text unmodified would still mark the response as transformed and force a redundant resend.
    """
    if not response_text or not response_text.strip():
        return None
    if not has_gurmukhi(response_text):
        return None
    if len(response_text) > MAX_CHARS:
        logger.info(
            "punjabi-voice: reply is %d chars (limit %d) — better read than heard",
            len(response_text), MAX_CHARS,
        )
        return None

    spoken = speakable(response_text)
    if not spoken:
        return None

    wav = synthesize(spoken)
    if wav is None:
        return None

    # MEDIA: is the explicit contract in gateway/platforms/base.py:extract_media.
    # [[audio_as_voice]] asks for a voice bubble where the platform supports one; on WhatsApp
    # a .wav routes to mediaType "audio" either way, so it arrives playable, not as a document.
    return f"{response_text}\n\n[[audio_as_voice]]\nMEDIA:{wav}"


if __name__ == "__main__":  # manual check: python punjabi_voice.py "ਅੱਜ ਮੌਸਮ ਸਾਫ਼ ਹੈ।"
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    result = transform(sys.argv[1] if len(sys.argv) > 1 else "")
    print(result if result is not None else "(unchanged — no audio)")
