"""Regressions identified by independent review; fixture databases only."""
from datetime import date

from helpers import days_ago, today_local

from vineyard_mcp.maturity import (
    irrigation_vs_ripening,
    maturity_status,
    record_sample,
    water_balance,
)


def test_public_tool_forwards_winery(db, monkeypatch):
    from vineyard_mcp import server

    monkeypatch.setattr(server, "db", lambda: db)
    fn = getattr(server.maturity_status, "fn", server.maturity_status)
    captured = {}

    def assess(conn, block_code, season, *, winery=None):
        captured.update(winery=winery, block_code=block_code, season=season)
        assert conn is db
        return captured

    monkeypatch.setattr(server.M, "maturity_status", assess)
    assert fn("B3", 2026, winery="Buyer")["winery"] == "Buyer"


def test_all_contracts_participate_in_irrigation_cross_check(db):
    balance = water_balance(db, "B3", 0, 50, kc=0.6)
    entries = [
        {"block_code": "B3", "winery": winery, "brix": 21,
         "target": {"winery": winery}, "brix_gap": gap,
         "projected_days_to_target": days}
        for winery, gap, days in [("Far", 8, 24), ("Near", 1, 3)]
    ]
    out = irrigation_vs_ripening(db, "B3", balance, {"blocks": entries})
    assert out["tension"] == "irrigating_may_delay_contract_ripeness"
    assert {c["winery"] for c in out["contracts"]} == {"Near", "Far"}
    assert out["winery"] == "Near"
    assert all("no contract target" not in n for c in out["contracts"] for n in c["considerations"])


def test_latest_retest_selected_on_both_dates(db):
    for ago, brix in [(7, 18), (7, 20), (0, 21), (0, 22)]:
        record_sample(db, "B3", sampled_on=days_ago(ago), brix=brix)
    out = maturity_status(db, "B3")["blocks"][0]
    assert out["brix"] == 22
    assert out["brix_per_day"] == 0.286


def test_samples_do_not_cross_seasons(db):
    year = today_local().year
    record_sample(db, "B3", sampled_on=f"{year - 1}-09-10", brix=20)
    record_sample(db, "B3", sampled_on=f"{year}-09-10", brix=22)
    out = maturity_status(db, "B3", season=year - 1)["blocks"][0]
    assert out["samples_this_season"] == 1
    assert out["brix"] == 20
    assert out["brix_per_day"] is None


def test_old_samples_do_not_hide_unsampled_current_contract(db):
    year = today_local().year
    record_sample(db, "B3", sampled_on=f"{year - 1}-09-10", brix=20)
    db.execute("INSERT INTO fruit_targets(block_id,season_year,winery,target_brix_min) "
               "SELECT id, ?, 'Buyer', 23 FROM blocks WHERE code='B3'", (year,))
    out = maturity_status(db, "B3", season=year)
    assert out["blocks"] == []
    assert out["contracted_but_unsampled"][0]["winery"] == "Buyer"


def test_projection_is_anchored_to_sample_not_request_date(db):
    year = today_local().year
    db.execute("INSERT INTO fruit_targets(block_id,season_year,winery,target_brix_min) "
               "SELECT id, ?, 'Buyer', 23 FROM blocks WHERE code='B3'", (year,))
    record_sample(db, "B3", sampled_on=days_ago(14), brix=19)
    record_sample(db, "B3", sampled_on=days_ago(7), brix=21)
    out = maturity_status(db, "B3")["blocks"][0]
    assert date.fromisoformat(out["projected_date"]) == today_local()
    assert out["projected_days_to_target"] == 0
    assert out["brix_gap"] == 2  # projected arrival is not a measured ripe sample
