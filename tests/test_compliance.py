"""The four obligations, tested as obligations rather than as features.

Each of these is something that must hold when the model is having a bad day, when a message
carries an injection, or when a provider is degraded. If one of these tests goes red, the
system is not merely buggy — it is capable of producing a false legal record.
"""

from __future__ import annotations

from datetime import UTC

from vineyard_mcp.compliance import (
    commit_spray_log,
    commit_task_log,
    draft_correction,
    draft_spray_log,
    draft_task_log,
    find_recent_logs,
    present_confirmation,
    resolve_block,
    resolve_product,
    verify_product,
)
from vineyard_mcp.db import row_to_dict


def _commit_spray(db, token, reply="si, esta bien"):
    """Full gate: present the card, then commit with the worker's words."""
    present_confirmation(db, token)
    return commit_spray_log(db, token, reply)


def _commit_task(db, token, reply="si"):
    present_confirmation(db, token)
    return commit_task_log(db, token, reply)

FULL_SPRAY = {
    "wind_kmh": 8,          # BC requires prevailing weather on the record
    "temp_c": 18,
    "product_name_raw": "Microthiol Disperss",
    "block_code": "B3",
    "start_time": "06:00",
    "end_time": "08:00",
    "rate_value": 8,
    "rate_units": "kg/ha",
    "log_date": "2026-05-14",
}


def _ready_draft(db, phone, **over):
    payload = {**FULL_SPRAY, **over}
    return draft_spray_log(db, phone, payload, raw_message="hice el spray de azufre en bloque 3")


# ── Obligation 1: nothing commits without the worker's confirmation ───────────

def test_commit_with_unknown_token_is_refused(db):
    assert _commit_spray(db, "not-a-real-token")["error"] == "unknown_token"


def test_commit_with_a_consumed_token_is_refused(db, juan):
    token = _ready_draft(db, juan)["confirm_token"]
    assert "committed" in _commit_spray(db, token)
    again = _commit_spray(db, token)
    assert again["error"] == "token_already_used"
    assert db.execute("SELECT COUNT(*) c FROM spray_log").fetchone()["c"] == 1


def test_commit_while_fields_are_missing_is_refused(db, juan):
    """A draft that is still collecting has not been shown to the worker as a card,
    so there is no confirmation to honour."""
    out = draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"})
    assert out["ready_to_confirm"] is False
    refusal = _commit_spray(db, out["confirm_token"])
    assert refusal["error"] == "draft_not_ready"
    assert refusal["missing_fields"]
    assert db.execute("SELECT COUNT(*) c FROM spray_log").fetchone()["c"] == 0


def test_task_token_cannot_commit_a_spray(db, juan):
    """Cross-intent tokens are refused: a confirmed task is not a confirmed spray."""
    task = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 6, "block_code": "B1"})
    assert task["ready_to_confirm"] is True
    assert _commit_spray(db, task["confirm_token"])["error"] == "wrong_intent"


# ── Obligation 2: BC-required fields validated server-side ───────────────────

def test_missing_required_fields_are_named_individually(db, juan):
    out = draft_spray_log(db, juan, {"block_code": "B3"})
    fields = {m["field"] for m in out["missing_fields"]}
    assert "product_name_raw" in fields
    assert "start_time" in fields
    assert "rate_or_total" in fields


def test_rate_or_total_satisfies_the_requirement_either_way(db, juan):
    by_total = _ready_draft(
        db, juan, rate_value=None, rate_units=None, total_amount=36, total_units="kg"
    )
    assert by_total["ready_to_confirm"] is True


def test_negative_quantities_are_rejected(db, juan):
    out = _ready_draft(db, juan, rate_value=-5)
    assert {"field": "rate_value", "why": "must_be_positive"} in out["missing_fields"]


def test_bad_time_format_is_rejected(db, juan):
    out = _ready_draft(db, juan, start_time="6am")
    assert any(m["field"] == "start_time" for m in out["missing_fields"])


# ── Obligation 3: the worker's own words, verbatim ───────────────────────────

def test_raw_message_is_stored_verbatim(db, juan):
    original = "hice el spray de asufre en el bloke 3 como a las 6"
    out = draft_spray_log(db, juan, FULL_SPRAY, raw_message=original)
    committed = _commit_spray(db, out["confirm_token"])["committed"]
    assert committed["raw_message"] == original


