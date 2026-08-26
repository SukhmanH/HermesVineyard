"""The Punjabi voice layer: when a reply gets spoken, and when it must not be touched.

Synthesis itself is stubbed — these tests are about the decision to speak and the shape of the
returned string, both of which have already broken silently once each:

  * an ``isalnum()`` filter deleted Gurmukhi combining marks, turning ਮੌਸਮ into ਮਸਮ and feeding
    the TTS a mangled word it pronounced confidently;
  * the whole layer ran as a shell hook whose return value Hermes discards, so every reply was
    synthesized and then thrown away with no error anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hermes" / "voice"))

import punjabi_voice as pv  # noqa: E402

GURMUKHI_REPLY = "ਅੱਜ ਮੌਸਮ ਸਾਫ਼ ਹੈ। 22 ਡਿਗਰੀ।"


@pytest.fixture
def fake_wav(tmp_path, monkeypatch):
    """Stub synthesis so the tests stay fast and offline."""
    wav = tmp_path / "spoken.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 2000)
    monkeypatch.setattr(pv, "synthesize", lambda spoken: wav)
    return wav


def test_gurmukhi_reply_gets_audio_appended(fake_wav):
    out = pv.transform(GURMUKHI_REPLY)
    assert out is not None
    assert out.startswith(GURMUKHI_REPLY), "the original reply must survive verbatim"
    assert f"MEDIA:{fake_wav}" in out
    assert "[[audio_as_voice]]" in out


def test_english_reply_is_left_alone(fake_wav):
    """Never guess at language: no Gurmukhi, no audio."""
    assert pv.transform("Spray window is clear tomorrow 6-9am.") is None


def test_unchanged_replies_return_none_not_the_original(fake_wav):
    """None is the 'no change' signal.

    Returning the original string would still flag the response as transformed and force the
    gateway into a redundant resend.
    """
    assert pv.transform("plain english") is None
    assert pv.transform("") is None
    assert pv.transform("   ") is None


def test_a_long_report_is_left_to_be_read(fake_wav):
    long_reply = "ਮੌਸਮ " * 200
    assert len(long_reply) > pv.MAX_CHARS
    assert pv.transform(long_reply) is None


def test_synthesis_failure_costs_the_audio_not_the_message(monkeypatch):
    """A TTS failure must never swallow the reply — text-only is the correct degradation."""
    monkeypatch.setattr(pv, "synthesize", lambda spoken: None)
    assert pv.transform(GURMUKHI_REPLY) is None


def test_speakable_preserves_gurmukhi_vowel_signs():
    """The regression that produced confident gibberish.

    ਮੌਸਮ carries U+0A4C (category Mn). str.isalnum() is False for combining marks, so an
    alnum-based filter silently drops them and the model speaks a different word.
    """
    assert "ਮੌਸਮ" in pv.speakable("**ਮੌਸਮ** ਸਾਫ਼ ਹੈ")


def test_speakable_strips_markdown_and_emoji_but_keeps_words():
    spoken = pv.speakable("- **ਧੁੱਪ**, 29 ਡਿਗਰੀ ☀️\n# ਸਿਰਲੇਖ")
    assert "☀" not in spoken and "*" not in spoken and "#" not in spoken
    assert "ਧੁੱਪ" in spoken and "ਸਿਰਲੇਖ" in spoken
    assert "29" in spoken, "numbers carry the actual content — never strip them"


def test_has_gurmukhi_ignores_other_indic_scripts():
    """Devanagari and Gujarati sit next to Gurmukhi in the Unicode table; only ours counts."""
    assert pv.has_gurmukhi("ਸਤ ਸ੍ਰੀ ਅਕਾਲ")
    assert not pv.has_gurmukhi("नमस्ते")       # Devanagari
    assert not pv.has_gurmukhi("નમસ્તે")       # Gujarati
    assert not pv.has_gurmukhi("hello")


def test_identical_text_reuses_one_render(tmp_path, monkeypatch):
    """Content-addressed cache: a repeated daily brief must not re-synthesize."""
    calls = []
    monkeypatch.setattr(pv, "OUT_DIR", tmp_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[cmd.index("--out") + 1]).write_bytes(b"RIFF" + b"\0" * 2000)
        return None

    monkeypatch.setattr(pv.subprocess, "run", fake_run)

    first = pv.synthesize("ਮੌਸਮ ਸਾਫ਼")
    second = pv.synthesize("ਮੌਸਮ ਸਾਫ਼")
    assert first == second
    assert len(calls) == 1, "second call must hit the cache"


def test_the_tts_venv_is_isolated_from_the_parent_interpreter(monkeypatch):
    """Running the venv's python is not enough — the environment has to be scrubbed too.

    Live failure 2026-08-23: synthesis worked from a shell and failed every time from the
    gateway. The gateway runs on the Hermes venv, which ships `tokenizers 0.23.1`; the TTS venv
    pinned `0.22.2` because `transformers` requires `<=0.23.0`. Inherited `PYTHONPATH` put Hermes'
    site-packages ahead of the venv's own, and `transformers` raised an ImportError naming a
    version that was not installed in the venv it named.
    """
    monkeypatch.setenv("PYTHONPATH", r"C:\somewhere\else\site-packages")
    monkeypatch.setenv("VIRTUAL_ENV", r"C:\some\other\venv")
    monkeypatch.setenv("PYTHONHOME", r"C:\a\third\python")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "keep-me")  # unrelated vars must survive

    env = pv._isolated_env()

    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    assert "PYTHONHOME" not in env
    assert env["PYTHONNOUSERSITE"] == "1", "the user site directory is the other leak path"
    assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "keep-me", (
        "credentials must survive the scrub or every render would fail"
    )


def test_synthesis_is_spawned_with_the_scrubbed_environment(tmp_path, monkeypatch):
    """The scrubbing is worthless if `synthesize` forgets to pass it."""
    monkeypatch.setattr(pv, "OUT_DIR", tmp_path)
    monkeypatch.setenv("PYTHONPATH", r"C:\leaky\site-packages")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        Path(cmd[cmd.index("--out") + 1]).write_bytes(b"RIFF" + b"\0" * 2000)
        return None

    monkeypatch.setattr(pv.subprocess, "run", fake_run)
    pv.synthesize("ਮੌਸਮ")

    assert "env" in seen, "the subprocess must be given an explicit environment"
    assert "PYTHONPATH" not in seen["env"]


def test_changing_the_voice_invalidates_the_cache(tmp_path, monkeypatch):
    """A new voice must produce new renders, not the old voice from cache.

    The voice lives in speak.py (the VOICE constant). This bit once already: under IndicF5 the
    caches keyed on text alone, so replacing the reference clip kept every phrase already
    spoken answering in the old voice forever. Now speak.py's *contents* are part of the
    plugin-side key and the voice name is part of speak.py's own key — editing either layer
    invalidates both.
    """
    monkeypatch.setattr(pv, "OUT_DIR", tmp_path / "out")
    speak = tmp_path / "speak.py"
    speak.write_bytes(b"VOICE = 'pa-IN-Chirp3-HD-Puck'")
    monkeypatch.setattr(pv, "SPEAK", speak)

    rendered = []

    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("--out") + 1])
        out.write_bytes(b"RIFF" + b"\0" * 2000)
        rendered.append(out)
        return None

    monkeypatch.setattr(pv.subprocess, "run", fake_run)

    first = pv.synthesize("ਮੌਸਮ ਸਾਫ਼")
    assert len(rendered) == 1
    assert pv.synthesize("ਮੌਸਮ ਸਾਫ਼") == first
    assert len(rendered) == 1, "same voice, same text — must hit the cache"

    speak.write_bytes(b"VOICE = 'pa-IN-Wavenet-A'")
    second = pv.synthesize("ਮੌਸਮ ਸਾਫ਼")

    assert second != first, "a changed voice must not reuse the old render"
    assert len(rendered) == 2


def test_a_missing_speak_py_does_not_crash_the_fingerprint(tmp_path, monkeypatch):
    """synthesize() reports a missing tool with a real explanation; this must not pre-empt it."""
    monkeypatch.setattr(pv, "SPEAK", tmp_path / "absent.py")
    assert pv._voice_fingerprint() == "no-speak"  # returns something usable rather than raising


def test_a_truncated_wav_is_rejected(tmp_path, monkeypatch):
    """A near-empty file means synthesis failed; delivering it would send silence."""
    monkeypatch.setattr(pv, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        pv.subprocess, "run",
        lambda cmd, **kw: Path(cmd[cmd.index("--out") + 1]).write_bytes(b"RIFF"),
    )
    assert pv.synthesize("ਮੌਸਮ") is None
