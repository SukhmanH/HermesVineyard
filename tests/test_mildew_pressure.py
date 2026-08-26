"""Tests for the powdery-mildew pressure proxy (advisory.mildew_pressure)."""

from datetime import UTC, datetime

from vineyard_mcp.advisory import mildew_pressure


def _hours(specs):
    """specs: list of (utc_hour, temp_c, precip_prob, sky) for one fixed date."""
    base = datetime(2026, 7, 15, tzinfo=UTC)
    out = []
    for utc_hour, temp, prob, sky in specs:
        stamp = base.replace(hour=utc_hour)
        h = {"time": stamp.isoformat(), "temp_c": temp}
        if prob is not None:
            h["precip_prob_pct"] = prob
        if sky:
            h["sky"] = sky
        out.append(h)
    return out


def _full_day(temp_fn, wet_fn):
    # UTC hours whose local (PDT, UTC-7) time falls in 06:00-20:00 -> UTC 13:00..03(+1)
    return _hours(
        (h, temp_fn(h), wet_fn(h), "Showers" if wet_fn(h) else "Sunny")
        for h in range(13, 24)
    ) + _hours(
        (h, temp_fn(h), wet_fn(h), "Rain" if wet_fn(h) else "Sunny") for h in range(0, 4)
    )


def test_hot_wet_day_scores_high():
    hours = []
    for utc in range(13, 24):
        local = (utc - 7) % 24
        if 6 <= local <= 20:
            hours.append((utc, 27, 80, "Showers"))
    result = mildew_pressure(_hours(hours))
    assert result["band"] == "HIGH"
    assert result["infection_condition_hours"] == len(hours)


def test_cool_dry_day_scores_low():
    hours = [(utc, 12, 10, "Sunny") for utc in range(13, 24)]
    result = mildew_pressure(_hours(hours))
    assert result["score"] < 30 or result["band"] == "LOW"
    assert result["infection_condition_hours"] == 0


def test_night_hours_excluded_via_local_conversion():
    # 20:00 UTC = 13:00 PDT (counted); 04:00 UTC = 21:00 PDT (excluded)
    hours = _hours([(20, 26, 90, "Rain"), (4, 26, 90, "Rain")])
    result = mildew_pressure(hours)
    assert result["hours_used"] == 1
    assert result["infection_condition_hours"] == 1


def test_empty_and_garbage_inputs():
    assert mildew_pressure([])["band"] == "no_data"
    bad = mildew_pressure([{"time": "nonsense", "temp_c": "x"}])
    assert bad["band"] == "no_data" and bad["hours_skipped"] == 1


def test_score_is_bounded_and_transparent():
    hot = _full_day(lambda _: 29, lambda _: True)
    result = mildew_pressure(hot)
    assert result["score"] <= 100
    for key in ("band", "note", "wet_hours", "optimal_temp_hours"):
        assert key in result


def test_optimal_only_builds_partial_pressure():
    # Warm but dry all day: pressure accumulates from warmth alone (~15 h -> MODERATE).
    specs = [(utc, 25, 5, "Sunny") for utc in range(13, 24)]
    specs += [(utc, 25, 5, "Sunny") for utc in range(0, 4)]
    result = mildew_pressure(_hours(specs))
    assert result["band"] == "MODERATE"
    assert result["infection_condition_hours"] == 0