def test_raw_message_accumulates_across_the_interview(db, juan):
    """A three-message interview must keep all three, not only the last."""
    first = draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"},
                            raw_message="hice el spray")
    draft_spray_log(db, juan, {"block_code": "B3"}, raw_message="en el bloque 3")
    out = draft_spray_log(db, juan, {"start_time": "06:00", "end_time": "08:00",
                                     "rate_value": 8, "rate_units": "kg/ha",
                                     "wind_kmh": 8, "temp_c": 18},
                          raw_message="viento tranquilo")
    assert out["confirm_token"] == first["confirm_token"]
    committed = _commit_spray(db, out["confirm_token"])["committed"]
    assert "hice el spray" in committed["raw_message"]
    assert "en el bloque 3" in committed["raw_message"]
    assert "viento tranquilo" in committed["raw_message"]


# ── Obligation 4: never assert an unverified re-entry interval ────────────────

def test_unverified_product_yields_no_rei_and_asks_for_the_label(db, juan):
    """The product row HAS rei_hours=48, but nobody has checked the physical label.
    Hermes must ask rather than assert."""
    out = _ready_draft(db, juan, product_name_raw="Mystery Fungicide")
    assert out["product_verified"] is False
    assert {"field": "label_rei", "why": "product_unverified"} in out["missing_fields"]
    assert out["ready_to_confirm"] is False
    assert "rei_hours" not in out["draft"]


def test_applicator_supplied_label_rei_unblocks_the_commit(db, juan):
    out = _ready_draft(db, juan, product_name_raw="Mystery Fungicide", label_rei=12)
    assert out["ready_to_confirm"] is True
    committed = _commit_spray(db, out["confirm_token"])["committed"]
    assert committed["rei_hours"] == 12


def test_verified_product_supplies_rei_and_pcp(db, juan):
    out = _ready_draft(db, juan)
    assert out["product_verified"] is True
    result = _commit_spray(db, out["confirm_token"])
    assert result["committed"]["rei_hours"] == 24
    assert result["committed"]["pcp_number"] == "PCP-12345"
    assert result["rei_broadcast"]["block_code"] == "B3"


def test_verify_product_is_a_named_human_act_and_is_audited(db):
    out = verify_product(db, "Mystery Fungicide", verified_by="manager:+12505550004",
                         pcp_number="PCP-99999", rei_hours=48)
    assert out["verified"]["verified"] == 1
    row = db.execute(
        "SELECT * FROM audit_log WHERE action = 'product.verified'"
    ).fetchone()
    assert row["actor"] == "manager:+12505550004"


# ── REI expiry, including across a DST boundary ──────────────────────────────

def test_rei_expiry_is_correct_across_a_dst_boundary(db, juan):
    """BC springs forward 2026-03-08. A 24 h REI is 24 REAL hours, so the UTC arithmetic
    must not drift even though the local wall clock shifts."""
    out = _ready_draft(db, juan, log_date="2026-03-07", start_time="16:00", end_time="18:00")
    committed = _commit_spray(db, out["confirm_token"])["committed"]
    # 2026-03-07 18:00 PST (UTC-8) == 2026-03-08T02:00:00Z; +24h == 2026-03-09T02:00:00Z
    assert committed["rei_expires_at_utc"] == "2026-03-09T02:00:00Z"


def test_rei_active_view_lists_the_block(db, juan):
    from datetime import datetime, timedelta
    future = datetime.now(UTC) + timedelta(days=1)
    out = _ready_draft(db, juan, log_date=future.strftime("%Y-%m-%d"))
    _commit_spray(db, out["confirm_token"])
    active = db.execute("SELECT * FROM rei_active").fetchall()
    assert [r["block_code"] for r in active] == ["B3"]


# ── Corrections supersede, never mutate ──────────────────────────────────────

def test_correction_creates_a_new_row_and_leaves_the_original_byte_identical(db, juan):
    first = _commit_spray(db, _ready_draft(db, juan)["confirm_token"])["committed"]
    before = row_to_dict(
        db.execute("SELECT * FROM spray_log WHERE id = ?", (first["id"],)).fetchone()
    )

    corr = draft_correction(db, "spray_log", first["id"], {"rate_value": 6},
                            raw_message="fueron 6 kg no 8")
    assert corr["ready_to_confirm"] is True
    new = _commit_spray(db, corr["confirm_token"])["committed"]

    after = row_to_dict(
        db.execute("SELECT * FROM spray_log WHERE id = ?", (first["id"],)).fetchone()
    )
    assert after == before, "the superseded row must never change"
    assert new["corrects_log_id"] == first["id"]
    assert new["rate_value"] == 6

    current = db.execute("SELECT * FROM spray_log_current").fetchall()
    assert [r["id"] for r in current] == [new["id"]]
    assert db.execute("SELECT COUNT(*) c FROM spray_log").fetchone()["c"] == 2


