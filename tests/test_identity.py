"""Contact resolution by phone or WhatsApp lid.

Found live 2026-08-22: WhatsApp identified a real, enrolled contact by a device-linked
"...@lid" id, not by the phone number in contacts.wa_phone. A lookup keyed only on phone found
nothing, so Hermes never knew who was speaking - and four separate Punjabi voice notes got
auto-detected as Portuguese, then Polish, with nothing to trigger the forced-language fix.
"""

from __future__ import annotations

import sqlite3

import pytest

from vineyard_mcp.queries import resolve_contact


def test_resolves_by_phone(db, juan):
    out = resolve_contact(db, juan)
    assert out["found"] is True
    assert out["contact"]["short_name"] == "Juan"


def test_resolves_by_lid_once_recorded(db, juan):
    db.execute("UPDATE contacts SET wa_lid = ? WHERE wa_phone = ?",
              ("111111111111111@lid", juan))
    out = resolve_contact(db, "111111111111111@lid")
    assert out["found"] is True
    assert out["contact"]["wa_phone"] == juan


def test_an_unrecorded_lid_is_reported_as_not_found_not_guessed(db):
    """The correct response to an unknown sender is to say so, not to infer identity from
    voice content."""
    out = resolve_contact(db, "999999999999999@lid")
    assert out["found"] is False
    assert out["identifier"] == "999999999999999@lid"


def test_a_contact_with_no_lid_yet_is_still_findable_by_phone(db, applicator):
    """Most contacts will not have a lid recorded until they message in at least once - phone
    lookup must keep working regardless."""
    out = resolve_contact(db, applicator)
    assert out["found"] is True
    assert out["contact"]["wa_lid"] is None


def test_two_contacts_cannot_share_a_lid(db, juan):
    other = "+15215550002"  # Miguel, per conftest - must be a real fixture row or the
    # UPDATE below silently matches nothing and the test passes for the wrong reason.
    assert db.execute(
        "SELECT COUNT(*) c FROM contacts WHERE wa_phone = ?", (other,)
    ).fetchone()["c"] == 1

    db.execute("UPDATE contacts SET wa_lid = ? WHERE wa_phone = ?", ("222@lid", juan))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE contacts SET wa_lid = ? WHERE wa_phone = ?", ("222@lid", other))


def test_multiple_contacts_may_simultaneously_have_no_lid(db):
    """The partial unique index must allow many NULLs - most contacts start without one."""
    n = db.execute("SELECT COUNT(*) c FROM contacts WHERE wa_lid IS NULL").fetchone()["c"]
    assert n >= 2  # the fixture seeds several contacts, none with a lid yet
