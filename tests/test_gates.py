"""Regression guards for the protections that FAILED in the first real agent run (2026-08-21).

Every test here corresponds to something that actually went wrong when a live model drove the
kernel for the first time. They are grouped separately from the rest of the suite because they
are not hypothetical edge cases — each one is a defect that reached a committed legal record.

What the first run produced, before these guards existed:
  * a record committed with no confirmation card ever shown to anyone
  * a product marked verified=1 on hearsay, keeping its placeholder `PCP-XXXXX` and an
    unconfirmed REI
  * 20 kg/ha committed against a 6 kg/ha label rate, unremarked
  * wind and temperature left NULL on a record where BC requires them
  * the same sentence stored three times in the audit field
"""

from __future__ import annotations

import pytest

from vineyard_mcp.compliance import (
    commit_spray_log,
    draft_spray_log,
    present_confirmation,
    verify_product,
)

READY = {
    "product_name_raw": "Microthiol Disperss",
    "block_code": "B3",
    "start_time": "06:00",
    "end_time": "08:00",
    "rate_value": 8,
    "rate_units": "kg/ha",
    "wind_kmh": 8,
    "temp_c": 18,
    "log_date": "2026-05-14",
}


def _ready(db, phone, **over):
    return draft_spray_log(db, phone, {**READY, **over}, raw_message="hice el spray")


# ── Obligation 1: a human actually has to agree ──────────────────────────────

def test_commit_without_presenting_the_card_is_refused(db, juan):
    """THE headline failure. draft_* used to set 'awaiting_confirm' itself the moment the
    fields were complete, so the agent could draft and commit in one breath and nobody ever
    confirmed anything. The token gate was checking readiness, not agreement."""
    out = _ready(db, juan)
    assert out["ready_to_confirm"] is True

    refusal = commit_spray_log(db, out["confirm_token"], "si")
    assert refusal["error"] == "not_presented"
    assert db.execute("SELECT COUNT(*) c FROM spray_log").fetchone()["c"] == 0


def test_commit_with_an_empty_reply_is_refused(db, juan):
    out = _ready(db, juan)
    present_confirmation(db, out["confirm_token"])
    for empty in ("", "   ", "-", "n/a", "none"):
        refusal = commit_spray_log(db, out["confirm_token"], empty)
        assert refusal["error"] == "no_worker_confirmation", empty
    assert db.execute("SELECT COUNT(*) c FROM spray_log").fetchone()["c"] == 0


def test_the_workers_words_are_stored_as_the_signature(db, juan):
    """The reply goes ON the record. If the agent ever fabricates one, that is now a
    discoverable falsification rather than an invisible gap."""
    out = _ready(db, juan)
    present_confirmation(db, out["confirm_token"])
    committed = commit_spray_log(db, out["confirm_token"], "sí, así fue")["committed"]
    assert committed["confirmed_by_reply"] == "sí, así fue"


def test_presenting_an_incomplete_draft_is_refused(db, juan):
    out = draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"})
    assert present_confirmation(db, out["confirm_token"])["error"] == "draft_not_ready"


# ── Obligation 4: verification means someone read the label ──────────────────

def test_verification_rejects_a_placeholder_pcp_number(db):
    """What actually happened: someone said "yes he read it", the product flipped to
    verified=1, and the row kept its seeded `PCP-XXXXX`. Obligation 4 was satisfied on paper
    and defeated in fact."""
    for placeholder in ("PCP-XXXXX", "XXXXX", "TBD", "n/a", "?", "00000", ""):
        out = verify_product(db, "Mystery Fungicide", verified_by="owner:+1250",
                             pcp_number=placeholder, rei_hours=48)
        assert out["error"] == "placeholder_pcp_number", placeholder

    assert db.execute(
        "SELECT verified FROM products WHERE trade_name='Mystery Fungicide'"
    ).fetchone()["verified"] == 0


