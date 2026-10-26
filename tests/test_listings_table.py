"""listings_table: the CSV of listings shown to the owners and its daily message
(scripts/listings_table.py). Pure functions only; the CSV goes through tmp_path."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import listings_table as tbl  # noqa: E402


def listing(key, first_seen, **kw):
    base = {"dedupe_key": key, "mls_number": key.removeprefix("mls-"), "title": None,
            "address": "000 398 Upper Bench Road S Penticton, British Columbia V",
            "area": "Penticton", "price": 1995000.0, "acres": None, "url": None,
            "first_seen_utc": first_seen}
    return base | kw


class TestSync:
    def test_new_listing_gets_a_row_with_days_listed(self):
        rows = tbl.sync({}, [listing("mls-1", "2026-10-21T20:32:16Z")], date(2026, 10, 26))
        row = rows["mls-1"]
        assert row["listed_on"] == tbl.local_date("2026-10-21T20:32:16Z").isoformat()
        assert row["days_listed"] == (date(2026, 10, 26) - date.fromisoformat(row["listed_on"])).days
        assert row["price"] == "1995000"

    def test_listed_on_is_never_overwritten(self):
        """A date corrected by hand (or from the alert email) must survive the next sync."""
        rows = {"mls-1": {"dedupe_key": "mls-1", "listed_on": "2026-08-12",
                          "first_shown_utc": "2026-08-25T12:00:00Z"}}
        rows = tbl.sync(rows, [listing("mls-1", "2026-08-25T12:00:00Z")], date(2026, 10, 26))
        assert rows["mls-1"]["listed_on"] == "2026-08-12"
        assert rows["mls-1"]["days_listed"] == 75

    def test_url_filled_later(self):
        rows = tbl.sync({}, [listing("mls-1", "2026-10-21T20:32:16Z")], date(2026, 10, 26))
        rows = tbl.sync(rows, [listing("mls-1", "2026-10-21T20:32:16Z", url="https://x/1")],
                        date(2026, 10, 27))
        assert rows["mls-1"]["url"] == "https://x/1"

    def test_csv_round_trip(self, tmp_path):
        path = str(tmp_path / "shown.csv")
        rows = tbl.sync({}, [listing("mls-1", "2026-10-21T20:32:16Z")], date(2026, 10, 26))
        tbl.write_csv(rows, path)
        back = tbl.read_csv(path)
        assert back["mls-1"]["listed_on"] == rows["mls-1"]["listed_on"]
        assert list(tmp_path.iterdir()) == [tmp_path / "shown.csv"]   # no tmp left behind


class TestRender:
    NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)

    def rows(self):
        return tbl.sync({}, [
            listing("mls-1", "2026-10-26T02:00:00Z", url="https://www.realtor.ca/real-estate/1/x"),
            listing("mls-2", "2026-09-10T18:00:00Z", address="1525 Smethurst Road Naramata, BC",
                    area="Naramata", price=649000.0),
        ], self.NOW.astimezone().date())

    def test_new_additions_are_the_last_24_hours(self):
        text = tbl.render(self.rows(), self.NOW)
        new_section = text.split("All properties")[0]
        assert "New additions (1)" in new_section
        assert "398 Upper Bench Road S, Penticton — $2.0M" in new_section
        assert "https://www.realtor.ca/real-estate/1/x" in new_section
        assert "Smethurst" not in new_section

    def test_table_has_every_listing(self):
        text = tbl.render(self.rows(), self.NOW)
        table = text.split("```")[1]
        assert "1525 Smethurst Rd" in table and "$649K" in table
        assert "British Columbia" not in table

    def test_same_property_under_two_mls_numbers_is_one_line(self):
        rows = self.rows()
        rows = tbl.sync(rows, [listing("mls-3", "2026-09-10T18:00:00Z",
                                       address="1525 SMETHURST ROAD Naramata, BC",
                                       area="Naramata", price=649000.0)],
                        self.NOW.astimezone().date())
        text = tbl.render(rows, self.NOW)
        assert text.lower().count("1525 smethurst rd") == 1
        assert "All properties shown (2)" in text

    def test_no_new_additions_still_sends_the_table(self):
        text = tbl.render(self.rows(), datetime(2026, 11, 5, tzinfo=UTC))
        assert "New additions: none" in text
        assert "All properties shown (2)" in text

    def test_gone_listings_leave_the_table_but_stay_in_the_csv(self, tmp_path):
        rows = self.rows()
        rows["mls-2"]["status"] = "gone"
        text = tbl.render(rows, self.NOW)
        assert "Smethurst" not in text
        assert "1 sold or delisted" in text
        path = str(tmp_path / "shown.csv")
        tbl.write_csv(rows, path)
        assert tbl.read_csv(path)["mls-2"]["status"] == "gone"

    def test_empty_csv_is_silent(self):
        assert tbl.render({}, self.NOW) == ""
