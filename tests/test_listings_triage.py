"""listings_triage parsing and triage rules (scripts/listings_triage.py).

No IMAP anywhere in here: every function under test is pure, which is the point. The bugs these
pin were all found by feeding the parser a realistically-shaped alert email rather than by
reading it.
"""

from __future__ import annotations

import email
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import listings_triage as lt  # noqa: E402

HUNT = {
    "areas": ["Penticton", "Naramata", "Oliver", "Osoyoos", "Summerland"],
    "min_acres": 2.0,
    "max_price": None,
    "keywords": ["vineyard", "grape", "acreage", "farm"],
    "top_areas": ["Osoyoos", "Oliver", "Penticton", "Naramata"],
    "price_ceilings": {"Osoyoos": 800000, "Oliver": 1100000},
}


def msg_of(subject: str, body: str, ctype: str = "text/html"):
    raw = (
        f"From: alerts@realtor.ca\r\nSubject: {subject}\r\n"
        f"Content-Type: {ctype}; charset=utf-8\r\n\r\n{body}"
    ).encode()
    return email.message_from_bytes(raw), raw


TWO_LISTINGS = """<html><body>
<a href="https://www.realtor.ca/real-estate/30111/155-vineyard-way-osoyoos">a</a>
<p>MLS# 10123456 RE/MAX Realty 3 Bedroom 2 Bathroom 1,800 Square Feet</p>
<p>$749,000 - 155 Vineyard Way, Osoyoos, BC - 5.2 acres</p>
<a href="https://www.realtor.ca/real-estate/30222/900-naramata-rd-naramata">b</a>
<p>MLS# 10777777 Royal LePage 4 Bedroom 3 Bathroom 2,400 Square Feet</p>
<p>$2,300,000 - 900 Naramata Rd, Naramata, BC - 22 acres vineyard</p>
</body></html>"""


class TestMultiListingEmails:
    """One alert email is not one listing - the failure that silently dropped inventory."""

    def test_each_listing_is_parsed_separately(self):
        msg, raw = msg_of("3 new listings matching your search", TWO_LISTINGS)
        out = lt.parse_listings(msg, raw, HUNT)
        assert [x["mls"] for x in out] == ["10123456", "10777777"]

    def test_fields_do_not_bleed_between_listings(self):
        """Parsing the body as one blob took MLS from the first and area from the last."""
        msg, raw = msg_of("3 new listings", TWO_LISTINGS)
        first, second = lt.parse_listings(msg, raw, HUNT)
        assert (first["price"], first["area"], first["acres"]) == (749000, "Osoyoos", 5.2)
        assert (second["price"], second["area"], second["acres"]) == (2300000, "Naramata", 22.0)

    def test_each_listing_keeps_its_own_link(self):
        msg, raw = msg_of("3 new listings", TWO_LISTINGS)
        first, second = lt.parse_listings(msg, raw, HUNT)
        assert "155-vineyard-way" in first["url"]
        assert "900-naramata-rd" in second["url"]

    def test_an_email_with_no_mls_still_yields_one_listing(self):
        msg, raw = msg_of("A listing", "<p>$500,000 in Oliver BC, 4 acres</p>")
        assert len(lt.parse_listings(msg, raw, HUNT)) == 1


class TestParsing:
    def test_address_survives_adjacent_mls_and_bed_bath_metadata(self):
        """MLS numbers and '3 Bedroom' both lead with digits and were eaten as street numbers."""
        body = ("<p>MLS# 10398703 RE/MAX 3 Bedroom 3 Bathroom 2,830 Square Feet</p>"
                "<p>294 ROAD 18 Road, Oliver, BC V0H1T1 $1,299,900</p>")
        msg, raw = msg_of("New", body)
        assert lt.parse_listings(msg, raw, HUNT)[0]["title"] == "294 ROAD 18 Road, Oliver, BC"

    def test_millions_shorthand_price(self):
        msg, raw = msg_of("New", "<p>MLS# 10555555 Estate $1.2M in Oliver, BC</p>")
        assert lt.parse_listings(msg, raw, HUNT)[0]["price"] == 1_200_000

    def test_thousands_shorthand_price(self):
        msg, raw = msg_of("New", "<p>MLS# 10555556 $850K in Oliver, BC</p>")
        assert lt.parse_listings(msg, raw, HUNT)[0]["price"] == 850_000

    def test_promo_amount_is_not_mistaken_for_a_price(self):
        body = "<p>Save $500 on your move! MLS# 10999999 Priced at $875,000. Penticton BC</p>"
        msg, raw = msg_of("New", body)
        assert lt.parse_listings(msg, raw, HUNT)[0]["price"] is None

    def test_plain_text_email_is_parsed_not_discarded(self):
        """No text/html part meant an empty body, every field None, and a silent drop."""
        msg, raw = msg_of("New", "MLS 10111111 $900,000 4 acres Oliver BC vineyard", "text/plain")
        out = lt.parse_listings(msg, raw, HUNT)[0]
        assert out["price"] == 900_000
        assert out["area"] == "Oliver"

    def test_area_is_the_earliest_mention_not_the_config_order(self):
        """'20 minutes from Penticton' does not make it a Penticton listing."""
        body = "<p>MLS# 10333333 Home in Osoyoos, BC, 20 minutes from Penticton. $650,000</p>"
        msg, raw = msg_of("New", body)
        assert lt.parse_listings(msg, raw, HUNT)[0]["area"] == "Osoyoos"

    def test_hectares_are_converted_to_acres(self):
        msg, raw = msg_of("New", "<p>MLS# 10444444 Oliver BC 4 hectares</p>")
        assert lt.parse_listings(msg, raw, HUNT)[0]["acres"] == pytest.approx(9.884, abs=0.01)


