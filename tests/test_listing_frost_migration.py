"""Migration 8: listing_frost and listings.pid, added without touching existing rows."""
import sqlite3

import pytest

from vineyard_mcp.db import MIGRATIONS, migrate, schema_version


def listing(db, key="mls-10398703"):
    db.execute("INSERT INTO listings (dedupe_key, mls_number, source, title, price, acres, "
               "address, area, url, first_seen_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (key, key[4:], "mls-email", "294 Road 18, Oliver", 1299900, 9.5,
                "294 Road 18, Oliver", "Oliver", "https://example/294", "2026-10-01T00:00:00Z"))


def frost_row(db, status="submitted", supersedes=None):
    return db.execute(
        "INSERT INTO listing_frost (dedupe_key, model_version, status, supersedes_id) "
        "VALUES ('mls-10398703', 'v2+z1', ?, ?)", (status, supersedes)).lastrowid


def legacy(db):
    """The schema as it stood at version 7: no listing_frost, no listings.pid."""
    db.execute("DROP VIEW listing_frost_current")
    db.execute("DROP TABLE listing_frost")
    db.execute("ALTER TABLE listings DROP COLUMN pid")
    db.execute("DELETE FROM schema_version")
    db.execute("INSERT INTO schema_version (version) VALUES (7)")


def test_a_fresh_database_has_the_frost_table_and_listing_pids(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(listings)")}
    assert "pid" in cols
    assert db.execute("SELECT COUNT(*) FROM listing_frost").fetchone()[0] == 0
    assert schema_version(db) == 8


def test_upgrade_keeps_listings_and_is_repeatable(db):
    legacy(db)
    listing(db)
    before = [tuple(r) for r in db.execute("SELECT * FROM listings")]
    assert migrate(db) == [8]
    assert schema_version(db) == 8
    after = [tuple(r) for r in db.execute("SELECT * FROM listings")]
    assert [row[:-1] for row in after] == before and after[0][-1] is None   # pid NULL
    assert migrate(db) == []
    frost_row(db)
    assert db.execute("SELECT status FROM listing_frost").fetchone()[0] == "submitted"


def test_a_scored_row_is_history(db):
    """Rows move through the API's statuses until scored; then they never change."""
    rid = frost_row(db)
    db.execute("UPDATE listing_frost SET status='analyzing' WHERE id=?", (rid,))
    db.execute("UPDATE listing_frost SET status='done', frost_score=81.2 WHERE id=?", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="history"):
        db.execute("UPDATE listing_frost SET frost_score=90 WHERE id=?", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM listing_frost WHERE id=?", (rid,))
    newer = frost_row(db, supersedes=rid)          # a corrected parcel supersedes it
    current = [r["id"] for r in db.execute("SELECT id FROM listing_frost_current")]
    assert current == [newer]


def test_unknown_statuses_are_refused(db):
    with pytest.raises(sqlite3.IntegrityError):
        frost_row(db, status="frost free")


def test_migration_rolls_back_on_failure(db, monkeypatch):
    legacy(db)
    monkeypatch.setitem(MIGRATIONS, 8, ["ALTER TABLE listings ADD COLUMN pid TEXT",
                                        "THIS IS NOT VALID SQL"])
    with pytest.raises(sqlite3.OperationalError):
        migrate(db)
    assert schema_version(db) == 7
    assert "pid" not in {r["name"] for r in db.execute("PRAGMA table_info(listings)")}
