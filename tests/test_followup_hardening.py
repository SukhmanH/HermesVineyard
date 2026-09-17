"""Regression evidence for the rejected correction prototype's failure modes."""
import json

import pytest

from vineyard_mcp.compliance import (
    commit_spray_log,
    commit_task_log,
    draft_correction,
    draft_spray_log,
    draft_task_log,
    present_confirmation,
)


def spray(db, phone, **changes):
    fields = dict(product_name_raw="Kumulus DF", block_code="B1", log_date="2026-09-01",
                  start_time="08:00", rate_value=6, rate_units="kg/ha", wind_kmh=5, temp_c=20)
    fields.update(changes)
    return draft_spray_log(db, phone, fields, "original spray words")


def commit(db, draft, phone, task=False):
    assert draft["ready_to_confirm"], draft
    assert present_confirmation(db, draft["confirm_token"])["presented"]
    return (commit_task_log if task else commit_spray_log)(
        db, draft["confirm_token"], "yes", phone)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1, True])
def test_finite_positive_at_intake_and_commit(db, applicator, juan, value):
    d = spray(db, applicator, rate_value=value)
    assert not d["ready_to_confirm"]
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": value})
    assert not d["ready_to_confirm"]
    d = draft_task_log(db, juan, {"hours_total": 3})
    present_confirmation(db, d["confirm_token"])
    payload = json.loads(db.execute("SELECT draft_json FROM drafts WHERE confirm_token=?",
                                    (d["confirm_token"],)).fetchone()[0])
    payload["hours_total"] = value
    db.execute("UPDATE drafts SET draft_json=? WHERE confirm_token=?",
               (json.dumps(payload), d["confirm_token"]))
    assert commit_task_log(db, d["confirm_token"], "yes", juan)["error"] == "missing_fields"


@pytest.mark.parametrize("field", ["task_type", "log_date", "hours_total"])
def test_task_mandatory_commit_gate(db, juan, field):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 3})
    present_confirmation(db, d["confirm_token"])
    payload = dict(d["draft"])
    payload.pop(field)
    db.execute("UPDATE drafts SET draft_json=? WHERE confirm_token=?",
               (json.dumps(payload), d["confirm_token"]))
    assert commit_task_log(db, d["confirm_token"], "yes", juan)["error"] == "missing_fields"


def test_correction_snapshots_followup_provenance_and_block(db, applicator):
    original = commit(db, spray(db, applicator, source_msg_id="source-1"), applicator)["committed"]
    db.execute("UPDATE products SET rei_hours=2, pcp_number='changed', phi_days=99")
    d = draft_correction(db, "spray_log", original["id"],
                         {"notes": "fixed", "block_code": "B3"}, "correction words")
    d = draft_spray_log(db, applicator, {"rate_confirmed": True, "raw_message": "REPLACE",
                                         "source_msg_id": "REPLACE", "corrects_log_id": 999},
                        "followup words")
    row = commit(db, d, applicator)["committed"]
    for field in ("pcp_number", "rei_hours", "phi_days", "source_msg_id"):
        assert row[field] == original[field], (field, row[field], original[field])
    assert row["block_id"] != original["block_id"]
    assert row["corrects_log_id"] == original["id"]
    assert row["raw_message"] == "original spray words\ncorrection words\nfollowup words"


def test_unknown_product_requires_label_across_followups(db, applicator):
    original = commit(db, spray(db, applicator), applicator)["committed"]
    d = draft_correction(db, "spray_log", original["id"], {"product_name_raw": "Unknown ZZZ"})
    assert not d["ready_to_confirm"]
    assert d["draft"].get("rei_hours") is None
    d = draft_spray_log(db, applicator, {"notes": "new"})
    assert not d["ready_to_confirm"]
    d = draft_spray_log(db, applicator, {"label_rei": 48, "pcp_number": "12345"})
    row = commit(db, d, applicator)["committed"]
    assert row["rei_hours"] == 48
    assert row["product_id"] is None
    assert row["phi_days"] is None