def test_verification_requires_the_label_values_at_all(db):
    """If they cannot tell you the registration number and the re-entry interval,
    they did not read the label."""
    with pytest.raises(TypeError):
        verify_product(db, "Mystery Fungicide", verified_by="owner:+1250")  # type: ignore[call-arg]


def test_verification_rejects_a_nonsense_rei(db):
    out = verify_product(db, "Mystery Fungicide", verified_by="owner:+1250",
                         pcp_number="PCP-30456", rei_hours=-5)
    assert out["error"] == "bad_rei_hours"


def test_a_real_verification_succeeds_and_records_the_label_values(db):
    out = verify_product(db, "Mystery Fungicide", verified_by="owner:+12505550005",
                         pcp_number="PCP-30456", rei_hours=12, phi_days=7)
    assert out["verified"]["verified"] == 1
    assert out["verified"]["pcp_number"] == "PCP-30456"
    assert out["verified"]["rei_hours"] == 12


# ── Over-application must be asked about, not silently recorded ──────────────

def test_a_rate_far_above_the_label_blocks_until_confirmed(db, juan):
    """20 kg/ha went in against a 6 kg/ha label rate with nothing asked. That is a 3.3x
    over-application: a label violation and a residue risk."""
    out = _ready(db, juan, product_name_raw="Kumulus DF", rate_value=20)
    reasons = [m["why"] for m in out["missing_fields"] if m["field"] == "rate_confirmed"]
    assert reasons and reasons[0].startswith("above_label_rate:")
    assert out["ready_to_confirm"] is False


def test_a_confirmed_high_rate_commits_and_carries_the_flag(db, juan):
    """Confirmed is not erased — the record says it was above label rate and was checked."""
    out = _ready(db, juan, product_name_raw="Kumulus DF", rate_value=20, rate_confirmed=True)
    assert out["ready_to_confirm"] is True
    present_confirmation(db, out["confirm_token"])
    committed = commit_spray_log(db, out["confirm_token"], "si, 20 kg/ha")["committed"]
    assert committed["rate_flag"].startswith("above_label_rate:20")


def test_a_normal_rate_is_not_flagged(db, juan):
    out = _ready(db, juan, product_name_raw="Kumulus DF", rate_value=6)
    assert not [m for m in out["missing_fields"] if m["field"] == "rate_confirmed"]


def test_mismatched_units_are_not_compared(db, juan):
    """Comparing 20 g/ha against a 6 kg/ha label would be a false alarm; a false alarm here
    trains people to click past the real one."""
    out = _ready(db, juan, product_name_raw="Kumulus DF", rate_value=20, rate_units="g/ha")
    assert not [m for m in out["missing_fields"] if m["field"] == "rate_confirmed"]


# ── BC-required weather ──────────────────────────────────────────────────────

def test_weather_is_required_on_a_spray_record(db, juan):
    """wind_kmh and temp_c came back NULL on a committed record while Hermes reported the
    weather confidently in chat. BC requires prevailing conditions."""
    out = _ready(db, juan, wind_kmh=None, temp_c=None)
    fields = {m["field"] for m in out["missing_fields"]}
    assert {"wind_kmh", "temp_c"} <= fields
    assert out["ready_to_confirm"] is False


# ── Audit hygiene ────────────────────────────────────────────────────────────

def test_repeated_raw_messages_are_not_stored_three_times(db, juan):
    """The agent re-sent the same summary on each follow-up call, so the audit field held the
    same paragraph three times over."""
    same = "Sprayed sulfur on B3 this morning, 07:00 to 09:30."
    draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"}, raw_message=same)
    draft_spray_log(db, juan, {"block_code": "B3"}, raw_message=same)
    out = draft_spray_log(db, juan, {"start_time": "07:00", "end_time": "09:30",
                                     "rate_value": 8, "rate_units": "kg/ha",
                                     "wind_kmh": 8, "temp_c": 18}, raw_message=same)
    present_confirmation(db, out["confirm_token"])
    committed = commit_spray_log(db, out["confirm_token"], "si")["committed"]
    assert committed["raw_message"].count(same) == 1
