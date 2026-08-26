"""Advisory maths, and the guardrail that keeps recommendations grounded.

The load-bearing test here is `spray_options` refusing to surface a product that is not in the
shed. That list IS the guardrail: if it ever returns something arbitrary, Hermes can recommend a
product nobody owns at a rate nobody verified.
"""

from __future__ import annotations

from vineyard_mcp.advisory import (
    compute_gdd,
    log_recommendation,
    recent_recommendations,
    spray_options,
    spray_status,
    task_cadence,
)
from vineyard_mcp.compliance import commit_spray_log, draft_spray_log, present_confirmation

SPRAY = {
    "product_name_raw": "Microthiol Disperss",
    "block_code": "B3",
    "start_time": "06:00",
    "end_time": "08:00",
    "rate_value": 8,
    "rate_units": "kg/ha",
    "wind_kmh": 8,
    "temp_c": 18,
    "target_pest": "powdery mildew",
}


def _spray(db, phone, **over):
    out = draft_spray_log(db, phone, {**SPRAY, **over}, raw_message="x")
    present_confirmation(db, out["confirm_token"])
    return commit_spray_log(db, out["confirm_token"], "si")


# ── Growing degree days ──────────────────────────────────────────────────────

def test_gdd_accumulates_above_base_only():
    days = [{"tmax_c": 20, "tmin_c": 10}, {"tmax_c": 30, "tmin_c": 10}]
    # (15-10) + (20-10) = 15
    assert compute_gdd(days)["gdd"] == 15.0


def test_a_cold_day_contributes_zero_not_a_negative():
    """A frost does not un-ripen the crop. Negative accumulation would understate the season."""
    days = [{"tmax_c": 4, "tmin_c": -6}, {"tmax_c": 20, "tmin_c": 10}]
    assert compute_gdd(days)["gdd"] == 5.0


def test_missing_days_are_counted_not_silently_skipped():
    """A gappy record reads EARLIER than reality, which is the direction that mistimes a spray.
    The gap has to be visible."""
    days = [{"tmax_c": 20, "tmin_c": 10}, {"tmax_c": None, "tmin_c": 10}, {"bad": True}]
    out = compute_gdd(days)
    assert out["days_used"] == 1
    assert out["days_missing"] == 2
    assert out["complete"] is False


def test_empty_input_is_not_complete():
    assert compute_gdd([])["complete"] is False


# ── Protection status ────────────────────────────────────────────────────────

def test_spray_status_reports_days_since_and_lapse(db, juan):
    from datetime import date, timedelta

    old = (date.today() - timedelta(days=16)).isoformat()
    _spray(db, juan, log_date=old)
    status = spray_status(db, "B3")
    entry = status["protection"][0]
    assert entry["days_since"] == 16
    assert entry["reapply_days"] == 10
    assert entry["lapsed"] is True


def test_unknown_interval_is_reported_as_unknown_not_guessed(db, juan):
    db.execute("UPDATE products SET reapply_days = NULL WHERE trade_name='Microthiol Disperss'")
    _spray(db, juan)
    entry = spray_status(db, "B3")["protection"][0]
    assert entry["interval_known"] is False
    assert entry["lapsed"] is None


def test_blocks_never_sprayed_are_surfaced(db, juan):
    _spray(db, juan)
    status = spray_status(db)
    never = {b["code"] for b in status["never_sprayed"]}
    assert "B1" in never and "B3" not in never


def test_consecutive_same_resistance_group_is_flagged(db, juan):
    """Repeating a FRAC group breeds resistance - the survivors are the population that
    tolerated the last pass. Three in a row must be said out loud."""
    from datetime import date, timedelta

    for n in (30, 20, 10):
        _spray(db, juan, log_date=(date.today() - timedelta(days=n)).isoformat())
    rot = spray_status(db, "B3")["rotation"]
    assert rot and rot[0]["frac_group"] == "M2"
    assert rot[0]["consecutive"] == 3
    assert rot[0]["concern"] == "high"


def test_a_single_application_is_not_a_rotation_concern(db, juan):
    _spray(db, juan)
    assert spray_status(db, "B3")["rotation"] == []


# ── The guardrail ────────────────────────────────────────────────────────────

