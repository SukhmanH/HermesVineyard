"""Daily weather observations: upsert semantics, validation, and season GDD rollup."""

from __future__ import annotations

from vineyard_mcp.db import migrate
from vineyard_mcp.queries import record_daily_obs
from vineyard_mcp.queries import season_gdd as gdd_season


def test_upsert_replaces_a_day(db):
    migrate(db)
    r1 = record_daily_obs(db, "oliver", "2026-07-15", tmax_c=33.0, tmin_c=18.0,
                          precip_mm=0.0, source="wunderground")
    assert r1["recorded"] is True
    r2 = record_daily_obs(db, "oliver", "2026-07-15", tmax_c=34.5, tmin_c=19.0,
                          precip_mm=0.0, source="wunderground")
    assert r2["recorded"] is True
    rows = db.execute("SELECT tmax_c, tmin_c FROM daily_obs WHERE site='oliver'").fetchall()
    assert len(rows) == 1 and tuple(rows[0]) == (34.5, 19.0)


def test_invalid_inputs_refused(db):
    migrate(db)
    assert record_daily_obs(db, "oliver", "15/07/2026", 30.0, 15.0)["error"] == "invalid_date"
    assert record_daily_obs(db, "oliver", "2026-07-15", 30.0, 31.0)["error"] == "invalid_value"
    assert record_daily_obs(db, "oliver", "2026-07-15", "hot", 15.0)["error"] == "invalid_value"


def test_season_gdd_sums_and_flags_gaps(db):
    migrate(db)
    # 5 contiguous days: GDD = sum(max(0, (tmax+tmin)/2 - 10))
    for i, (tmax, tmin) in enumerate([(30, 15), (28, 14), (26, 13), (24, 12), (22, 11)]):
        record_daily_obs(db, "oliver", f"2026-07-{10 + i:02d}", tmax, tmin)
    out = gdd_season(db, "oliver", 2026)
    expected = sum(max(0.0, (a + b) / 2 - 10.0) for a, b in
                   [(30, 15), (28, 14), (26, 13), (24, 12), (22, 11)])
    assert abs(out["gdd"] - expected) < 0.01
    assert out["complete"] is True and out["days_missing"] == 0

    # A calendar gap (skip the 18th) must show up as missing days, not silently depress.
    record_daily_obs(db, "oliver", "2026-07-20", 25.0, 12.0)
    out2 = gdd_season(db, "oliver", 2026)
    assert out2["complete"] is False and out2["days_missing"] > 0


def test_season_gdd_with_no_data(db):
    migrate(db)
    out = gdd_season(db, "penticton", 2026)
    assert out["gdd"] is None and out["complete"] is False



def test_unknown_site_is_refused(db):
    """daily_obs has no CHECK on site, so a typo would create a phantom whose observations
    never surface in any GDD total and never announce themselves."""
    migrate(db)
    out = record_daily_obs(db, "olivr", "2026-07-15", 30.0, 15.0)
    assert out["error"] == "unknown_site"
    assert db.execute("SELECT COUNT(*) FROM daily_obs").fetchone()[0] == 0


def test_site_is_case_normalised(db):
    """'Oliver' and 'oliver' are the same vineyard, not two half-populated histories."""
    migrate(db)
    assert record_daily_obs(db, "Oliver", "2026-07-15", 30.0, 15.0)["recorded"] is True
    assert record_daily_obs(db, "oliver", "2026-07-15", 31.0, 16.0)["recorded"] is True
    rows = db.execute("SELECT site, tmax_c FROM daily_obs").fetchall()
    assert [tuple(r) for r in rows] == [("oliver", 31.0)]