def test_a_row_cannot_be_corrected_twice(db, juan):
    first = _commit_spray(db, _ready_draft(db, juan)["confirm_token"])["committed"]
    corr = draft_correction(db, "spray_log", first["id"], {"rate_value": 6})
    _commit_spray(db, corr["confirm_token"])
    second = draft_correction(db, "spray_log", first["id"], {"rate_value": 7})
    assert second["error"] == "already_superseded"


def test_find_recent_logs_returns_the_workers_own_records(db, juan):
    _commit_spray(db, _ready_draft(db, juan)["confirm_token"])
    found = find_recent_logs(db, juan)
    assert len(found["spray_log"]) == 1
    assert found["spray_log"][0]["block_code"] == "B3"


# ── Resolution helpers: tolerant, but never inventive ────────────────────────

def test_block_resolution_handles_how_people_actually_talk(db):
    for said in ("B3", "b3", "bloque 3", "el 3", "bloque tres", "block three", "3"):
        assert resolve_block(db, said)["code"] == "B3", said


def test_block_resolution_returns_none_rather_than_guessing(db):
    # "the far one by the road" contains the word "one". Substituting number-words across free
    # prose would resolve that to B1 - an invented block on a legal record. Regression guard.
    assert resolve_block(db, "the far one by the road") is None
    assert resolve_block(db, "one of the guys did it") is None
    assert resolve_block(db, "B99") is None
    assert resolve_block(db, "") is None
    assert resolve_block(db, None) is None


def test_ambiguous_block_number_is_a_question_not_a_coin_flip(db):
    """Two blocks sharing a number across sites must not silently resolve to either."""
    db.execute("INSERT INTO blocks (code, name, site, acres) VALUES ('N3','Bench Three','naramata',2.0)")
    assert resolve_block(db, "bloque 3") is None
    assert resolve_block(db, "B3")["code"] == "B3"  # explicit code still works


def test_product_resolution_tolerates_misspelling(db):
    assert resolve_product(db, "microthiol")["trade_name"] == "Microthiol Disperss"
    assert resolve_product(db, "Microthiol Dispers")["trade_name"] == "Microthiol Disperss"


def test_product_resolution_refuses_the_unknown(db):
    assert resolve_product(db, "something nobody stocks") is None


def test_unresolved_block_blocks_the_commit(db, juan):
    out = _ready_draft(db, juan, block_code="B99")
    assert out["ready_to_confirm"] is False
    assert _commit_spray(db, out["confirm_token"])["error"] == "draft_not_ready"


# ── Draft merge semantics ────────────────────────────────────────────────────

def test_a_followup_answer_never_blanks_an_earlier_field(db, juan):
    first = draft_spray_log(db, juan, FULL_SPRAY)
    second = draft_spray_log(db, juan, {"end_time": "09:00", "rate_units": None})
    assert second["confirm_token"] == first["confirm_token"]
    assert second["draft"]["rate_units"] == "kg/ha"
    assert second["draft"]["end_time"] == "09:00"


def test_unknown_contact_is_refused(db):
    assert draft_spray_log(db, "+1999", FULL_SPRAY)["error"] == "unknown_contact"


# ── Task log ─────────────────────────────────────────────────────────────────

def test_task_log_records_crew_hours_and_participants(db, juan):
    out = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 12, "block_code": "B1"})
    committed = _commit_task(db, out["confirm_token"])["committed"]
    assert committed["hours_total"] == 12
    workers = db.execute(
        "SELECT contact_id FROM task_workers WHERE task_log_id = ?", (committed["id"],)
    ).fetchall()
    assert len(workers) == 1


def test_task_without_hours_is_not_ready(db, juan):
    out = draft_task_log(db, juan, {"task_type": "poda"})
    assert {"field": "hours_total", "why": "required"} in out["missing_fields"]


# ── The applicator's English path (docs/01 §D11) ─────────────────────────────

def test_applicator_files_a_spray_in_english(db, applicator):
    out = draft_spray_log(
        db, applicator,
        {**FULL_SPRAY, "target_pest": "powdery mildew", "method": "airblast"},
        raw_message="Sprayed sulfur on B3 06:00-08:00, 8 kg/ha",
    )
    assert out["ready_to_confirm"] is True
    committed = _commit_spray(db, out["confirm_token"])["committed"]
    assert committed["applicator_name"] == "Gurpreet Singh"
    assert committed["target_pest"] == "powdery mildew"