def test_task_correction_memberships_and_atomic_supersession(db, juan):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 3, "block_code": "B1"})
    original = commit(db, d, juan, task=True)["committed"]
    workers = [r[0] for r in db.execute(
        "SELECT contact_id FROM task_workers WHERE task_log_id=?", (original["id"],))]
    a = draft_correction(db, "task_log", original["id"], {"wa_phone": juan, "notes": "a"})
    b = draft_correction(db, "task_log", original["id"], {"wa_phone": juan, "notes": "b"})
    row = commit(db, a, juan, task=True)["committed"]
    assert [r[0] for r in db.execute(
        "SELECT contact_id FROM task_workers WHERE task_log_id=?", (row["id"],))] == workers
    assert commit(db, b, juan, task=True)["error"] == "already_superseded"


def test_correction_preserves_rate_warning_then_recomputes(db, applicator):
    d = spray(db, applicator, rate_value=20, rate_confirmed=True)
    original = commit(db, d, applicator)["committed"]
    assert original["rate_flag"]
    db.execute("UPDATE products SET default_rate=100")
    d = draft_correction(db, "spray_log", original["id"], {"notes": "unrelated"})
    row = commit(db, d, applicator)["committed"]
    assert row["rate_flag"] == original["rate_flag"]
    d = draft_correction(db, "spray_log", row["id"], {"rate_value": 1000})
    assert not d["ready_to_confirm"]
    d = draft_spray_log(db, applicator, {"rate_confirmed": True})
    row = commit(db, d, applicator)["committed"]
    assert "1000" in row["rate_flag"]


def test_explicit_same_label_value_survives_identity_change(db, applicator):
    original = commit(db, spray(db, applicator), applicator)["committed"]
    d = draft_correction(db, "spray_log", original["id"], {
        "product_name_raw": "Unknown ZZZ", "label_rei": original["rei_hours"],
        "pcp_number": original["pcp_number"],
    })
    row = commit(db, d, applicator)["committed"]
    assert row["rei_hours"] == original["rei_hours"]
    assert row["pcp_number"] == original["pcp_number"]


@pytest.mark.parametrize("value", [[], {}, "nan", "inf", True, float("inf")])
@pytest.mark.parametrize("field", ["wind_kmh", "temp_c", "rh_pct"])
def test_weather_numeric_fields_reject_invalid(db, applicator, field, value):
    d = spray(db, applicator)
    present_confirmation(db, d["confirm_token"])
    payload = dict(d["draft"])
    payload[field] = value
    db.execute("UPDATE drafts SET draft_json=? WHERE confirm_token=?",
               (json.dumps(payload), d["confirm_token"]))
    assert commit_spray_log(db, d["confirm_token"], "yes", applicator)["error"] == "missing_fields"


def test_task_correction_requires_existing_member_reporter(db, juan, applicator):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 3})
    row = commit(db, d, juan, task=True)["committed"]
    assert draft_correction(db, "task_log", row["id"], {"wa_phone": applicator})["error"] == "reporter_not_task_worker"


@pytest.mark.parametrize("workers", [[99999], [True], [1, 1], "1", []])
def test_invalid_membership_cannot_be_committed(db, juan, workers):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 3})
    present_confirmation(db, d["confirm_token"])
    payload = dict(d["draft"], workers=workers)
    db.execute("UPDATE drafts SET draft_json=? WHERE confirm_token=?",
               (json.dumps(payload), d["confirm_token"]))
    assert commit_task_log(db, d["confirm_token"], "yes", juan)["error"] == "missing_fields"


def test_spray_two_prepared_corrections_cannot_both_commit(db, applicator):
    original = commit(db, spray(db, applicator), applicator)["committed"]
    a = draft_correction(db, "spray_log", original["id"], {"notes": "a"})
    b = draft_correction(db, "spray_log", original["id"], {"notes": "b"})
    assert commit(db, a, applicator)["committed"]
    assert commit(db, b, applicator)["error"] == "already_superseded"
    assert db.execute("SELECT COUNT(*) FROM spray_log WHERE corrects_log_id=?",
                      (original["id"],)).fetchone()[0] == 1


