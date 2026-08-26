"""Admin CLI: init-db, import-seed, doctor.

    python -m vineyard_mcp init-db
    python -m vineyard_mcp import-seed seed/
    python -m vineyard_mcp doctor
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .config import get_settings
from .db import connect, init_db, is_initialized, migrate, schema_version, transaction

SEED_FILES = {
    "blocks.csv": (
        "blocks",
        ["code", "name", "site", "acres", "variety", "row_count", "lat", "lon", "notes"],
    ),
    "contacts.csv": (
        "contacts",
        ["wa_phone", "full_name", "short_name", "lang", "role",
         "voice_replies", "reports_in"],
    ),
    # Loaded AFTER blocks, so block_code can resolve. Handled specially below.
    "fruit_targets.csv": (
        "fruit_targets",
        ["block_code", "season_year", "winery", "target_brix_min", "target_brix_max",
         "target_ta_min", "target_ta_max", "target_ph_min", "target_ph_max",
         "harvest_window_from", "harvest_window_to", "contract_notes"],
    ),
    "products.csv": (
        "products",
        ["trade_name", "pcp_number", "type", "rei_hours", "phi_days", "max_temp_c",
         "rainfast_hours", "default_rate", "rate_units", "frac_group", "target_pests",
         "reapply_days", "notes"],
    ),
}


# Columns that may be refreshed from a CSV on an existing row. Everything a HUMAN established
# by reading a physical label is EXCLUDED - verified, rei_hours, phi_days, pcp_number. A CSV
# re-import must never be able to silently undo a verification or overwrite a label value with
# whatever a spreadsheet happened to contain.
UPDATABLE = {
    "products": ["type", "max_temp_c", "rainfast_hours", "default_rate", "rate_units",
                 "frac_group", "target_pests", "reapply_days", "notes"],
    "blocks": ["name", "site", "acres", "variety", "row_count", "lat", "lon", "notes"],
    "contacts": ["full_name", "short_name", "lang", "role", "voice_replies", "reports_in"],
}
KEY = {"products": "trade_name", "blocks": "code", "contacts": "wa_phone"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def cmd_init_db(_: argparse.Namespace) -> int:
    conn = connect()
    created = init_db(conn)
    settings = get_settings()
    if created:
        print(f"Initialized schema v{schema_version(conn)} at {settings.db_path}")
        return 0

    # Existing database: upgrade in place. Never drop and rebuild - once there is a real
    # compliance record those rows are the legal artifact and there is no re-import.
    applied = migrate(conn)
    if applied:
        print(f"Migrated to schema v{schema_version(conn)} "
              f"(applied {', '.join('v' + str(a) for a in applied)}) at {settings.db_path}")
    else:
        print(f"Already at schema v{schema_version(conn)} at {settings.db_path}")
    return 0


def cmd_import_seed(args: argparse.Namespace) -> int:
    seed_dir = Path(args.directory)
    if not seed_dir.is_dir():
        print(f"No such directory: {seed_dir}", file=sys.stderr)
        return 2

    conn = connect()
    if not is_initialized(conn):
        print("Database not initialized - run 'init-db' first.", file=sys.stderr)
        return 2

    total = 0
    for filename, (table, columns) in SEED_FILES.items():
        path = seed_dir / filename
        if not path.exists():
            print(f"  skip {filename} (not present)")
            continue

        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))

        # fruit_targets keys on a block CODE in the CSV but a block_id in the table.
        resolve_block_id = table == "fruit_targets"

        inserted = 0
        updated = 0
        before_changes = conn.total_changes
        with transaction(conn):
            for row in rows:
                values = [_clean(row.get(c)) for c in columns]
                if all(v is None for v in values):
                    continue

                cols = list(columns)
                if resolve_block_id:
                    code = _clean(row.get("block_code"))
                    found = conn.execute(
                        "SELECT id FROM blocks WHERE code = ?", (code,)
                    ).fetchone()
                    if found is None:
                        print(f"    ! skipping {filename} row: unknown block {code!r}")
                        continue
                    cols = ["block_id"] + [c for c in columns if c != "block_code"]
                    values = [found["id"]] + [
                        _clean(row.get(c)) for c in columns if c != "block_code"
                    ]
                columns_sql = cols
                placeholders = ",".join("?" for _ in columns_sql)
                # INSERT OR IGNORE: re-running a seed import must be safe. Updating existing
                # rows is deliberately NOT done here — products carry a `verified` flag a human
                # set, and a careless re-import must never silently reset it.
                conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({','.join(columns_sql)}) "
                    f"VALUES ({placeholders})",
                    values,
                )
                inserted += 1

                if args.update and not resolve_block_id                         and conn.total_changes == before_changes:
                    # Row already existed. Refresh only the catalogue columns; never the ones
                    # a human set by reading a label.
                    cols = [c for c in UPDATABLE[table] if c in columns]
                    sets = ", ".join(f"{c} = ?" for c in cols)
                    vals = [_clean(row.get(c)) for c in cols] + [_clean(row.get(KEY[table]))]
                    conn.execute(f"UPDATE {table} SET {sets} WHERE {KEY[table]} = ?", vals)
                    updated += 1
                before_changes = conn.total_changes
        print(f"  {filename}: {inserted} rows processed"
              + (f", {updated} updated" if updated else ""))
        total += inserted

    print(f"Seed import done ({total} rows).")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    settings = get_settings()
    problems: list[str] = []

    print(f"DB path        : {settings.db_path}")
    print(f"Timezone       : {settings.timezone}")

    if not settings.db_path.exists():
        problems.append("database file does not exist - run 'init-db'")
        print("Schema version : (no database)")
    else:
        conn = connect()
        version = schema_version(conn)
        print(f"Schema version : {version}")
        if version is None:
            problems.append("schema_version missing - database may be partially initialized")

        counts = {}
        for table in ("contacts", "blocks", "products", "spray_log", "task_log",
                      "drafts", "audit_log", "listings", "weather_cache"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            except Exception as exc:  # noqa: BLE001 - report, don't crash the doctor
                counts[table] = f"ERROR: {exc}"
                problems.append(f"table {table} unreadable: {exc}")
        print("Row counts     :")
        for table, count in counts.items():
            print(f"                 {table:<14} {count}")

        for table, label in (("contacts", "contacts"), ("blocks", "blocks"),
                             ("products", "products")):
            if counts.get(table) == 0:
                problems.append(f"no {label} seeded - run 'import-seed'")

        unverified = conn.execute(
            "SELECT COUNT(*) c FROM products WHERE verified = 0"
        ).fetchone()["c"]
        if unverified:
            # Not an error: it is the correct state before someone reads the labels. But it is
            # the thing that will make Hermes answer "ask your manager" all season, so say it.
            print(f"\n  {unverified} product(s) UNVERIFIED - Hermes will refuse to state their")
            print("  re-entry intervals until a human checks the physical label (obligation 4).")

        from .templates import check as check_templates
        tmpl_problems = check_templates()
        if tmpl_problems:
            problems.extend(tmpl_problems)
        else:
            print()
            print("  Templates: es/en/pa present, all safety messages covered.")

        if not settings.sites:
            problems.append("no sites configured in config/settings.yaml")
        else:
            missing_codes = [s.key for s in settings.sites if not s.eccc_citypage]
            if missing_codes:
                problems.append(
                    f"sites missing eccc_citypage: {', '.join(missing_codes)}"
                )

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nAll checks passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vineyard_mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the schema if the database is fresh")

    seed = sub.add_parser("import-seed", help="load blocks/contacts/products CSVs")
    seed.add_argument("directory", nargs="?", default="seed")
    seed.add_argument("--update", action="store_true",
                      help="also refresh catalogue columns on existing rows. "
                           "Never touches verified / rei_hours / phi_days / pcp_number.")

    sub.add_parser("doctor", help="report configuration and database health")

    args = parser.parse_args(argv)
    return {
        "init-db": cmd_init_db,
        "import-seed": cmd_import_seed,
        "doctor": cmd_doctor,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
