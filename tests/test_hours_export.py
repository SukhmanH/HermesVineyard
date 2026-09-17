"""Exercise real export CLI against fixture data only."""
import os
import subprocess
import sys
from pathlib import Path

import openpyxl
from test_worker_hours import commit, task

from vineyard_mcp.compliance import draft_correction, draft_task_log


def test_hours_cli_exports_current_individual_values_and_gaps(db, juan, tmp_path):
    original = commit(db, juan, task(db, juan, notes="=1+1"))
    corrected = draft_correction(db, "task_log", original["id"], {
        "wa_phone": juan, "hours_total": 8,
        "worker_hours": [{"contact_id": 1, "hours": 3}, {"contact_id": 2, "hours": 5}],
    })
    commit(db, juan, corrected)
    commit(db, juan, draft_task_log(db, juan, {
        "task_type": "poda", "log_date": "2026-09-02", "hours_total": 7}, "fixture"))
    path = db.execute("PRAGMA database_list").fetchone()[2]
    before = list(db.iterdump())
    env = dict(os.environ, DB_PATH=path, EXPORT_DIR=str(tmp_path / 'exports'),
               BACKUP_DIR=str(tmp_path / 'backups'))
    result = subprocess.run([sys.executable, 'tools/build_exports.py',
        '--hours-from', '2026-09-01', '--hours-to', '2026-09-07'],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    wb = openpyxl.load_workbook(tmp_path / 'exports/hours-2026-09-01-to-2026-09-07.xlsx')
    rows = list(wb['entries'].values)
    headers = rows[0]
    records = [dict(zip(headers, r, strict=True)) for r in rows[1:]]
    assert [r['hours'] for r in records] == [3, 5, None]
    assert records[-1]['status'] == 'MISSING_INDIVIDUAL_HOURS'
    assert records[0]['notes'] == '=1+1'
    assert all(c.data_type != 'f' for sheet in wb for row in sheet for c in row)
    totals = list(wb['worker_totals'].values)
    assert totals[1][2:] == (3, 'INCOMPLETE')
    assert totals[2][2:] == (5, 'RECORDED_HOURS_ONLY')
    assert list(db.iterdump()) == before
    assert not (tmp_path / 'backups').exists()
    wb.close()


def test_legacy_schema_exports_missing_not_inferred(db, juan, tmp_path, monkeypatch):
    from tools import build_exports as exports
    commit(db, juan, draft_task_log(db, juan, {
        "task_type": "poda", "log_date": "2026-09-01", "hours_total": 8}, "fixture"))
    db.execute("ALTER TABLE task_workers DROP COLUMN hours")
    monkeypatch.setattr(exports, "DB_PATH", db.execute("PRAGMA database_list").fetchone()[2])
    output = tmp_path / 'legacy.xlsx'
    assert exports.build_hours_period(str(output), '2026-09-01', '2026-09-07') == 1
    wb = openpyxl.load_workbook(output)
    assert wb['entries']['F2'].value is None
    assert wb['entries']['H2'].value == 'MISSING_INDIVIDUAL_HOURS'
    wb.close()


def test_hours_cli_rejects_ambiguous_period_before_writing(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, EXPORT_DIR=str(tmp_path / 'exports'),
               DB_PATH=str(tmp_path / 'must-not-create.db'))
    for args in [ ['--hours-from', '2026-09-01'],
                  ['--hours-from', '2026-09-08', '--hours-to', '2026-09-01'],
                  ['--hours-from', '2026-02-30', '--hours-to', '2026-09-01'] ]:
        result = subprocess.run([sys.executable, 'tools/build_exports.py', *args],
            cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 2
    assert not (tmp_path / 'exports').exists()
    assert not (tmp_path / 'must-not-create.db').exists()
