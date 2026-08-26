"""Test fixtures: a fresh in-file database per test, seeded with known rows.

No LLM anywhere in this suite. Everything here must hold whether or not a model is running —
that is the entire point of the compliance kernel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vineyard_mcp import config as config_mod  # noqa: E402
from vineyard_mcp.db import connect, init_db, transaction  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A seeded database. sqlite needs a real file for WAL, so tmp_path not :memory:."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SETTINGS_PATH", str(Path(__file__).parent / "fixtures_settings.yaml"))
    config_mod.get_settings.cache_clear()

    conn = connect()
    init_db(conn)

    with transaction(conn):
        conn.executemany(
            """INSERT INTO contacts (wa_phone, full_name, short_name, lang, role,
                                     voice_replies, reports_in, consent_ts_utc)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                ("+15215550001", "Juan Perez", "Juan", "es", "worker", 1, "es",
                 "2026-01-01T00:00:00Z"),
                ("+15215550002", "Miguel Santos", "Miguel", "es", "worker", 0, "es",
                 "2026-01-01T00:00:00Z"),
                # The applicator: reads Gurmukhi, types spray reports in English (docs/01 §D11)
                ("+12505550003", "Gurpreet Singh", "Gurpreet", "pa", "worker", 0,
                 "en", "2026-01-01T00:00:00Z"),
                ("+12505550004", "Manager Name", "Manager", "en", "manager", 0, "en",
                 "2026-01-01T00:00:00Z"),
            ],
        )
        conn.executemany(
            "INSERT INTO blocks (code, name, site, acres, variety) VALUES (?,?,?,?,?)",
            [
                ("B1", "Home South", "penticton", 3.2, "Pinot Noir"),
                ("B3", "Home North", "penticton", 4.5, "Merlot"),
                ("N2", "Bench Upper", "naramata", 5.1, "Riesling"),
            ],
        )
        conn.executemany(
            """INSERT INTO products (trade_name, pcp_number, type, rei_hours, phi_days,
                                     max_temp_c, rainfast_hours, default_rate, rate_units,
                                     frac_group, target_pests, reapply_days, verified)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                # Verified: Hermes may state its REI. Same FRAC group as Kumulus, which is
                # what makes the rotation guard testable.
                ("Microthiol Disperss", "PCP-12345", "fungicide", 24, 0, 30.0, 4.0,
                 "8", "kg/ha", "M2", "powdery mildew", 10, 1),
                # Carries a label rate, for the over-application guard.
                ("Kumulus DF", "PCP-23456", "fungicide", 24, 0, 30.0, 4.0,
                 "6", "kg/ha", "M2", "powdery mildew", 10, 1),
                # Unverified: obligation 4 — Hermes must refuse to state an REI for this.
                ("Mystery Fungicide", None, "fungicide", 48, 7, None, None, None, None,
                 None, None, None, 0),
            ],
        )

    yield conn
    conn.close()
    config_mod.get_settings.cache_clear()


@pytest.fixture()
def juan() -> str:
    return "+15215550001"


@pytest.fixture()
def applicator() -> str:
    return "+12505550003"
