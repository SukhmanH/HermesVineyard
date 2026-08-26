"""Confirmation binding: the confirm token is not a bearer capability on its own.

Obligation 1 hardening (2026-08-25): a draft is bound to the WhatsApp number it was opened
with. The card transits WhatsApp and can be forwarded; the reply that commits must come from
the SAME number, resolved by resolve_contact. These tests pin that gate, plus the expiry gate.
"""

from __future__ import annotations

from vineyard_mcp.compliance import (
    commit_spray_log,
    commit_task_log,
    draft_spray_log,
    draft_task_log,
    expire_drafts,
    present_confirmation,
)

JUAN = "+15215550001"
GURPREET = "+12505550003"

SPRAY = {
    "product_name_raw": "Microthiol Disperss",
    "block_code": "B1",
    "log_date": "2026-08-25",
    "start_time": "06:00",
    "end_time": "07:30",
    "rate_value": 8,
    "rate_units": "kg/ha",
    "target_pest": "powdery mildew",
    "label_rei": 24,
    "wind_kmh": 8,
    "temp_c": 21,
}


def _open_spray_draft(db, phone):
    out = draft_spray_log(db, phone, dict(SPRAY), raw_message="spray test")
    assert out["ready_to_confirm"], out
    present_confirmation(db, out["confirm_token"])
    return out["confirm_token"]


def test_confirmation_from_a_different_number_is_refused(db, juan):
    token = _open_spray_draft(db, JUAN)
    refusal = commit_spray_log(db, token, "si", wa_phone=GURPREET)
    assert refusal["error"] == "confirmation_from_wrong_number"
    assert refusal["draft_phone"] == JUAN
    # And nothing committed.
    assert db.execute("SELECT COUNT(*) FROM spray_log").fetchone()[0] == 0


def test_confirmation_from_the_drafts_own_number_commits(db, juan):
    token = _open_spray_draft(db, JUAN)
    out = commit_spray_log(db, token, "si", wa_phone=JUAN)
    assert "committed" in out
    assert db.execute("SELECT COUNT(*) FROM spray_log").fetchone()[0] == 1


def test_task_confirmation_is_number_bound_too(db, juan):
    out = draft_task_log(
        db,
        JUAN,
        {
            "task_type": "poda",
            "block_code": "B1",
            "log_date": "2026-08-25",
            "hours_total": 4,
            "workers": [1],
        },
        raw_message="poda test",
    )
    present_confirmation(db, out["confirm_token"])
    refusal = commit_task_log(db, out["confirm_token"], "si", wa_phone=GURPREET)
    assert refusal["error"] == "confirmation_from_wrong_number"
    ok = commit_task_log(db, out["confirm_token"], "si", wa_phone=JUAN)
    assert "committed" in ok


def test_expired_draft_cannot_be_committed_even_by_its_own_number(db, juan):
    token = _open_spray_draft(db, JUAN)
    # Backdate past the 24h TTL, then run the reaper for real.
    db.execute(
        "UPDATE drafts SET created_at_utc = datetime('now', '-25 hours') WHERE confirm_token = ?",
        (token,),
    )
    db.commit()
    expire_drafts(db)
    refusal = commit_spray_log(db, token, "si", wa_phone=JUAN)
    assert refusal["error"] == "draft_expired"
    assert db.execute("SELECT COUNT(*) FROM spray_log").fetchone()[0] == 0


def test_wrong_number_refusal_does_not_consume_the_token(db, juan):
    """A failed impostor attempt must not burn the real worker's confirmation."""
    token = _open_spray_draft(db, JUAN)
    refusal = commit_spray_log(db, token, "si", wa_phone=GURPREET)
    assert refusal["error"] == "confirmation_from_wrong_number"
    ok = commit_spray_log(db, token, "si", wa_phone=JUAN)
    assert "committed" in ok


def test_server_tool_requires_the_sender_phone():
    """The MCP boundary must make wa_phone mandatory - the kernel default is for tests only."""
    import inspect

    from vineyard_mcp.server import commit_spray_log as tool

    sig = inspect.signature(tool)
    assert sig.parameters["wa_phone"].default is inspect.Parameter.empty

