"""Template loading and the safety-key check.

Rendering is Hermes's job — it reads these files itself. What lives here is the one thing that
must not be left to judgement: **proving that every language can express every safety message.**

A missing `rei_alert` in `pa.yaml` does not raise an error at 2 p.m. when a block is sprayed. It
produces silence for exactly the people who needed the warning, and nobody finds out until
someone walks into a treated block. So it is checked at startup instead.
"""

from __future__ import annotations

from typing import Any

import yaml

from .config import REPO_ROOT

TEMPLATE_DIR = REPO_ROOT / "templates"

WORKER_LANGS = ("es", "pa")
ALL_LANGS = ("es", "en", "pa")

# Messages that carry safety weight. Absent = a worker is not warned.
SAFETY_KEYS = ("rei_alert", "rei_allclear", "frost_alert", "weather_down", "emergency_ack")

# Messages every worker language needs to run a conversation at all.
WORKER_KEYS = ("morning_brief", "task_ask", "task_confirm", "task_ack", "correction", "help")


def load(lang: str) -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{lang}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no template file for language {lang!r} at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check() -> list[str]:
    """Return a list of problems. Empty means every language can say everything it must."""
    problems: list[str] = []

    for lang in ALL_LANGS:
        try:
            data = load(lang)
        except FileNotFoundError as exc:
            problems.append(str(exc))
            continue

        keys = set(data)
        if lang in WORKER_LANGS:
            for key in SAFETY_KEYS:
                if key not in keys:
                    problems.append(f"{lang}.yaml missing SAFETY message {key!r}")
            for key in WORKER_KEYS:
                if key not in keys:
                    problems.append(f"{lang}.yaml missing {key!r}")

        meta = data.get("meta") or {}
        if meta.get("lang") != lang:
            problems.append(f"{lang}.yaml meta.lang is {meta.get('lang')!r}, expected {lang!r}")

        # Unreviewed Punjabi is not a build error - it is a go-live blocker, surfaced loudly
        # because the person who can fix it is not the person running doctor.
        if lang == "pa" and not meta.get("reviewed_by"):
            problems.append(
                "pa.yaml has NOT been reviewed by a Punjabi speaker "
                "(meta.reviewed_by is empty) - safety wording is unverified"
            )

    return problems
