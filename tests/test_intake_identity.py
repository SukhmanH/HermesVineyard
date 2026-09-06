"""Intake accepts a lid-identified sender, and the confirmation gate still binds to the person.

Found live 2026-09-06 while wiring voice-note intake: `resolve_contact` and `registry.py` both
matched a sender on `wa_phone OR wa_lid`, but `compliance._contact` matched on `wa_phone` alone.
So an enrolled worker whose message arrived carrying a device-linked "...@lid" — which is not the
sender's choice — got `unknown_contact` from `draft_spray_log` and could not file a report at all,
while the same identifier resolved fine everywhere else. Same person, two answers, depending on
which door they knocked on.

The fix collapses every identity entering the draft system to the contact's canonical `wa_phone`.
That must NOT weaken obligation 1: a draft is still bound to the person who opened it, so a
forwarded confirmation card cannot be signed by somebody else. These tests pin both halves —
the door being open, and the lock still working.
"""

from __future__ import annotations

import pytest

from vineyard_mcp import compliance as C


LID = "111111111111111@lid"
OTHER_LID = "222222222222222@lid"


@pytest.fixture()
def juan_with_lid(db, juan):
    db.execute("UPDATE contacts SET wa_lid = ? WHERE wa_phone = ?", (LID, juan))
    db.commit()
    return juan


def _extraction():
    return {
        "product_name_raw": "Kumulus DF",
        "block_code": "B3",
        "rate_value": 6,
        "rate_units": "kg/ha",
        "start_time": "07:00",
        "end_time": "10:30",
        "target_pest": "powdery mildew",
    }


def test_contact_resolves_by_lid_not_just_phone(db, juan_with_lid):
    assert C._contact(db, juan_with_lid)["short_name"] == "Juan"
    assert C._contact(db, LID)["short_name"] == "Juan"


def test_unknown_identifier_still_resolves_to_nothing(db):
    """An unknown sender must stay unknown — never inferred."""
    assert C._contact(db, OTHER_LID) is None


def test_draft_opens_from_a_lid(db, juan_with_lid):
    """The actual break: a lid-identified worker could not file a spray report."""
    out = C.draft_spray_log(db, LID, _extraction(), raw_message="test")
    assert "error" not in out, out
    assert out["draft"]["applicator_name"] == "Juan Perez"


def test_draft_is_keyed_by_canonical_phone_whichever_door_was_used(db, juan_with_lid):
    """One worker must not end up with two parallel open drafts for the same report."""
    first = C.draft_spray_log(db, LID, _extraction(), raw_message="test")
    second = C.draft_spray_log(db, juan_with_lid, {"notes": "same report, other door"})
    assert second["confirm_token"] == first["confirm_token"]

    row = db.execute(
        "SELECT wa_phone FROM drafts WHERE confirm_token = ?", (first["confirm_token"],)
    ).fetchone()
    assert row["wa_phone"] == juan_with_lid


def test_confirmation_crossing_identities_is_allowed_for_the_same_person(db, juan_with_lid):
    """Opened carrying a lid, confirmed carrying the phone — one person, so the identity gate
    must not fire. Any refusal here must come from a LATER check, never the binding."""
    out = C.draft_spray_log(db, LID, _extraction(), raw_message="test")
    _, refusal = C._load_committable(db, out["confirm_token"], "spray_report", "si", juan_with_lid)
    if refusal is not None:
        assert refusal["error"] != "confirmation_from_wrong_number"


def test_a_different_person_still_cannot_confirm_someone_elses_draft(db, juan_with_lid, applicator):
    """Obligation 1. The token alone is not the signature — the token PLUS the same person is."""
    out = C.draft_spray_log(db, LID, _extraction(), raw_message="test")
    _, refusal = C._load_committable(db, out["confirm_token"], "spray_report", "si", applicator)
    assert refusal is not None
    assert refusal["error"] == "confirmation_from_wrong_number"


def test_a_stranger_cannot_confirm_a_draft(db, juan_with_lid):
    """An unrecognised lid resolves to nothing and must not match the draft's owner."""
    out = C.draft_spray_log(db, LID, _extraction(), raw_message="test")
    _, refusal = C._load_committable(db, out["confirm_token"], "spray_report", "si", OTHER_LID)
    assert refusal is not None
    assert refusal["error"] == "confirmation_from_wrong_number"
