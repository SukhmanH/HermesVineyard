"""Re-transcribe a voice note with the language FORCED.

    python transcribe.py <audio> --lang pa

Runs on the Hermes venv, which already has faster-whisper and the CUDA libraries.

## Why this exists

The gateway transcribes inbound audio with `stt.language: ''` — auto-detect — because the crew
speaks three languages and there is no per-contact setting upstream. Auto-detect is fine for
Spanish and English. It is **not reliable for Punjabi on short clips**, and vineyard voice notes
are short.

Measured here, 2026-08-22, on real Punjabi audio:

    3 s  auto        -> detected `kn` (Kannada), confidence 0.25
    3 s  forced pa   -> correct
    8 s  auto        -> detected `pa`, confidence 0.51   (barely)
    8 s  forced pa   -> byte-identical to auto

A live 3-second note was decoded as **Portuguese** and delivered as such.

The failure mode is worse than "inaccurate". The acoustic model hears roughly the same sounds
either way — what changes is the **script it writes them in**. A Punjabi sentence rendered in
Kannada is not a degraded message, it is an unreadable one. And nothing errors: a confident
sentence in the wrong language arrives looking like a real answer.

Forcing costs nothing when auto would have been right (see the 8 s rows), so for any contact
whose language we already know from `contacts.lang`, there is no reason to let Whisper guess.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODEL = "large-v3"

# Primes the decoder toward vocabulary it otherwise mangles. Free accuracy on exactly the words
# that carry the compliance weight: block codes, product names, task verbs.
PROMPTS = {
    "es": ("Viñedo. Bloque B1 B3 N2 O7. Azufre, Kumulus, Microthiol, oídio, cenicilla. "
           "Poda, deshoje, desbrote, riego, cosecha, hileras, mochila, kg por hectárea."),
    "en": ("Vineyard. Block B1 B3 N2 O7. Sulfur, Kumulus, Microthiol, powdery mildew. "
           "Pruning, leaf removal, irrigation, harvest, rows, kg per hectare."),
    "pa": "ਬਲਾਕ, ਸਪਰੇਅ, ਗੰਧਕ, ਛਾਂਟੀ, ਪਾਣੀ, ਘੰਟੇ, ਕਤਾਰਾਂ, ਵਾਢੀ।",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio", type=Path)
    ap.add_argument("--lang", required=True,
                    help="force this language (es / en / pa). Never omit for a pa contact.")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of plain text")
    args = ap.parse_args()

    if not args.audio.exists():
        print(f"no such audio file: {args.audio}", file=sys.stderr)
        return 2

    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="auto", compute_type="auto")
    segments, info = model.transcribe(
        str(args.audio),
        language=args.lang,
        beam_size=5,
        initial_prompt=PROMPTS.get(args.lang),
        vad_filter=True,
    )
    text = " ".join(s.text for s in segments).strip()

    # Gurmukhi and accented Spanish both blow up a default cp1252 Windows console. Set this for
    # BOTH output paths, not just one.
    sys.stdout.reconfigure(encoding="utf-8")

    if args.json:
        print(json.dumps({
            "text": text,
            "language": info.language,
            "forced": args.lang,
            "duration_s": round(info.duration, 2),
            # Short audio is where auto-detect fails. Surfaced so the caller can decide to ask
            # for a repeat rather than trusting a one-word transcript.
            "very_short": info.duration < 4.0,
        }, ensure_ascii=False))
    else:
        # stdout carries the transcript ONLY, so a caller can use it directly.
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
