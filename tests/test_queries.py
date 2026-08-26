"""Reads, job bookkeeping, and get_situation.

The job tests matter more than they look: idempotence and the skip/fail distinction are what
stop a restarted process sending a second morning brief, and what stop "nothing needed doing"
from being indistinguishable from "the job crashed".
"""

from __future__ import annotations

from datetime import UTC

from vineyard_mcp.compliance import (
    commit_spray_log,
    draft_spray_log,
    present_confirmation,
)
from vineyard_mcp.queries import (
    cache_weather,
    get_situation,
    job_finish,
    job_start,
    log_decision,
    log_message,
    query_logs,
    recent_decisions,
    rei_active,
    skip_job,
)


def _commit_spray(db, token, reply="si, esta bien"):
    """Full gate: present the card, then commit with the worker's words."""
    present_confirmation(db, token)
    return commit_spray_log(db, token, reply)


SPRAY = {
    "wind_kmh": 8,          # BC requires prevailing weather on the record
    "temp_c": 18,
    "product_name_raw": "Microthiol Disperss",
    "block_code": "B3",
    "start_time": "06:00",
    "end_time": "08:00",
    "rate_value": 8,
    "rate_units": "kg/ha",
}


def _spray(db, juan, **over):
    out = draft_spray_log(db, juan, {**SPRAY, **over}, raw_message="x")
    return _commit_spray(db, out["confirm_token"])


# ── Job idempotence ──────────────────────────────────────────────────────────

def test_a_job_runs_once_per_local_date(db):
    first = job_start(db, "morning_brief", "2026-05-14")
    assert first["proceed"] is True
    job_finish(db, "morning_brief", ok=True, summary="sent", local_date="2026-05-14")

    second = job_start(db, "morning_brief", "2026-05-14")
    assert second["already_ran"] is True
    assert second["proceed"] is False


def test_a_failed_job_may_be_retried(db):
    """Only a FINISHED job blocks a rerun. A crash at 06:00 must not block 06:10."""
    job_start(db, "morning_brief", "2026-05-14")
    job_finish(db, "morning_brief", ok=False, summary="provider timeout",
               local_date="2026-05-14")
    assert job_start(db, "morning_brief", "2026-05-14")["proceed"] is True


def test_the_next_day_runs_again(db):
    job_start(db, "morning_brief", "2026-05-14")
    job_finish(db, "morning_brief", local_date="2026-05-14")
    assert job_start(db, "morning_brief", "2026-05-15")["proceed"] is True


def test_a_deliberate_skip_is_distinguishable_from_a_failure(db):
    """This is the whole point of skip_job: a silent no-op and a crash must not look alike."""
    skip_job(db, "midday_recheck", "verdict unchanged, wind within 3 km/h", "2026-05-14")
    job_finish(db, "eod_report", ok=False, summary="smtp down", local_date="2026-05-14")

    actions = {
        r["action"]
        for r in db.execute("SELECT action FROM audit_log").fetchall()
    }
    assert "job.skipped" in actions
    assert "job.failed" in actions

    skipped = db.execute(
        "SELECT detail_json FROM audit_log WHERE action='job.skipped'"
    ).fetchone()
    assert "verdict unchanged" in skipped["detail_json"]


# ── Decisions ────────────────────────────────────────────────────────────────

def test_decisions_are_logged_with_their_reasoning(db):
    log_decision(
        db,
        action="skipped midday recheck",
        observed="verdict unchanged since 06:00, wind steady",
        reasoning="a message with no new information trains people to ignore messages",
    )
    recent = recent_decisions(db)
    assert len(recent) == 1
    assert recent[0]["decided"] == "skipped midday recheck"
    assert "trains people to ignore" in recent[0]["reasoning"]


# ── Reads ────────────────────────────────────────────────────────────────────

def test_query_logs_filters_and_reads_the_current_view(db, juan):
    _spray(db, juan, log_date="2026-05-14")
    _spray(db, juan, log_date="2026-05-20", block_code="B1")

    all_rows = query_logs(db, table="spray_log")
    assert all_rows["count"] == 2

    by_block = query_logs(db, table="spray_log", block_code="B3")
    assert by_block["count"] == 1
    assert by_block["rows"][0]["block_code"] == "B3"

    by_date = query_logs(db, table="spray_log", date_from="2026-05-15")
    assert by_date["count"] == 1


def test_query_logs_can_include_superseded_rows_for_the_compliance_export(db, juan):
    from vineyard_mcp.compliance import draft_correction

    first = _spray(db, juan, log_date="2026-05-14")["committed"]
    corr = draft_correction(db, "spray_log", first["id"], {"rate_value": 6})
    _commit_spray(db, corr["confirm_token"])

    assert query_logs(db, table="spray_log")["count"] == 1
    both = query_logs(db, table="spray_log", include_superseded=True)
    assert both["count"] == 2


def test_message_logging_dedupes_on_message_id(db):
    first = log_message(db, direction="in", wa_phone="+15215550001", body="hola",
                        wa_message_id="ABC123")
    assert first["logged"] is True
    replay = log_message(db, direction="in", wa_phone="+15215550001", body="hola",
                         wa_message_id="ABC123")
    assert replay["duplicate"] is True
    assert db.execute("SELECT COUNT(*) c FROM messages_raw").fetchone()["c"] == 1


# ── get_situation: what a scheduled run can actually notice ──────────────────

def test_situation_reports_weather_staleness_per_site(db):
    cache_weather(db, "penticton", "eccc", {"hourly": []}, {"verdict": "YES"})
    sit = get_situation(db)
    by_site = {w["site"]: w for w in sit["weather"]}
    assert by_site["penticton"]["stale"] is False
    # naramata is configured but never fetched — Hermes must be able to see the gap
    assert by_site["naramata"]["status"] == "no_data"


def test_situation_surfaces_unverified_products_actually_in_use(db, juan):
    _spray(db, juan, product_name_raw="Mystery Fungicide", label_rei=12)
    sit = get_situation(db)
    names = [p["trade_name"] for p in sit["unverified_products_in_use"]]
    assert "Mystery Fungicide" in names


def test_situation_includes_open_drafts_so_they_are_not_forgotten(db, juan):
    draft_spray_log(db, juan, {"product_name_raw": "Microthiol Disperss"})
    sit = get_situation(db)
    assert len(sit["open_drafts"]) == 1
    assert sit["open_drafts"][0]["state"] == "collecting"


def test_situation_carries_active_reis(db, juan):
    from datetime import datetime, timedelta

    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%d")
    _spray(db, juan, log_date=future)
    sit = get_situation(db)
    assert [r["block_code"] for r in sit["rei_active"]] == ["B3"]
    assert rei_active(db)["active"][0]["block_code"] == "B3"


def test_situation_reports_recent_decisions(db):
    log_decision(db, action="held a nudge", observed="Miguel is off Fridays",
                 reasoning="a manager told me last week")
    assert get_situation(db)["recent_decisions"][0]["decided"] == "held a nudge"


def test_situation_does_not_crash_on_an_empty_database(db):
    """A fresh install must still produce a usable situation, not a stack trace at 06:00."""
    sit = get_situation(db)
    assert sit["rei_active"] == []
    assert sit["today_sprays"] == []
    assert "local_date" in sit
