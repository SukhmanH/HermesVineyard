"""Block registry intake: role-gated, validated, audited (vineyard_mcp/registry.py)."""

from __future__ import annotations

from vineyard_mcp.registry import update_block

OWNER = "+12505550004"  # role=manager in fixtures (manager passes the gate)
JUAN = "+15215550001"   # worker — must be refused


def _manager_db(db):
    """The fixture's 4th contact is a manager; promote nothing — use as-is."""
    return db


def test_worker_cannot_update_the_registry(db):
    out = update_block(db, "B1", {"acres": 4.0}, updated_by=JUAN)
    assert out["error"] == "forbidden_role"


def test_unknown_caller_refused(db):
    out = update_block(db, "B1", {"acres": 4.0}, updated_by="+19999999999")
    assert out["error"] == "unknown_caller"


def test_unknown_block_refused(db):
    out = update_block(db, "ZZ", {"acres": 4.0}, updated_by=OWNER)
    assert out["error"] == "unknown_block"


def test_unknown_field_refused(db):
    out = update_block(db, "B1", {"favourite_colour": "red"}, updated_by=OWNER)
    assert out["error"] == "unknown_fields"


def test_impossible_values_refused(db):
    for bad in ({"acres": -3}, {"acres": 0}, {"emitter_lph": 0},
                {"irrigation_type": "soaker"}, {"lat": 8.5}, {"row_count": -1}):
        out = update_block(db, "B1", bad, updated_by=OWNER)
        assert out["error"] == "invalid_value", bad


def test_valid_update_lands_and_is_audited(db):
    out = update_block(
        db, "B1",
        {"acres": 4.2, "variety": "Pinot Noir", "irrigation_type": "drip",
         "emitter_lph": 2.3, "vines_per_acre": 1210, "row_count": 48},
        updated_by=OWNER,
    )
    assert out["updated"] is True
    row = db.execute("SELECT acres, variety, irrigation_type, emitter_lph FROM blocks "
                     "WHERE code = 'B1'").fetchone()
    assert tuple(row) == (4.2, "Pinot Noir", "drip", 2.3)
    audit = db.execute(
        "SELECT actor, action, entity FROM audit_log WHERE action = 'block.updated'"
    ).fetchone()
    assert tuple(audit) == (OWNER, "block.updated", "blocks")


def test_partial_update_leaves_other_fields_alone(db):
    before = db.execute("SELECT variety FROM blocks WHERE code = 'B1'").fetchone()[0]
    update_block(db, "B1", {"acres": 5.5}, updated_by=OWNER)
    after = db.execute("SELECT variety, acres FROM blocks WHERE code = 'B1'").fetchone()
    assert after[0] == before and after[1] == 5.5


def test_deactivated_contact_cannot_update_the_registry(db):
    """active=1 must apply to BOTH identity columns.

    `wa_phone = ? OR wa_lid = ? AND active = 1` parses as `wa_phone = ? OR (wa_lid = ? AND
    active = 1)` — SQL binds AND tighter than OR — so a deactivated contact matched by phone
    sailed straight through the role gate and rewrote the registry.
    """
    db.execute("UPDATE contacts SET active = 0 WHERE wa_phone = ?", (OWNER,))
    db.commit()
    out = update_block(db, "B1", {"acres": 99.0}, updated_by=OWNER)
    assert out["error"] == "unknown_caller"
    assert db.execute("SELECT acres FROM blocks WHERE code = 'B1'").fetchone()[0] == 3.2


def test_blank_name_is_refused_not_raised(db):
    """blocks.name is NOT NULL; a blank must come back as a structured error, never as an
    IntegrityError escaping the kernel."""
    out = update_block(db, "B1", {"name": "   "}, updated_by=OWNER)
    assert out["error"] == "invalid_value"
    assert out["field"] == "name"
    assert db.execute("SELECT name FROM blocks WHERE code = 'B1'").fetchone()[0] == "Home South"


def test_blank_nullable_text_field_clears_it(db):
    """The nullable text fields may still be cleared — only `name` is load-bearing."""
    out = update_block(db, "B1", {"notes": "  "}, updated_by=OWNER)
    assert out["updated"] is True
    assert db.execute("SELECT notes FROM blocks WHERE code = 'B1'").fetchone()[0] is None
