#!/usr/bin/env python3
"""Nightly export builder for vineyard ops.

Rebuilds the current-view workbooks (spray_log.xlsx, task_log.xlsx) from the
append-only SQLite kernel, runs an online SQLite .backup, snapshots the
WhatsApp session dir, and applies the retention rotation. Pure stdlib + openpyxl.
"""
from __future__ import annotations

import os
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")


def _path(env: str, default: str) -> str:
    """Honour the same env vars as vineyard_mcp.config; relative resolves against the repo."""
    raw = os.environ.get(env) or default
    return raw if os.path.isabs(raw) else os.path.join(REPO, raw)


EXPORT_DIR = _path("EXPORT_DIR", os.path.join("data", "exports"))
ARCHIVE_DIR = os.path.join(EXPORT_DIR, "archive")
BACKUP_DIR = _path("BACKUP_DIR", os.path.join("data", "backups"))
DB_PATH = _path("DB_PATH", os.path.join("data", "hermes.db"))

# The WhatsApp session dir differs per host: ~/.hermes/platforms/whatsapp on the Ubuntu box,
# LOCALAPPDATA on the Windows build machine. Resolve it rather than pinning one developer's
# home directory - this backup is the thing that saves a re-pair.
def _wa_session() -> str | None:
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    candidates = [
        os.environ.get("WA_SESSION_DIR"),
        os.path.join(home, "platforms", "whatsapp"),
        os.path.join(local, "hermes", "whatsapp"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


WA_SESSION = _wa_session()

# Local wall-clock, DST included. A fixed -7 offset silently misdates every run from November
# to March, and the stamp is what the archive filenames and retention are keyed on.
TZ = ZoneInfo(os.environ.get("TZ") or "America/Vancouver")
NOW = datetime.now(TZ)
STAMP = NOW.strftime("%Y%m%d_%H%M%S")
DATE = NOW.strftime("%Y-%m-%d")

# Retention windows.
KEEP_NIGHTLY = 14   # dated workbook archives
KEEP_DB_BAK = 14    # sqlite .backup copies
KEEP_WA_BAK = 7     # whatsapp session snapshots

FAILED = []


def log(msg: str) -> None:
    print(msg, flush=True)


def conn_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


# --------------------------------------------------------------------------- #
# Workbook builders
# --------------------------------------------------------------------------- #
def _style_header(ws) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    fill = PatternFill("solid", fgColor="1F4E37")
    font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28


def _widths(ws, ncols: int) -> None:
    # Reasonable defaults; raw_message gets wider.
    for c in range(1, ncols + 1):
        letter = ws.cell(row=1, column=c).column_letter
        header = str(ws.cell(row=1, column=c).value or "")
        ws.column_dimensions[letter].width = 40 if "raw" in header.lower() else 16


def build_spray(path: str) -> int:
    import openpyxl

    q = """
        SELECT s.id, s.log_date, s.start_time, s.end_time,
               b.code, b.name, b.site, s.acres_treated,
               s.product_name_raw, p.trade_name, s.pcp_number,
               s.rate_value, s.rate_units, s.total_amount, s.total_units,
               s.target_pest, s.method,
               s.applicator_name, s.applicator_contact_id,
               s.wind_kmh, s.wind_dir, s.temp_c, s.rh_pct, s.sky, s.weather_source,
               s.rei_hours, s.rei_expires_at_utc, s.phi_days,
               s.notes, s.raw_message, s.confirmed_by_reply, s.created_at_utc
        FROM spray_log_current s
        LEFT JOIN blocks b ON b.id = s.block_id
        LEFT JOIN products p ON p.id = s.product_id
        ORDER BY s.log_date DESC, s.start_time DESC
    """
    cols = ["id", "log_date", "start_time", "end_time", "block_code", "block_name",
            "site", "acres_treated", "product_name_raw", "product_trade_name",
            "pcp_number", "rate_value", "rate_units", "total_amount", "total_units",
            "target_pest", "method", "applicator_name", "applicator_contact_id",
            "wind_kmh", "wind_dir", "temp_c", "rh_pct", "sky", "weather_source",
            "rei_hours", "rei_expires_at_utc", "phi_days", "notes", "raw_message",
            "confirmed_by_reply", "created_at_utc"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "spray_log"
    ws.append(cols)
    with closing(conn_ro()) as c:
        for row in c.execute(q):
            ws.append(list(row))
    _style_header(ws)
    _widths(ws, len(cols))
    wb.save(path)
    return ws.max_row - 1


def build_task(path: str) -> int:
    import openpyxl

    q = """
        SELECT t.id, t.log_date, t.task_type,
               b.code, b.name, b.site,
               t.hours_total, t.quantity, t.quantity_unit,
               t.start_time, t.end_time, t.notes,
               t.raw_message, t.confirmed_by_reply, t.created_at_utc,
               (SELECT GROUP_CONCAT(ct.short_name, ', ')
                  FROM task_workers tw JOIN contacts ct ON ct.id = tw.contact_id
                 WHERE tw.task_log_id = t.id) AS workers
        FROM task_log_current t
        LEFT JOIN blocks b ON b.id = t.block_id
        ORDER BY t.log_date DESC, t.start_time DESC
    """
    cols = ["id", "log_date", "task_type", "block_code", "block_name", "site",
            "hours_total", "quantity", "quantity_unit", "start_time", "end_time",
            "notes", "raw_message", "confirmed_by_reply", "created_at_utc", "workers"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "task_log"
    ws.append(cols)
    with closing(conn_ro()) as c:
        for row in c.execute(q):
            ws.append(list(row))
    _style_header(ws)
    _widths(ws, len(cols))
    wb.save(path)
    return ws.max_row - 1


def _append_literal(ws, values):
    """Keep worker-supplied strings as text, never executable Excel formulas."""
    from openpyxl.cell import WriteOnlyCell

    cells = []
    for value in values:
        cell = WriteOnlyCell(ws, value=value)
        if isinstance(value, str):
            cell.data_type = "s"
        cells.append(cell)
    ws.append(cells)


def build_compliance_month(path: str, year: int, month: int) -> int:
    """Export all raw monthly spray records and their immediate correction links."""
    import openpyxl

    local = ZoneInfo("America/Vancouver")
    start = datetime(year, month, 1, tzinfo=local)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=local)
    utc = ZoneInfo("UTC")
    lo, hi = (d.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ") for d in (start, end))
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "spray_log"
    with closing(conn_ro()) as c:
        c.execute("BEGIN")  # both sheets reflect one consistent read-only snapshot
        cur = c.execute(
            """SELECT s.*, b.code AS block_code, b.name AS block_name,
                      (SELECT GROUP_CONCAT(id, ',') FROM
                        (SELECT c.id FROM spray_log c
                         WHERE c.corrects_log_id=s.id ORDER BY c.id)) AS "SUPERSEDED-BY"
               FROM spray_log s LEFT JOIN blocks b ON b.id=s.block_id
               WHERE s.log_date >= ? AND s.log_date < ? ORDER BY s.log_date, s.id""",
            (start.date().isoformat(), end.date().isoformat()),
        )
        _append_literal(ws, [d[0] for d in cur.description])
        count = 0
        for row in cur:
            _append_literal(ws, row)
            count += 1
        audit = wb.create_sheet("audit_log")
        cur = c.execute("SELECT * FROM audit_log WHERE at_utc >= ? AND at_utc < ? "
                        "ORDER BY at_utc, id", (lo, hi))
        _append_literal(audit, [d[0] for d in cur.description])
        for row in cur:
            _append_literal(audit, row)
    for sheet in (ws, audit):
        _style_header(sheet)
        _widths(sheet, sheet.max_column)
        sheet.auto_filter.ref = sheet.dimensions
    meta = wb.create_sheet("metadata")
    for row in [("period", start.strftime("%Y-%m")), ("timezone", "America/Vancouver"),
                ("spray_records", count), ("audit_records", audit.max_row - 1),
                ("status", "records exported" if count else "no spray records"),
                ("correction_links", "Immediate correction IDs, including outside this month"),
                ("generated_at_utc", datetime.now(utc).isoformat())]:
        _append_literal(meta, row)
    wb.save(path)
    wb.close()
    return count


# --------------------------------------------------------------------------- #
# SQLite online backup
# --------------------------------------------------------------------------- #
def backup_db() -> str:
    dest = os.path.join(BACKUP_DIR, f"hermes.db.bak.{STAMP}")
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)  # the SQLite .backup command, online-safe
        finally:
            dst.close()
    finally:
        src.close()
    return dest


# --------------------------------------------------------------------------- #
# WhatsApp session snapshot
# --------------------------------------------------------------------------- #
def backup_whatsapp() -> str:
    if not WA_SESSION:
        # Silently zipping nothing is the failure mode that looks healthy right up until the
        # day you need the session back and find 7 empty archives.
        raise FileNotFoundError(
            "no WhatsApp session dir found (set WA_SESSION_DIR, or HERMES_HOME)"
        )
    dest = os.path.join(BACKUP_DIR, f"whatsapp-session-{STAMP}.zip")
    written = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(WA_SESSION):
            for f in files:
                fp = os.path.join(root, f)
                z.write(fp, os.path.relpath(fp, WA_SESSION))
                written += 1
    if written == 0:
        os.remove(dest)
        raise FileNotFoundError(f"WhatsApp session dir is empty: {WA_SESSION}")
    return dest


# --------------------------------------------------------------------------- #
# Retention rotation
# --------------------------------------------------------------------------- #
def _prune(glob_pattern: str, keep: int, label: str) -> None:
    import glob

    files = sorted(glob.glob(glob_pattern), key=os.path.getmtime, reverse=True)
    for old in files[keep:]:
        try:
            os.remove(old)
            log(f"  pruned {os.path.basename(old)}")
        except OSError as e:
            FAILED.append(f"prune {old}: {e}")
    log(f"  {label}: kept {min(len(files), keep)} of {len(files)}")


def rotate() -> None:
    log("Rotation:")
    _prune(os.path.join(ARCHIVE_DIR, "spray_log-*.xlsx"), KEEP_NIGHTLY, "nightly spray")
    _prune(os.path.join(ARCHIVE_DIR, "task_log-*.xlsx"), KEEP_NIGHTLY, "nightly task")
    _prune(os.path.join(BACKUP_DIR, "hermes.db.bak.*"), KEEP_DB_BAK, "db backups")
    _prune(os.path.join(BACKUP_DIR, "whatsapp-session-*.zip"), KEEP_WA_BAK, "wa snapshots")


# --------------------------------------------------------------------------- #
def main() -> int:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)

    log(f"Nightly exports {DATE} ({STAMP})")
    log("— spray workbook")
    try:
        n = build_spray(os.path.join(EXPORT_DIR, "spray_log.xlsx"))
        build_spray(os.path.join(ARCHIVE_DIR, f"spray_log-{STAMP}.xlsx"))
        log(f"  spray_log.xlsx: {n} rows")
    except Exception as e:  # noqa
        FAILED.append(f"spray workbook: {e}")
        log(f"  FAIL spray: {e}")

    log("— task workbook")
    try:
        n = build_task(os.path.join(EXPORT_DIR, "task_log.xlsx"))
        build_task(os.path.join(ARCHIVE_DIR, f"task_log-{STAMP}.xlsx"))
        log(f"  task_log.xlsx: {n} rows")
    except Exception as e:  # noqa
        FAILED.append(f"task workbook: {e}")
        log(f"  FAIL task: {e}")

    log("— sqlite .backup")
    try:
        d = backup_db()
        log(f"  {os.path.basename(d)}")
    except Exception as e:  # noqa
        FAILED.append(f"db backup: {e}")
        log(f"  FAIL db backup: {e}")

    log("— whatsapp session backup")
    try:
        w = backup_whatsapp()
        log(f"  {os.path.basename(w)}")
    except Exception as e:  # noqa
        FAILED.append(f"wa backup: {e}")
        log(f"  FAIL wa backup: {e}")

    rotate()

    if FAILED:
        log("FAILURES:")
        for f in FAILED:
            log(f"  - {f}")
        return 1
    log("OK — all nightly exports complete")
    return 0


def cli() -> int:
    import argparse
    import re

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compliance-month", metavar="YYYY-MM",
                        help="Export a historical calendar month; no backups or rotation")
    args = parser.parse_args()
    if args.compliance_month is None:
        return main()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", args.compliance_month):
        parser.error("month must be YYYY-MM")
    year, month = map(int, args.compliance_month.split("-"))
    try:
        datetime(year, month, 1)
        # The builder needs the exclusive next-month boundary too.
        datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    except ValueError:
        parser.error("invalid calendar month")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, f"compliance-{args.compliance_month}.xlsx")
    count = build_compliance_month(path, year, month)
    log(f"{path}: {count} spray records (includes superseded records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
