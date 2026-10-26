"""emit_listings_frost.sh: one cron job per owner passes on what listings_frost composed.

The script runs under bash against a throwaway HOME laid out like ~/.hermes/cron/output. What it
must get right: a quiet run sends nothing, a real message reaches each owner exactly once, and
neither a failed run nor a narration dump is ever passed on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hermes" / "emit_listings_frost.sh"
JOB = "dcfe2736bd46"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def transcript(home: Path, name: str, response: str | None) -> None:
    out = home / ".hermes" / "cron" / "output" / JOB
    out.mkdir(parents=True, exist_ok=True)
    body = "# Cron Job: listings_frost\n\n## Prompt\n\nRun the frost scoring.\n"
    if response is not None:
        body += f"\n## Response\n\n{response}\n"
    (out / f"{name}.md").write_text(body, encoding="utf-8", newline="\n")


def emit(home: Path, who: str) -> str:
    env = dict(os.environ, HOME=str(home), MIN_AGE_S="0")
    run = subprocess.run([BASH, SCRIPT.as_posix(), who], env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return run.stdout


MESSAGE = ("1056 Naramata Rd, Penticton, BC: frost 81, 7.5 frost-safe ac of 9.0 plantable, "
           "confidence high.\n   map: http://100.71.243.94:8000/?job=abc")


def test_a_message_reaches_each_owner_once(tmp_path):
    transcript(tmp_path, "2026-10-26_10-00-00", MESSAGE)
    assert emit(tmp_path, "sukhman").strip() == MESSAGE
    assert emit(tmp_path, "sukhman") == ""                # not again on the next tick
    assert emit(tmp_path, "harpreet").strip() == MESSAGE  # each owner has their own marker


def test_quiet_runs_send_nothing(tmp_path):
    for i, quiet in enumerate(("[SILENT]", "silent", "NO_REPLY", "Nothing new.\n\n[SILENT]")):
        transcript(tmp_path, f"2026-10-26_1{i}-00-00", quiet)
    assert emit(tmp_path, "waris") == ""
    transcript(tmp_path, "2026-10-26_15-00-00", MESSAGE)
    assert emit(tmp_path, "waris").strip() == MESSAGE


def test_failures_narration_and_unfinished_runs_are_never_passed_on(tmp_path):
    transcript(tmp_path, "2026-10-26_10-00-00", "[CRON_FAILURE]\nfrost API unreachable")
    transcript(tmp_path, "2026-10-26_11-00-00", "Let me think about each listing. " * 400)
    transcript(tmp_path, "2026-10-26_12-00-00", None)     # crashed before it answered
    assert emit(tmp_path, "baljit") == ""
    transcript(tmp_path, "2026-10-26_13-00-00", MESSAGE)
    assert emit(tmp_path, "baljit").strip() == MESSAGE


def test_after_an_outage_an_owner_gets_what_they_missed_in_order(tmp_path):
    transcript(tmp_path, "2026-10-26_10-00-00", "first listing")
    transcript(tmp_path, "2026-10-26_12-00-00", "[SILENT]")
    transcript(tmp_path, "2026-10-26_14-00-00", "second listing")
    assert emit(tmp_path, "sukhman").split("\n\n") == ["first listing", "second listing\n"]


def test_a_bad_recipient_name_is_refused(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    run = subprocess.run([BASH, SCRIPT.as_posix(), "../x"], env=env, capture_output=True,
                         text=True, timeout=60)
    assert run.returncode == 2 and run.stdout == ""
