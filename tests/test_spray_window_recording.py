"""A spray verdict must record itself.

The verdict maths is covered in `test_weather_math.py`; this file is about the step *after* it.

Found live 2026-08-23: asked whether B1 could be sprayed, Hermes fetched the forecast correctly
and called `compute_spray_window` correctly — then never called `cache_weather`. A correct
verdict went out with no `weather_cache` row behind it. Nothing errored, and the answer read as
authoritative, so the gap was invisible from the conversation alone.

Instructions to cache already existed in `weather-fetch/SKILL.md` and in `HERMES.md`, and did
not fire. So the tool records the verdict itself, and these tests hold it to that.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from vineyard_mcp import queries as Q
from vineyard_mcp import server


@pytest.fixture()
def tool(db, monkeypatch):
    """Point the server's `db()` at the test database and hand back the tool function."""
    monkeypatch.setattr(server, "db", lambda: db)
    fn = server.compute_spray_window
    return getattr(fn, "fn", fn)  # unwrap FastMCP's decorator if present


def calm_hours():
    """A morning that should read YES: light wind, moderate temperature, dry."""
    return [
        {"time": f"2026-08-23T{h:02d}:00-07:00", "wind_kmh": 6.0, "gust_kmh": 10.0,
         "temp_c": 18.0, "precip_prob_pct": 0.0}
        for h in range(5, 11)
    ]


def _rows(db):
    return db.execute("SELECT * FROM weather_cache ORDER BY id").fetchall()


def test_a_verdict_writes_exactly_one_row(tool, db):
    before = len(_rows(db))
    out = tool("penticton", calm_hours(), source="eccc", age_hours=0.5)

    assert out["recorded"] is True
    assert len(_rows(db)) == before + 1


def test_the_row_holds_both_the_forecast_and_the_verdict(tool, db):
    """Either half alone is useless to an auditor: the verdict without the data cannot be
    checked, the data without the verdict does not say what was decided."""
    out = tool("naramata", calm_hours(), source="eccc", age_hours=0.5)
    row = _rows(db)[-1]

    assert row["site"] == "naramata"
    assert row["source"] == "eccc"
    assert json.loads(row["payload_json"])["hourly"], "the forecast must be stored"
    assert json.loads(row["verdict_json"])["verdict"] == out["verdict"]


def test_a_NO_is_recorded_just_like_a_YES(tool, db):
    """The refusals are the ones an auditor asks about — 'why did you not spray that week?'"""
    windy = [dict(h, wind_kmh=40.0, gust_kmh=60.0) for h in calm_hours()]
    out = tool("oliver", windy, source="eccc", age_hours=0.5)

    assert out["verdict"] == "NO"
    assert out["recorded"] is True
    assert json.loads(_rows(db)[-1]["verdict_json"])["verdict"] == "NO"


def test_a_fail_safe_NO_on_stale_data_is_still_recorded(tool, db):
    """The fail-safe path must not be the one that skips the audit trail."""
    out = tool("penticton", calm_hours(), source="eccc", age_hours=48.0)

    assert out["verdict"] == "NO"
    assert out["recorded"] is True


def test_the_site_comes_back_on_the_verdict(tool, db):
    """Three sites are computed per run; an unlabelled verdict is easy to attach to the wrong
    block when they are summarized together."""
    assert tool("oliver", calm_hours(), source="eccc", age_hours=0.5)["site"] == "oliver"


def test_a_storage_failure_surfaces_but_never_swallows_the_verdict(tool, db, monkeypatch):
    """Degrade in the safe direction.

    An unrecorded verdict is still safe to act on today — it is only indefensible later. Losing
    the verdict instead would leave a crew waiting with nothing, which is worse.
    """
    def boom(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Q, "cache_weather", boom)
    out = tool("penticton", calm_hours(), source="eccc", age_hours=0.5)

    assert out["verdict"] == "YES", "the verdict must survive a storage failure"
    assert out["recorded"] is False, "and the caller must be able to see it was not recorded"
    assert "database is locked" in out["record_error"]


def test_each_site_is_recorded_separately(tool, db):
    """The morning brief computes all three; one row each, not one row for the run."""
    for site in ("penticton", "naramata", "oliver"):
        tool(site, calm_hours(), source="eccc", age_hours=0.5)

    assert [r["site"] for r in _rows(db)] == ["penticton", "naramata", "oliver"]