def test_spray_options_only_ever_returns_products_in_the_shed(db):
    """THE guardrail. If this leaks anything not in `products`, Hermes can recommend a product
    nobody owns at a rate nobody verified."""
    shed = {r["trade_name"] for r in db.execute("SELECT trade_name FROM products").fetchall()}
    names = {o["trade_name"] for o in spray_options(db, "B3", "powdery mildew")["options"]}
    assert names <= shed
    assert names, "the shed has mildew products; none were offered"


def test_options_exclude_products_not_registered_for_the_pest(db):
    db.execute("UPDATE products SET target_pests='botrytis' WHERE trade_name='Kumulus DF'")
    names = {o["trade_name"] for o in spray_options(db, "B3", "powdery mildew")["options"]}
    assert "Kumulus DF" not in names


def test_unverified_products_are_shown_but_unusable(db):
    """Visible so a manager sees what verifying would unlock; refused so obligation 4 holds."""
    db.execute("UPDATE products SET verified=0, target_pests='powdery mildew' "
               "WHERE trade_name='Kumulus DF'")
    opts = {o["trade_name"]: o for o in spray_options(db, "B3", "powdery mildew")["options"]}
    k = opts["Kumulus DF"]
    assert k["usable"] is False
    assert any("unverified" in b for b in k["blockers"])
    assert k["rei_hours"] is None, "an unverified product must never state an REI"


def test_options_warn_when_a_choice_repeats_the_last_resistance_group(db, juan):
    _spray(db, juan)
    opts = {o["trade_name"]: o for o in spray_options(db, "B3", "powdery mildew")["options"]}
    assert any("same resistance group" in n for n in opts["Kumulus DF"]["notes"])


def test_options_carry_the_temperature_ceiling(db):
    opts = spray_options(db, "B3", "powdery mildew")["options"]
    assert any("30" in n for o in opts for n in o["notes"])


# ── Task cadence ─────────────────────────────────────────────────────────────

def test_task_cadence_compares_against_your_own_median(db, juan):
    from datetime import date, timedelta

    from vineyard_mcp.compliance import commit_task_log, draft_task_log

    for block, days_ago in (("B1", 5), ("B3", 8), ("N2", 40)):
        out = draft_task_log(db, juan, {
            "task_type": "deshoje", "hours_total": 6, "block_code": block,
            "log_date": (date.today() - timedelta(days=days_ago)).isoformat()})
        present_confirmation(db, out["confirm_token"])
        commit_task_log(db, out["confirm_token"], "si")

    out = task_cadence(db, "deshoje")
    assert out["median_days_by_task"]["deshoje"] == 8
    worst = out["blocks"][0]
    assert worst["block_code"] == "N2"
    assert worst["behind"] is True


# ── Recommendations are logged so they can be judged ────────────────────────

def test_recommendations_are_recorded_with_their_evidence(db):
    log_recommendation(
        db, subject="B3 mildew cover",
        options="Kumulus DF (M2) or hold until Thursday",
        evidence="16 days since last cover; label interval 10; no window until Thu 06:00",
        recommended="hold until Thursday",
    )
    recs = recent_recommendations(db)
    assert len(recs) == 1
    assert recs[0]["recommended"] == "hold until Thursday"
    assert "16 days" in recs[0]["evidence"]


# ── Catalogue updates must never undo a human's label verification ──────────

def test_seed_update_cannot_reset_verification_or_label_values():
    """`import-seed --update` refreshes the catalogue. If it could touch these, a careless CSV
    re-import would silently un-verify a product, or overwrite a label REI with a spreadsheet
    guess - defeating obligation 4 through the back door."""
    from vineyard_mcp.cli import UPDATABLE

    forbidden = {"verified", "rei_hours", "phi_days", "pcp_number", "verified_by",
                 "verified_at_utc"}
    assert not (set(UPDATABLE["products"]) & forbidden)


def test_migrations_are_additive_only():
    """A migration that drops or retypes a column can lose committed compliance rows - the same
    harm the append-only triggers exist to prevent.

    Matches destructive STATEMENTS, not bare words: `BEFORE DELETE ON ... RAISE(ABORT)` is a
    trigger that *prevents* deletion, and an earlier version of this test flagged it.
    """
    import re

    from vineyard_mcp.db import MIGRATIONS

    destructive = re.compile(
        r"(DROP\s+(TABLE|COLUMN|INDEX|VIEW|TRIGGER)|DELETE\s+FROM|TRUNCATE)", re.I
    )
    for version, statements in MIGRATIONS.items():
        for st in statements:
            hit = destructive.search(st)
            assert hit is None, f"v{version} is destructive: {hit.group(0)!r}"
