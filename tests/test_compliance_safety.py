"""Safety regressions using only the isolated fixture database."""

import pytest
from test_compliance import _commit_spray, _ready_draft


@pytest.mark.parametrize("field,value", [
    ("log_date", "2026-02-30"), ("log_date", "2026-2-03"),
    ("log_date", "20260203"), ("log_date", "0000-01-01"),
    ("start_time", "24:00"), ("end_time", "99:99"),
    ("start_time", "6:00"), ("end_time", "08:60"),
])
def test_spray_rejects_noncanonical_or_impossible_datetime(db, juan, field, value):
    draft = _ready_draft(db, juan, **{field: value})
    assert not draft["ready_to_confirm"]
    assert field in {m["field"] for m in draft["missing_fields"]}
    assert "error" in _commit_spray(db, draft["confirm_token"])
    assert db.execute("SELECT count(*) FROM spray_log").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("label_rei", -48), ("label_rei", -0.5), ("label_rei", "garbage"),
    ("label_rei", float("nan")), ("label_rei", float("inf")),
])
def test_negative_or_junk_rei_is_refused_not_committed(db, juan, field, value):
    """A negative REI would schedule re-entry before the spray happened."""
    draft = _ready_draft(db, juan, **{field: value})
    assert not draft["ready_to_confirm"], draft["missing_fields"]
    assert field in {m["field"] for m in draft["missing_fields"]}
    assert "error" in _commit_spray(db, draft["confirm_token"])
    assert db.execute("SELECT count(*) FROM spray_log").fetchone()[0] == 0


def test_commit_refuses_a_tampered_negative_rei(db, juan):
    """The draft-side flow cannot inject a bad rei_hours (label wins), but the drafts
    table itself is writable: a stale or tampered draft must not commit unchecked."""
    draft = _ready_draft(db, juan)
    db.execute(
        "UPDATE drafts SET draft_json=json_set(draft_json, '$.rei_hours', -24) "
        "WHERE confirm_token=?",
        (draft["confirm_token"],),
    )
    assert "error" in _commit_spray(db, draft["confirm_token"])
    assert db.execute("SELECT count(*) FROM spray_log").fetchone()[0] == 0


def test_zero_and_positive_label_rei_are_accepted(db, juan):
    for value in ("0", "12"):
        draft = _ready_draft(db, juan, label_rei=value)
        assert draft["ready_to_confirm"], draft["missing_fields"]
        db.execute("DELETE FROM drafts")
