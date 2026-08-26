"""Contract targets set by message, and sample corrections.

The validation here matters more than it looks. A Brix target typed as 2.3 instead of 23 does
not error anywhere downstream — it silently reports every block as ripe, and nobody notices
until harvest.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from vineyard_mcp.maturity import (
    correct_sample,
    get_fruit_targets,
    maturity_status,
    record_sample,
    set_fruit_target,
)

YEAR = date.today().year


def _ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ── Setting a target by message ──────────────────────────────────────────────

def test_a_manager_can_set_a_target_by_message(db):
    out = set_fruit_target(
        db, "B3", "Okanagan Crush Pad",
        target_brix_min=23.0, target_brix_max=25.0,
        harvest_window_from=f"{YEAR}-09-25", harvest_window_to=f"{YEAR}-10-15",
        set_by="manager:+12505550004",
    )
    assert out["created"] is True
    assert out["target"]["target_brix_min"] == 23.0
    assert out["target"]["winery"] == "Okanagan Crush Pad"


def test_the_target_immediately_drives_maturity_reporting(db):
    """The point of setting it by message: it works straight away, no CSV round-trip."""
    set_fruit_target(db, "B3", "Test Winery", target_brix_min=23.0, target_brix_max=25.0)
    record_sample(db, "B3", sampled_on=_ago(7), brix=20.0)
    record_sample(db, "B3", sampled_on=_ago(0), brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix_gap"] == 1.6
    assert entry["projected_days_to_target"] == 8


def test_changes_are_audited_with_before_and_after(db):
    """'Who moved the Brix target and when' gets asked when a load is disputed."""
    set_fruit_target(db, "B3", "W", target_brix_min=23.0, set_by="manager:+1250")
    out = set_fruit_target(db, "B3", "W", target_brix_min=24.0, set_by="owner:+1778")
    assert out["created"] is False
    assert out["changed"]["target_brix_min"] == [23.0, 24.0]

    rows = db.execute(
        "SELECT actor, action FROM audit_log WHERE entity='fruit_targets' ORDER BY id"
    ).fetchall()
    assert [r["action"] for r in rows] == ["fruit_target.set", "fruit_target.changed"]
    assert rows[1]["actor"] == "owner:+1778"


def test_a_partial_update_does_not_blank_the_rest(db):
    set_fruit_target(db, "B3", "W", target_brix_min=23.0, target_brix_max=25.0,
                     contract_notes="pick early if smoke")
    set_fruit_target(db, "B3", "W", target_brix_max=26.0)
    t = get_fruit_targets(db, "B3")["targets"][0]
    assert t["target_brix_min"] == 23.0
    assert t["target_brix_max"] == 26.0
    assert t["contract_notes"] == "pick early if smoke"


def test_get_targets_reports_who_set_it_and_when(db):
    set_fruit_target(db, "B3", "W", target_brix_min=23.0, set_by="manager:+1250")
    t = get_fruit_targets(db, "B3")["targets"][0]
    assert t["last_set_by"] == "manager:+1250"
    assert t["last_set_at"]


# ── Validation: the quiet failures ───────────────────────────────────────────

def test_a_decimal_slip_is_refused(db):
    """2.3 instead of 23 would silently report every block as ripe."""
    out = set_fruit_target(db, "B3", "W", target_brix_min=2.3)
    assert out["error"] == "invalid_target"
    assert any("target_brix_min" in p for p in out["problems"])


def test_an_inverted_range_is_refused(db):
    out = set_fruit_target(db, "B3", "W", target_brix_min=25.0, target_brix_max=23.0)
    assert out["error"] == "invalid_target"
    assert any("above its maximum" in p for p in out["problems"])


def test_a_backwards_harvest_window_is_refused(db):
    out = set_fruit_target(db, "B3", "W", harvest_window_from=f"{YEAR}-10-15",
                           harvest_window_to=f"{YEAR}-09-25")
    assert any("opens after it closes" in p for p in out["problems"])


def test_a_malformed_date_is_refused(db):
    out = set_fruit_target(db, "B3", "W", harvest_window_from="end of September")
    assert any("not YYYY-MM-DD" in p for p in out["problems"])


def test_the_winery_must_be_named(db):
    """Two wineries can contract different specs off the same block."""
    assert set_fruit_target(db, "B3", "  ")["error"] == "winery_required"


def test_an_unknown_block_is_refused(db):
    assert set_fruit_target(db, "B99", "W", target_brix_min=23.0)["error"] == "unknown_block"


def test_nothing_is_written_when_validation_fails(db):
    set_fruit_target(db, "B3", "W", target_brix_min=2.3)
    assert db.execute("SELECT COUNT(*) c FROM fruit_targets").fetchone()["c"] == 0


# ── Sample corrections ───────────────────────────────────────────────────────

def test_a_mistyped_reading_can_be_corrected(db):
    original = record_sample(db, "B3", brix=12.4)["recorded"]
    out = correct_sample(db, original["id"], brix=21.4, set_by="manager:+1250",
                         raw_message="meant 21.4 not 12.4")
    assert out["corrected"]["brix"] == 21.4
    assert out["corrected"]["corrects_sample_id"] == original["id"]


def test_the_original_sample_survives_untouched(db):
    original = record_sample(db, "B3", brix=12.4)["recorded"]
    correct_sample(db, original["id"], brix=21.4)
    still = db.execute(
        "SELECT brix FROM fruit_samples WHERE id = ?", (original["id"],)
    ).fetchone()
    assert still["brix"] == 12.4
    assert db.execute("SELECT COUNT(*) c FROM fruit_samples").fetchone()["c"] == 2


def test_only_the_corrected_row_drives_reporting(db):
    set_fruit_target(db, "B3", "W", target_brix_min=23.0)
    original = record_sample(db, "B3", brix=12.4)["recorded"]
    correct_sample(db, original["id"], brix=21.4)
    entry = maturity_status(db, "B3")["blocks"][0]
    assert entry["brix"] == 21.4


def test_a_sample_cannot_be_corrected_twice(db):
    original = record_sample(db, "B3", brix=12.4)["recorded"]
    correct_sample(db, original["id"], brix=21.4)
    out = correct_sample(db, original["id"], brix=22.0)
    assert out["error"] == "already_superseded"


def test_a_correction_still_has_to_be_plausible(db):
    original = record_sample(db, "B3", brix=21.4)["recorded"]
    assert correct_sample(db, original["id"], brix=87)["error"] == "implausible_value"


def test_unknown_fields_are_refused(db):
    original = record_sample(db, "B3", brix=21.4)["recorded"]
    out = correct_sample(db, original["id"], block_code="B1")
    assert out["error"] == "unknown_field"


def test_correcting_a_missing_sample_is_refused(db):
    assert correct_sample(db, 9999, brix=21.0)["error"] == "unknown_sample"


@pytest.mark.parametrize("field,value", [("brix", 21.4), ("ta_g_l", 6.8), ("ph", 3.4)])
def test_unchanged_fields_carry_over_into_the_correction(db, field, value):
    original = record_sample(db, "B3", brix=21.4, ta_g_l=6.8, ph=3.4)["recorded"]
    out = correct_sample(db, original["id"], sample_size=200)
    assert out["corrected"][field] == value
