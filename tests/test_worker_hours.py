"""Individual payroll hours must come from explicit confirmed values."""
import json

import pytest

from vineyard_mcp.compliance import (
    commit_task_log,
    draft_correction,
    draft_task_log,
    present_confirmation,
)


def task(db, juan, **changes):
    fields = dict(task_type="poda", log_date="2026-09-01", hours_total=7,
                  workers=[1, 2], worker_hours=[
                      {"contact_id": 1, "hours": 3}, {"contact_id": 2, "hours": 4}])
    fields.update(changes)
    return draft_task_log(db, juan, fields, "fixture: Juan 3 hours, Miguel 4 hours")


def commit(db, juan, draft):
    assert draft["ready_to_confirm"], draft
    assert present_confirmation(db, draft["confirm_token"])["presented"]
    return commit_task_log(db, draft["confirm_token"], "yes", juan)["committed"]


def hours(db, log_id):
    return [tuple(r) for r in db.execute(
        "SELECT contact_id,hours FROM task_workers WHERE task_log_id=? ORDER BY contact_id",
        (log_id,))]


def test_explicit_individual_hours_are_not_apportioned(db, juan):
    draft = task(db, juan)
    assert draft["draft"]["worker_hours"] == [
        {"contact_id": 1, "hours": 3}, {"contact_id": 2, "hours": 4}]
    row = commit(db, juan, draft)
    assert hours(db, row["id"]) == [(1, 3), (2, 4)]


@pytest.mark.parametrize("value", [None, [], {}, True, 0, -1, 25, "nan", "inf"])
def test_invalid_individual_hours_refused_at_intake_and_commit(db, juan, value):
    entries = [{"contact_id": 1, "hours": value}, {"contact_id": 2, "hours": 4}]
    d = task(db, juan, worker_hours=entries)
    assert not d["ready_to_confirm"]
    d = task(db, juan)
    present_confirmation(db, d["confirm_token"])
    payload = dict(d["draft"], worker_hours=entries)
    db.execute("UPDATE drafts SET draft_json=? WHERE confirm_token=?",
               (json.dumps(payload), d["confirm_token"]))
    assert commit_task_log(db, d["confirm_token"], "yes", juan)["error"] == "missing_fields"


@pytest.mark.parametrize("entries", [[], {}, [1], [{"contact_id": 1, "hours": 7}],
    [{"contact_id": 1, "hours": 3}, {"contact_id": 1, "hours": 4}],
    [{"contact_id": 1, "hours": 3}, {"contact_id": 999, "hours": 4}],
    [{"contact_id": 1, "hours": 3}, {"contact_id": 2, "hours": 3}]])
def test_hours_require_complete_membership_and_matching_crew_total(db, juan, entries):
    assert not task(db, juan, worker_hours=entries)["ready_to_confirm"]


def test_correction_preserves_hours_and_invalidates_changed_total(db, juan):
    original = commit(db, juan, task(db, juan))
    d = draft_correction(db, "task_log", original["id"], {"wa_phone": juan, "notes": "fix"})
    row = commit(db, juan, d)
    assert hours(db, row["id"]) == hours(db, original["id"])
    d = draft_correction(db, "task_log", row["id"], {"wa_phone": juan, "hours_total": 8})
    assert not d["ready_to_confirm"]


def test_legacy_hours_not_inferred_even_for_single_worker(db, juan):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 7})
    row = commit(db, juan, d)
    assert hours(db, row["id"]) == [(1, None)]


def test_individual_hours_are_append_only(db, juan):
    import sqlite3
    row = commit(db, juan, task(db, juan))
    for sql in ["UPDATE task_workers SET hours=1 WHERE task_log_id=?",
                "DELETE FROM task_workers WHERE task_log_id=?"]:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(sql, (row["id"],))


def test_hours_migration_preserves_legacy_memberships(db, juan):
    from vineyard_mcp.db import migrate
    row = commit(db, juan, task(db, juan, worker_hours=None))
    # Reconstruct the actual pre-hours table in a temporary fixture, not production.
    db.execute("DROP TABLE task_workers")
    db.execute("CREATE TABLE task_workers (task_log_id INTEGER, contact_id INTEGER, "
               "PRIMARY KEY(task_log_id,contact_id))")
    db.execute("INSERT INTO task_workers VALUES (?,1)", (row["id"],))
    db.execute("DELETE FROM schema_version")
    db.execute("INSERT INTO schema_version(version) VALUES(6)")
    assert migrate(db) == [7]
    assert hours(db, row["id"]) == [(1, None)]
    assert migrate(db) == []


def test_registered_mcp_hours_capture(db, juan, monkeypatch):
    import asyncio

    from vineyard_mcp import server

    monkeypatch.setattr(server, "_conn", db)

    async def exercise():
        tools = await server.mcp.list_tools()
        description = next(t.description for t in tools if t.name == "draft_task_log")
        assert "worker_hours" in description
        assert "show" in description.lower()
        draft = await server.mcp.call_tool("draft_task_log", {
            "wa_phone": juan, "extraction": {"task_type": "poda", "hours_total": 7,
                "workers": [1, 2], "worker_hours": [
                    {"contact_id": 1, "hours": 3}, {"contact_id": 2, "hours": 4}]},
            "raw_message": "fixture: Juan 3, Miguel 4 hours",
        })
        def unpack(result):
            if isinstance(result, dict):
                return result
            # FastMCP versions return content alone or (content, structured content).
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
                return result[1]
            return json.loads(result[0].text)
        d = unpack(draft)
        assert d["draft"]["worker_hours"][1]["hours"] == 4
        await server.mcp.call_tool("present_confirmation", {"confirm_token": d["confirm_token"]})
        r = unpack(await server.mcp.call_tool("commit_task_log", {
            "confirm_token": d["confirm_token"], "worker_reply": "yes", "wa_phone": juan}))
        assert hours(db, r["committed"]["id"]) == [(1, 3), (2, 4)]
    asyncio.run(exercise())