@pytest.mark.parametrize("field", ["task_type", "log_date", "hours_total"])
def test_correction_creation_does_not_ignore_missing_required_fields(db, juan, field):
    d = draft_task_log(db, juan, {"task_type": "poda", "hours_total": 3})
    original = commit(db, d, juan, task=True)["committed"]
    corrected = draft_correction(db, "task_log", original["id"], {"wa_phone": juan, field: None})
    assert not corrected["ready_to_confirm"]
    assert any(item["field"] == field for item in corrected["missing_fields"])


def test_correction_followup_requires_new_presentation(db, applicator):
    original = commit(db, spray(db, applicator), applicator)["committed"]
    d = draft_correction(db, "spray_log", original["id"], {"notes": "a"})
    present_confirmation(db, d["confirm_token"])
    draft_spray_log(db, applicator, {"notes": "b"})
    assert commit_spray_log(db, d["confirm_token"], "yes", applicator)["error"] == "not_presented"


def test_gust_warning_available_in_all_languages():
    from vineyard_mcp.templates import load
    texts = [load(lang)["spray_missing_gusts"] for lang in ("en", "es", "pa")]
    assert all(isinstance(text, str) and text for text in texts)
    assert len(set(texts)) == 3
    assert any("\u0a00" <= char <= "\u0a7f" for char in texts[-1])


@pytest.mark.parametrize("value", [None, "bad", True, float("nan"), float("inf"), -1])
def test_invalid_gusts_never_approve(value):
    from vineyard_mcp.weather_math import compute_spray_window
    hourly = [{"time": f"2026-09-01T{h:02d}:00", "wind_kmh": 5, "temp_c": 20,
               "gust_kmh": value} for h in range(8, 13)]
    verdict = compute_spray_window(hourly, age_hours=0.5)
    assert verdict["verdict"] == "NO"
    assert verdict["reason"] == "missing_gusts"


def test_unverified_product_cannot_take_unattested_registry_interval(db, applicator):
    d = spray(db, applicator, product_name_raw="Mystery Fungicide", rei_hours=48)
    assert not d["ready_to_confirm"]
    d = draft_spray_log(db, applicator, {"label_rei": 48})
    assert d["ready_to_confirm"]


def test_changed_known_product_resolves_and_keeps_new_snapshot(db, applicator):
    original = commit(db, spray(db, applicator), applicator)["committed"]
    d = draft_correction(db, "spray_log", original["id"], {"product_name_raw": "Microthiol Disperss"})
    assert d["draft"]["pcp_number"] == "PCP-12345"
    assert d["draft"]["product_id"] != original["product_id"]
    db.execute("UPDATE products SET rei_hours=1, pcp_number='new-registry'")
    d = draft_spray_log(db, applicator, {"notes": "unrelated"})
    row = commit(db, d, applicator)["committed"]
    assert row["pcp_number"] == "PCP-12345"
    assert row["rei_hours"] == 24


def test_commit_supersession_guard_holds_under_concurrent_connections(db, applicator, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local

    from vineyard_mcp import compliance as module
    from vineyard_mcp.db import connect

    original = commit(db, spray(db, applicator), applicator)["committed"]
    drafts = [draft_correction(db, "spray_log", original["id"], {"notes": note})
              for note in ("a", "b")]
    for d in drafts:
        present_confirmation(db, d["confirm_token"])
    path = db.execute("PRAGMA database_list").fetchone()[2]
    barrier = Barrier(2)
    state = local()
    real_load = module._load_committable

    def synchronized_load(*args, **kwargs):
        result = real_load(*args, **kwargs)
        if not getattr(state, "loaded", False):
            state.loaded = True
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(module, "_load_committable", synchronized_load)

    def attempt(d):
        connection = connect(path)
        try:
            return commit_spray_log(connection, d["confirm_token"], "yes", applicator)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, drafts))
    assert sum("committed" in r for r in results) == 1
    assert [r["error"] for r in results if "error" in r] == ["already_superseded"]
    assert db.execute("SELECT COUNT(*) FROM spray_log WHERE corrects_log_id=?",
                      (original["id"],)).fetchone()[0] == 1
