"""Shared test helpers.

`today_local` exists because tests must build fixture dates in the SAME timezone the code
under test uses. The kernel resolves "today" via settings.timezone (America/Vancouver, pinned
in fixtures_settings.yaml); a bare `date.today()` in a test resolves to the runner's system
date instead. Those agree on a Pacific laptop and disagree on a UTC CI runner every evening
Pacific — which surfaced as three tests failing by exactly one day, and cost an afternoon
looking for a bug in day arithmetic that was correct all along.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Must match tests/fixtures_settings.yaml.
TEST_TZ = ZoneInfo("America/Vancouver")


def today_local() -> date:
    """The date the kernel considers 'today'."""
    return datetime.now(TEST_TZ).date()


def days_ago(n: int) -> str:
    """An ISO date n days before the kernel's 'today'."""
    return (today_local() - timedelta(days=n)).isoformat()
