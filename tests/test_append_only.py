"""The append-only guarantee, tested at the database level.

These triggers are the reason the guarantee is real rather than aspirational. Application code
can be bypassed by the next caller; RAISE(ABORT) cannot be talked past by an agent, a
prompt-injected message, or a maintainer in a hurry.

A failing UPDATE here is the system working correctly.
"""

from __future__ import annotations

import sqlite3

import pytest

from vineyard_mcp.compliance import (
    commit_spray_log,
    commit_task_log,
    draft_spray_log,
    draft_task_log,
    present_confirmation,
)
from vineyard_mcp.db import audit, transaction


def _commit_spray(db, token, reply="si, esta bien"):
    """Full gate: present the card, then commit with the worker's words."""
    present_confirmation(db, token)
    return commit_spray_log(db, token, reply)


def _commit_task(db, token, reply="si"):
    present_confirmation(db, token)
    return commit_task_log(db, token, reply)

SPRAY = {
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


def _one_spray(db, juan):
    out = draft_spray_log(db, juan, SPRAY, raw_message="original words")
    return _commit_spray(db, out["confirm_token"])["committed"]


def test_spray_log_refuses_update(db, juan):
    row = _one_spray(db, juan)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE spray_log SET rate_value = 999 WHERE id = ?", (row["id"],))


def test_spray_log_refuses_delete(db, juan):
    row = _one_spray(db, juan)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM spray_log WHERE id = ?", (row["id"],))


def test_spray_log_refuses_mass_delete(db, juan):
    """The panic move — 'just clear the table' — is also refused."""
    _one_spray(db, juan)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM spray_log")


def test_raw_message_cannot_be_rewritten_after_the_fact(db, juan):
    """Obligation 3 has teeth: the worker's words are not editable, by anyone."""
    row = _one_spray(db, juan)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE spray_log SET raw_message = 'something else' WHERE id = ?", (row["id"],)
        )
    assert db.execute(
        "SELECT raw_message FROM spray_log WHERE id = ?", (row["id"],)
    ).fetchone()["raw_message"] == "original words"


def test_task_log_is_append_only(db, juan):
    out = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 6, "block_code": "B1"})
    row = _commit_task(db, out["confirm_token"])["committed"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE task_log SET hours_total = 1 WHERE id = ?", (row["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM task_log WHERE id = ?", (row["id"],))


def test_audit_log_is_append_only(db):
    with transaction(db):
        audit(db, actor="hermes", action="agent.decision", detail_json="{}")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE audit_log SET action = 'nothing.happened'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM audit_log")


def test_messages_raw_is_append_only(db):
    with transaction(db):
        db.execute(
            """INSERT INTO messages_raw (direction, wa_phone, msg_type, body, ts_utc)
               VALUES ('in','+15215550001','text','hola','2026-05-14T13:00:00Z')"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE messages_raw SET body = 'adios'")


def test_drafts_are_mutable_by_design(db, juan):
    """Drafts are NOT append-only: an interview in progress is not yet a record.
    The gate is the commit, not the draft."""
    draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"})
    db.execute("UPDATE drafts SET state = 'expired'")  # must not raise
    assert db.execute("SELECT state FROM drafts").fetchone()["state"] == "expired"


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO spray_log (log_date, start_time, block_id, acres_treated,
                                      product_name_raw, applicator_contact_id, applicator_name,
                                      raw_message)
               VALUES ('2026-05-14','06:00',9999,1.0,'X',1,'Y','z')"""
        )
