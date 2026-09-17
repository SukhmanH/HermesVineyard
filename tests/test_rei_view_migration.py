"""Direct SQL safety reads must retain unresolved re-entry restrictions."""
import sqlite3

import pytest

from vineyard_mcp.db import MIGRATIONS, migrate, schema_version

LEGACY_VIEW = """CREATE VIEW rei_active AS
SELECT s.id, s.block_id, b.code AS block_code, b.name AS block_name, b.site,
       s.product_name_raw, s.rei_expires_at_utc
FROM spray_log_current s JOIN blocks b ON b.id = s.block_id
WHERE s.rei_expires_at_utc IS NOT NULL
AND s.rei_expires_at_utc > strftime('%Y-%m-%dT%H:%M:%SZ','now')"""


def seed(db, expiry=None, corrects=None):
    return db.execute(
        "INSERT INTO spray_log (log_date,start_time,block_id,product_name_raw,"
        "raw_message,acres_treated,applicator_contact_id,applicator_name,"
        "rei_expires_at_utc,corrects_log_id) "
        "VALUES ('2026-09-01','06:00',(SELECT id FROM blocks WHERE code='B1'),"
        "'Legacy Sulfur','original words',1,(SELECT id FROM contacts LIMIT 1),"
        "'Worker',?,?)", (expiry, corrects),
    ).lastrowid


def active_ids(db):
    return {row['id'] for row in db.execute('SELECT * FROM rei_active')}


def legacy(db):
    db.execute('DROP VIEW rei_active')
    db.execute(LEGACY_VIEW)
    db.execute('DELETE FROM schema_version')
    db.execute('INSERT INTO schema_version (version) VALUES (5)')


def test_fresh_view_keeps_unknown_and_active_not_expired_or_superseded(db):
    unknown = seed(db)
    active = seed(db, '2999-01-01T00:00:00Z')
    seed(db, '2000-01-01T00:00:00Z')
    superseded = seed(db)
    seed(db, '2000-01-01T00:00:00Z', superseded)
    assert active_ids(db) == {unknown, active}


def test_upgrade_keeps_records_and_is_repeatable(db):
    legacy(db)
    unknown = seed(db)
    before = [tuple(row) for row in db.execute('SELECT * FROM spray_log')]
    assert active_ids(db) == set()
    assert 6 in migrate(db)
    assert schema_version(db) >= 6
    assert active_ids(db) == {unknown}
    assert migrate(db) == []
    assert [tuple(row) for row in db.execute('SELECT * FROM spray_log')] == before
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        db.execute("UPDATE spray_log SET raw_message='changed'")


def test_view_migration_rolls_back_on_failure(db, monkeypatch):
    legacy(db)
    monkeypatch.setitem(MIGRATIONS, 6, [
        'DROP VIEW rei_active', 'THIS IS NOT VALID SQL',
    ])
    with pytest.raises(sqlite3.OperationalError):
        migrate(db)
    assert schema_version(db) == 5
    assert db.execute("SELECT name FROM sqlite_master WHERE name='rei_active'").fetchone()
