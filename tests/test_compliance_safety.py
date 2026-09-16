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