class TestMoneyAndClassify:
    @pytest.mark.parametrize("value", [None, "", "n/a"])
    def test_money_never_raises_on_a_missing_price(self, value):
        assert lt.money(value) == "price n/a"

    def test_money_formats_real_prices(self):
        assert lt.money(749000) == "$749,000"

    @pytest.mark.parametrize("area", ["Summerland", "Osoyoos", "Oliver"])
    def test_classify_survives_a_missing_price(self, area):
        """`f'${price:,}'` with price=None is a TypeError that killed the whole cron run."""
        listing = {"area": area, "price": None, "keyword_hit": False, "acres": None}
        tier, why = lt.classify(listing, HUNT)
        assert tier == "digest"
        assert "price n/a" in why

    def test_render_survives_a_missing_price(self):
        listing = {"title": "12 Vineyard Rd", "price": None, "area": "Oliver", "beds": None,
                   "baths": None, "sqft": None, "broker": None, "url": None, "acres": None,
                   "why": "keyword"}
        assert "price n/a" in lt.render(listing)

    def test_keyword_hit_interrupts(self):
        listing = {"area": "Oliver", "price": 900000, "keyword_hit": True, "acres": None}
        assert lt.classify(listing, HUNT)[0] == "interrupt"

    def test_off_region_without_a_keyword_is_filtered(self):
        listing = {"area": None, "price": 400000, "keyword_hit": False, "acres": None}
        assert lt.classify(listing, HUNT)[0] == "filtered"

    def test_owner_max_price_is_a_hard_filter(self):
        """max_price sat in settings.yaml being ignored while the code used its own ceilings."""
        hunt = dict(HUNT, max_price=700_000)
        listing = {"area": "Osoyoos", "price": 2_300_000, "keyword_hit": True, "acres": 22}
        tier, why = lt.classify(listing, hunt)
        assert tier == "filtered"
        assert "max_price" in why

    def test_area_with_no_ceiling_does_not_trigger_the_price_interrupt(self):
        listing = {"area": "Summerland", "price": 100, "keyword_hit": False, "acres": None}
        assert lt.classify(listing, HUNT)[0] == "digest"

    def test_acreage_over_min_interrupts(self):
        listing = {"area": "Summerland", "price": 2_000_000, "keyword_hit": False, "acres": 8}
        assert lt.classify(listing, HUNT)[0] == "interrupt"


class TestNotepadAndPruning:
    def test_seen_keys_are_capped(self):
        """The map travels as one CLI argument; unbounded it eventually fails to write."""
        big = {f"mls-{i}": {"first_seen": f"2026-01-{(i % 28) + 1:02d}"} for i in range(500)}
        pruned, dropped = lt.prune_seen(big, cap=400)
        assert (len(pruned), dropped) == (400, 100)

    def test_pruning_keeps_the_newest(self):
        seen = {"old": {"first_seen": "2026-01-01"}, "new": {"first_seen": "2026-08-01"}}
        pruned, _ = lt.prune_seen(seen, cap=1)
        assert list(pruned) == ["new"]

    def test_pruning_is_a_no_op_under_the_cap(self):
        seen = {"a": {"first_seen": "2026-01-01"}}
        assert lt.prune_seen(seen, cap=400) == (seen, 0)

    def test_missing_notepad_key_sentinel_is_not_treated_as_a_value(self, monkeypatch):
        """`notepad get` prints "No notepad key '...'" and exits 0 for an absent key."""
        class Result:
            returncode = 0
            stdout = "No notepad key 'seen_keys' for job 1ff50fb0cbdc."
            stderr = ""

        monkeypatch.setattr(lt.subprocess, "run", lambda *a, **k: Result())
        assert lt.note_get("seen_keys") is None


class TestSenderAllowlist:
    @pytest.mark.parametrize("addr,ok", [
        ("noreply@zealty.ca", True),
        ("alerts@matrix.crea.ca", True),
        ("someone@mail.matrix.crea.ca", True),
        ("phisher@evil.com", False),
        ("", False),
    ])
    def test_allowlist(self, addr, ok):
        allowed = ["noreply@zealty.ca", "*@matrix.crea.ca"]
        assert lt.sender_allowed(addr, allowed) is ok

    def test_display_name_addresses_are_parsed(self):
        assert lt.sender_addr('"REALTOR.ca" <noreply@realtor.ca>') == "noreply@realtor.ca"
