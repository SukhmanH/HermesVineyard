"""Templates: every language must be able to say every safety message.

The failure this guards against is silent. A missing `rei_alert` in pa.yaml does not raise at
2 p.m. when a block gets sprayed - it produces nothing at all, for exactly the people who needed
the warning, and nobody finds out until someone walks into a treated block.
"""

from __future__ import annotations

import pytest
import yaml

from vineyard_mcp.templates import (
    ALL_LANGS,
    SAFETY_KEYS,
    TEMPLATE_DIR,
    WORKER_KEYS,
    WORKER_LANGS,
    check,
    load,
)


@pytest.mark.parametrize("lang", ALL_LANGS)
def test_every_language_file_parses(lang):
    data = load(lang)
    assert data.get("meta", {}).get("lang") == lang


@pytest.mark.parametrize("lang", WORKER_LANGS)
def test_worker_languages_carry_every_safety_message(lang):
    keys = set(load(lang))
    missing = [k for k in SAFETY_KEYS if k not in keys]
    assert not missing, f"{lang}.yaml cannot warn about: {missing}"


@pytest.mark.parametrize("lang", WORKER_LANGS)
def test_worker_languages_can_run_a_conversation(lang):
    keys = set(load(lang))
    assert not [k for k in WORKER_KEYS if k not in keys]


def test_managers_get_the_escalations_they_act_on():
    en = load("en")
    assert "eod_report" in en
    assert "gateway_down" in en
    assert "emergency_relay" in en
    # Standing-duty flags (docs/03 §1.1) must be sayable, not improvised each time.
    for flag in ("rei_near_miss", "repeat_application", "unverified_in_use"):
        assert flag in en["flag"], flag


def test_punjabi_claims_a_voice_only_while_the_tool_backing_it_exists():
    """Edge TTS has no pa-IN voice, so Punjabi speech comes from tools/punjabi-tts (now Google
    Cloud TTS, previously IndicF5).

    `voice_ok: true` is a promise Hermes acts on: it will try to send a Punjabi worker a spoken
    reply. If the tool is ever removed or moved and this stays true, that becomes a failed or
    wrong-language message to the person least able to work around it. So the flag and the tool
    are asserted together, never separately.
    """
    from vineyard_mcp.templates import TEMPLATE_DIR

    pa = load("pa")
    assert load("es")["meta"]["voice_ok"] is True

    if pa["meta"]["voice_ok"]:
        speaker = TEMPLATE_DIR.parent / "tools" / "punjabi-tts" / "speak.py"
        assert speaker.exists(), (
            "pa.yaml claims a Punjabi voice but tools/punjabi-tts/speak.py is gone"
        )
        raw = (TEMPLATE_DIR / "pa.yaml").read_text(encoding="utf-8")
        assert "punjabi-tts" in raw, "pa.yaml must point at what actually speaks Punjabi"


def test_the_punjabi_voice_setup_stays_documented():
    """The cloud TTS path has two pieces of non-obvious knowledge: credentials come from
    Application Default Credentials (a failure that otherwise looks like a broken tool), and
    swapping the voice must invalidate both cache layers. If the write-up disappears, the next
    person re-derives both the hard way."""
    from vineyard_mcp.templates import TEMPLATE_DIR

    status = TEMPLATE_DIR.parent / "tools" / "punjabi-tts" / "STATUS.md"
    assert status.exists(), "the Punjabi TTS write-up went missing"
    body = status.read_text(encoding="utf-8")
    for marker in ("application-default", "cache"):
        assert marker in body, f"STATUS.md should still explain {marker!r}"


def test_check_flags_unreviewed_punjabi():
    """Until a Punjabi speaker signs off, this must remain a loud go-live blocker."""
    problems = check()
    pa = load("pa")
    if not pa["meta"].get("reviewed_by"):
        assert any("reviewed" in p for p in problems)
    else:
        assert not any("reviewed" in p for p in problems)


def test_check_catches_a_deleted_safety_message(tmp_path, monkeypatch):
    """Prove the guard actually fires rather than passing vacuously."""
    import vineyard_mcp.templates as T

    for lang in ALL_LANGS:
        data = yaml.safe_load((TEMPLATE_DIR / f"{lang}.yaml").read_text(encoding="utf-8"))
        if lang == "pa":
            data.pop("rei_alert")
            data["meta"]["reviewed_by"] = "someone"
        (tmp_path / f"{lang}.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )

    monkeypatch.setattr(T, "TEMPLATE_DIR", tmp_path)
    problems = T.check()
    assert any("SAFETY" in p and "rei_alert" in p for p in problems)


def test_no_placeholder_is_left_as_a_bare_todo():
    for lang in ALL_LANGS:
        raw = (TEMPLATE_DIR / f"{lang}.yaml").read_text(encoding="utf-8")
        body = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("#"))
        for marker in ("TODO", "FIXME", "XXX"):
            assert marker not in body, f"{lang}.yaml has an unfinished {marker}"
