"""SQLite access. WAL, foreign keys on, rows as dicts.

The append-only guarantee lives in schema.sql triggers, not here — deliberately. A guarantee
enforced by application code is a guarantee that a future caller can bypass; one enforced by
RAISE(ABORT) cannot be talked past by an agent, a prompt injection, or a hurried maintainer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, get_settings

SCHEMA_VERSION = 5
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def utcnow() -> str:
    """UTC ISO-8601, second precision. The only clock this kernel trusts."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit; we manage transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # REPLACE performs an implicit DELETE; it must fire the append-only triggers too.
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction. A compliance commit is one atomic unit or it is nothing."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def is_initialized(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spray_log'"
    ).fetchone()
    return row is not None


def init_db(conn: sqlite3.Connection) -> bool:
    """Apply schema.sql if the database is fresh. Returns True if it applied.

    Never re-applies over an existing database: this file is the system of record and a
    surprise DROP would be unrecoverable.
    """
    if is_initialized(conn):
        return False

    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    return True


# ── Migrations ────────────────────────────────────────────────────────────────
# Once there is a real compliance record, the database can never be dropped and rebuilt: those
# rows are the legal artifact and there is no re-import. So schema changes arrive as additive
# migrations. Additive only, deliberately - no column is ever dropped or retyped here, because
# a migration that loses data is indistinguishable from the append-only violation the triggers
# exist to prevent.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        # Advisory support (docs/01 §D12): grounded recommendations need resistance groups,
        # what each product is registered for, and its reapplication interval.
        "ALTER TABLE products ADD COLUMN frac_group TEXT",
        "ALTER TABLE products ADD COLUMN target_pests TEXT",
        "ALTER TABLE products ADD COLUMN reapply_days INTEGER",
        """CREATE TABLE IF NOT EXISTS block_season (
             id               INTEGER PRIMARY KEY,
             block_id         INTEGER NOT NULL REFERENCES blocks(id),
             season_year      INTEGER NOT NULL,
             budbreak_date    TEXT,
             bloom_date       TEXT,
             veraison_date    TEXT,
             expected_harvest TEXT,
             notes            TEXT,
             UNIQUE (block_id, season_year)
           )""",
    ],
    4: [
        # WhatsApp identifies a sender by a device-linked "lid" (e.g. "143976027939069@lid"),
        # which is NOT the E.164 phone number in wa_phone. Found live 2026-08-22: the gateway
        # logged inbound messages as user=Sukhman chat=...@lid, and there was no column to match
        # that against - so a contact lookup by phone would have found nothing even if Hermes
        # had thought to try. Nullable and unique: most contacts will not have one until they
        # message in at least once.
        "ALTER TABLE contacts ADD COLUMN wa_lid TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_lid ON contacts (wa_lid) "
        "WHERE wa_lid IS NOT NULL",
    ],
    3: [
        # Fruit maturity against winery contract targets, and irrigation attributes (§D13).
        "ALTER TABLE blocks ADD COLUMN soil_type TEXT",
        "ALTER TABLE blocks ADD COLUMN irrigation_type TEXT",
        "ALTER TABLE blocks ADD COLUMN emitter_lph REAL",
        "ALTER TABLE blocks ADD COLUMN emitters_per_vine REAL",
        "ALTER TABLE blocks ADD COLUMN vines_per_acre INTEGER",
        """CREATE TABLE IF NOT EXISTS fruit_targets (
             id INTEGER PRIMARY KEY,
             block_id INTEGER NOT NULL REFERENCES blocks(id),
             season_year INTEGER NOT NULL,
             winery TEXT,
             target_brix_min REAL, target_brix_max REAL,
             target_ta_min REAL, target_ta_max REAL,
             target_ph_min REAL, target_ph_max REAL,
             harvest_window_from TEXT, harvest_window_to TEXT,
             contract_notes TEXT,
             UNIQUE (block_id, season_year, winery)
           )""",
        """CREATE TABLE IF NOT EXISTS fruit_samples (
             id INTEGER PRIMARY KEY,
             block_id INTEGER NOT NULL REFERENCES blocks(id),
             sampled_on TEXT NOT NULL,
             brix REAL, ta_g_l REAL, ph REAL, berry_weight_g REAL, sample_size INTEGER,
             sampled_by_contact_id INTEGER REFERENCES contacts(id),
             method TEXT, notes TEXT, raw_message TEXT,
             created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
             corrects_sample_id INTEGER REFERENCES fruit_samples(id)
           )""",
        """CREATE TRIGGER IF NOT EXISTS trg_sample_no_update BEFORE UPDATE ON fruit_samples
           BEGIN SELECT RAISE(ABORT, 'fruit_samples is append-only; insert a correction row');
           END""",
        """CREATE TRIGGER IF NOT EXISTS trg_sample_no_delete BEFORE DELETE ON fruit_samples
           BEGIN SELECT RAISE(ABORT, 'fruit_samples is append-only'); END""",
        "CREATE INDEX IF NOT EXISTS idx_sample_block ON fruit_samples (block_id, sampled_on)",
        """CREATE VIEW IF NOT EXISTS fruit_samples_current AS
             SELECT * FROM fruit_samples f
             WHERE NOT EXISTS (SELECT 1 FROM fruit_samples c WHERE c.corrects_sample_id = f.id)""",
    ],
    5: [
        # Weather history: one measured day per site. Feeds season-over-season GDD comparisons
        # and mildew-model validation. Upsert by (site, obs_date) - weather actuals are
        # correctable data, not compliance records; the latest measurement wins.
        """CREATE TABLE IF NOT EXISTS daily_obs (
             id INTEGER PRIMARY KEY,
             site TEXT NOT NULL,
             obs_date TEXT NOT NULL,
             tmax_c REAL,
             tmin_c REAL,
             precip_mm REAL,
             source TEXT NOT NULL,
             fetched_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
             UNIQUE (site, obs_date)
           )""",
        "CREATE INDEX IF NOT EXISTS idx_daily_obs_site ON daily_obs (site, obs_date)",
    ],
}


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply any migrations newer than the recorded version. Returns those applied.

    Each statement is tolerant of already having been applied, so re-running is safe and a
    half-finished upgrade can be resumed rather than needing a restore.
    """
    current = schema_version(conn) or 0
    applied: list[int] = []
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        for statement in MIGRATIONS[version]:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column" in str(exc).lower() or "already exists" in str(exc).lower():
                    continue
                raise
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        applied.append(version)
    return applied


def schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row["version"] if row else None
    except sqlite3.OperationalError:
        return None


def audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    detail_json: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO audit_log (at_utc, actor, action, entity, entity_id, detail_json)
           VALUES (?,?,?,?,?,?)""",
        (utcnow(), actor, action, entity, entity_id, detail_json),
    )
    return int(cur.lastrowid)


