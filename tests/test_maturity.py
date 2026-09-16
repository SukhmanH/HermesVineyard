"""Fruit maturity against winery targets, and the water balance behind irrigation advice.

These projections get used for harvest calls, so the tests care most about the cases where a
number should NOT be produced: one sample, stale samples, flat or falling Brix, implausible
readings. A confident projection built on bad data is worse than no projection.
"""

from __future__ import annotations

import sqlite3

import pytest
from helpers import days_ago, today_local

from vineyard_mcp.maturity import (
    compute_et0,
    irrigation_vs_ripening,
    maturity_status,
    record_sample,
    water_balance,
)

YEAR = today_local().year


def _ago(n):
    return days_ago(n)


def _target(db, code="B3", lo=23.0, hi=25.0, **over):
    bid = db.execute("SELECT id FROM blocks WHERE code=?", (code,)).fetchone()["id"]
    db.execute(
        """INSERT INTO fruit_targets (block_id, season_year, winery, target_brix_min,
               target_brix_max, target_ta_min, target_ta_max, target_ph_min, target_ph_max,
               harvest_window_from, harvest_window_to)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (bid, YEAR, over.get("winery", "Test Winery"), lo, hi,
         over.get("ta_min", 5.0), over.get("ta_max", 8.0),
         over.get("ph_min", 3.2), over.get("ph_max", 3.6),
         over.get("wfrom", _ago(-10)), over.get("wto", _ago(-40))),
    )


# ── Recording ────────────────────────────────────────────────────────────────

def test_a_sample_is_recorded_against_a_block(db):
    out = record_sample(db, "B3", brix=21.4, ta_g_l=7.1, ph=3.35, sample_size=200)
    assert out["recorded"]["brix"] == 21.4
    assert out["block_code"] == "B3"


def test_a_sample_needs_at_least_one_measurement(db):
    assert record_sample(db, "B3", sample_size=200)["error"] == "no_measurement"


def test_an_unknown_block_is_refused(db):
    assert record_sample(db, "B99", brix=22)["error"] == "unknown_block"


@pytest.mark.parametrize("field,value", [("brix", 87), ("ph", 9.5), ("ta_g_l", 400)])
def test_implausible_readings_are_refused_not_stored(db, field, value):
    """A refractometer misread or a transcription slip would otherwise poison the ripening rate
    and every projection made from it."""
    out = record_sample(db, "B3", **{field: value})
    assert out["error"] == "implausible_value"
    assert db.execute("SELECT COUNT(*) c FROM fruit_samples").fetchone()["c"] == 0


def test_samples_are_append_only(db):
    record_sample(db, "B3", brix=21.0)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE fruit_samples SET brix = 25")


# ── Ripening rate and projection ─────────────────────────────────────────────

def test_ripening_rate_and_days_to_target(db):
    _target(db, lo=23.0)
    record_sample(db, "B3", sampled_on=_ago(7), brix=20.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_per_day"] == 0.2            # 1.4 Bx over 7 days
    assert entry["brix_gap"] == 1.6                # 23.0 - 21.4
    assert entry["projected_days_to_target"] == 8  # ceil(1.6 / 0.2)


def test_a_single_sample_yields_no_rate(db):
    """One reading is a position, not a trajectory."""
    _target(db)
    record_sample(db, "B3", brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_per_day"] is None
    assert entry["projected_days_to_target"] is None
    assert any("only one Brix sample" in n for n in entry["notes"])


def test_flat_or_falling_brix_produces_no_projection(db):
    """Dividing by a zero or negative rate projects into the past, or to infinity."""
    _target(db)
    record_sample(db, "B3", sampled_on=_ago(7), brix=21.5)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["projected_days_to_target"] is None
    assert any("not risen" in n for n in entry["notes"])


def test_same_day_retest_does_not_kill_the_projection(db):
    """A same-day re-test is a second opinion on one day, not a second point on the line.
    The rate must come from the two most recent DISTINCT-date samples instead of going
    silently null — the grower's days-to-target vanished without a note when a re-test
    was logged (delegation review, reproduced)."""
    _target(db, lo=23.0)
    record_sample(db, "B3", sampled_on=_ago(7), brix=20.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)   # same-day re-test
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_per_day"] == 0.2
    assert entry["projected_days_to_target"] == 8


def test_all_samples_on_one_date_says_why_there_is_no_rate(db):
    """The rate going null must never be silent."""
    _target(db)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_per_day"] is None
    assert any("one date" in n for n in entry["notes"])


def test_stale_samples_are_flagged(db):
    """Ripening moves fast late season, and harvest calls get made on these numbers."""
    _target(db)
    record_sample(db, "B3", sampled_on=_ago(12), brix=21.0)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["sample_stale"] is True
    assert entry["sample_age_days"] == 12


def test_small_samples_are_flagged_as_noisy(db):
    _target(db)
    record_sample(db, "B3", brix=21.4, sample_size=30)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert any("30 berries" in n for n in entry["notes"])


# ── Contract conformance ─────────────────────────────────────────────────────

def test_in_spec_reports_each_metric_separately(db):
    """Sugar alone is not ripeness. TA and pH decide the wine."""
    _target(db, lo=23.0, hi=25.0, ta_min=5.0, ta_max=8.0, ph_min=3.2, ph_max=3.6)
    record_sample(db, "B3", brix=24.0, ta_g_l=9.5, ph=3.4)
    spec = maturity_status(db, "B3")["blocks"][0]["in_spec"]
    assert spec["brix"] == "in"
    assert spec["ta_g_l"] == "above"
    assert spec["ph"] == "in"


def test_overripe_fruit_is_called_out(db):
    """Sugar cannot be taken back out of a berry."""
    _target(db, lo=23.0, hi=25.0)
    record_sample(db, "B3", brix=26.5)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_gap"] <= 0
    assert any("ABOVE the contract window" in n for n in entry["notes"])


def test_projection_landing_after_the_contract_window_is_flagged(db):
    _target(db, lo=30.0, wfrom=_ago(5), wto=_ago(-3))   # window closes in 3 days
    record_sample(db, "B3", sampled_on=_ago(10), brix=20.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.0)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert any("AFTER the contract window" in n for n in entry["notes"])


def test_contracted_blocks_nobody_sampled_are_surfaced(db):
    """The blocks most likely to be forgotten are the ones with no data at all."""
    _target(db, code="B1")
    record_sample(db, "B3", brix=21.0)
    out = maturity_status(db)
    assert [b["block_code"] for b in out["contracted_but_unsampled"]] == ["B1"]


# ── Evapotranspiration ───────────────────────────────────────────────────────

def test_et0_is_plausible_for_a_hot_okanagan_summer_day(db):
    """Sanity, not precision: a hot dry inland August day lands in single-digit mm."""
    out = compute_et0([{"date": f"{YEAR}-08-15", "tmax_c": 33, "tmin_c": 15}], latitude=49.5)
    assert 3.0 < out["et0_total_mm"] < 12.0
    assert out["method"] == "hargreaves-samani"


def test_et0_is_lower_in_winter_than_summer(db):
    summer = compute_et0([{"date": f"{YEAR}-07-01", "tmax_c": 30, "tmin_c": 14}], 49.5)
    winter = compute_et0([{"date": f"{YEAR}-01-01", "tmax_c": 4, "tmin_c": -4}], 49.5)
    assert winter["et0_total_mm"] < summer["et0_total_mm"]


def test_et0_counts_bad_days_rather_than_hiding_them(db):
    out = compute_et0(
        [{"date": f"{YEAR}-08-15", "tmax_c": 30, "tmin_c": 14},
         {"date": "nonsense", "tmax_c": 30, "tmin_c": 14},
         {"date": f"{YEAR}-08-17", "tmax_c": 10, "tmin_c": 20}],   # max below min
        latitude=49.5)
    assert out["days_used"] == 1
    assert out["days_missing"] == 2
    assert out["complete"] is False


def test_et0_never_goes_negative(db):
    out = compute_et0([{"date": f"{YEAR}-12-21", "tmax_c": -10, "tmin_c": -20}], 49.5)
    assert out["et0_total_mm"] >= 0


# ── Water balance ────────────────────────────────────────────────────────────

def test_water_balance_reports_a_deficit_in_mm(db):
    out = water_balance(db, "B3", rain_mm=5.0, et0_mm=60.0, kc=0.6)
    assert out["crop_use_mm"] == 36.0
    assert out["deficit_mm"] == 31.0


def test_no_run_time_is_offered_without_irrigation_specs(db):
    """Litres depend on soil, rooting depth and emitter spacing. Inventing a dose here would be
    inventing agronomy."""
    out = water_balance(db, "B3", rain_mm=0, et0_mm=50)
    assert out["estimated_run_hours_per_acre"] is None
    assert any("no emitter rate" in n for n in out["notes"])


def test_a_run_time_is_offered_once_the_block_records_its_system(db):
    db.execute("UPDATE blocks SET emitter_lph=4, emitters_per_vine=2, vines_per_acre=900 "
               "WHERE code='B3'")
    out = water_balance(db, "B3", rain_mm=0, et0_mm=50, kc=0.6)
    assert out["estimated_run_hours_per_acre"] > 0


def test_rain_exceeding_crop_use_is_not_a_deficit(db):
    out = water_balance(db, "B3", rain_mm=80, et0_mm=50, kc=0.6)
    assert out["deficit_mm"] < 0
    assert any("rainfall met or exceeded" in n for n in out["notes"])


# ── The cross-check ──────────────────────────────────────────────────────────

def test_irrigating_a_block_behind_target_is_flagged_as_a_tension(db):
    """The point of the whole module: water now dilutes sugar and pushes the date out."""
    _target(db, lo=23.0)
    record_sample(db, "B3", sampled_on=_ago(7), brix=20.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    bal = water_balance(db, "B3", rain_mm=0, et0_mm=60, kc=0.6)
    out = irrigation_vs_ripening(db, "B3", bal, maturity_status(db, "B3"))
    assert out["tension"] == "irrigating_may_delay_contract_ripeness"
    assert any("dilutes sugar" in c for c in out["considerations"])
    assert any("manager call" in c for c in out["considerations"])


def test_a_block_already_at_target_has_no_ripening_objection(db):
    _target(db, lo=23.0, hi=26.0)
    record_sample(db, "B3", sampled_on=_ago(7), brix=22.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=24.0)
    bal = water_balance(db, "B3", rain_mm=0, et0_mm=60, kc=0.6)
    out = irrigation_vs_ripening(db, "B3", bal, maturity_status(db, "B3"))
    assert out["tension"] == "target_met_water_freely"


def test_a_small_deficit_is_not_worth_raising(db):
    _target(db)
    record_sample(db, "B3", brix=21.0)
    bal = water_balance(db, "B3", rain_mm=30, et0_mm=55, kc=0.6)
    out = irrigation_vs_ripening(db, "B3", bal, maturity_status(db, "B3"))
    assert out["deficit_significant"] is False
    assert out["tension"] is None


def test_a_stale_brix_reading_is_surfaced_in_the_water_decision(db):
    _target(db, lo=23.0)
    record_sample(db, "B3", sampled_on=_ago(20), brix=19.0)
    record_sample(db, "B3", sampled_on=_ago(12), brix=21.0)
    bal = water_balance(db, "B3", rain_mm=0, et0_mm=60, kc=0.6)
    out = irrigation_vs_ripening(db, "B3", bal, maturity_status(db, "B3"))
    assert any("re-sample" in c for c in out["considerations"])
