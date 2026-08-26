"""compute_spray_window() — the fail-safe.

The tests that matter most here are the ones asserting NO. A YES that should have been NO puts
spray on a neighbour's organic fruit or on a worker.
"""

from __future__ import annotations

from vineyard_mcp.config import SprayWindow
from vineyard_mcp.weather_math import (
    REASON_GUSTS,
    REASON_MISSING_WIND,
    REASON_NO_DATA,
    REASON_OK,
    REASON_RAIN,
    REASON_STALE,
    REASON_TEMP_HIGH,
    REASON_TOO_SHORT,
    REASON_WIND_CALM,
    REASON_WIND_HIGH,
    compute_spray_window,
)

CFG = SprayWindow()


def hours(specs: list[dict], date: str = "2026-05-14") -> list[dict]:
    """Build an hourly list. specs entries: {h, wind, gust, temp, rain}."""
    out = []
    for s in specs:
        out.append(
            {
                "time": f"{date}T{s['h']:02d}:00",
                "wind_kmh": s.get("wind", 8),
                "gust_kmh": s.get("gust", 12),
                "temp_c": s.get("temp", 18),
                "precip_prob_pct": s.get("rain", 0),
            }
        )
    return out


def calm_day(n: int = 8, start: int = 8, **over) -> list[dict]:
    return hours([{"h": start + i, **over} for i in range(n)])


# ── The happy path ────────────────────────────────────────────────────────────

def test_good_day_yields_yes_with_a_window():
    v = compute_spray_window(calm_day(), CFG, age_hours=0.5)
    assert v["verdict"] == "YES"
    assert v["reason"] == REASON_OK
    assert v["best_window"]["hours"] >= CFG.min_window_hours
    assert v["best_window"]["start"] == "08:00"


# ── Fail-safe gates: these must hold even when the rest of the data looks perfect ──

def test_stale_data_is_no_no_matter_how_good_the_forecast():
    """A beautiful forecast from nine hours ago is still not today's forecast."""
    v = compute_spray_window(calm_day(), CFG, age_hours=9.0)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_STALE
    assert v["stale"] is True
    assert v["best_window"] is None


def test_missing_wind_everywhere_is_no():
    """A spray call without wind data is not a call."""
    data = calm_day()
    for h in data:
        h["wind_kmh"] = None
    v = compute_spray_window(data, CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_MISSING_WIND


def test_missing_wind_is_not_treated_as_zero():
    """Regression guard: coercing a missing reading to 0.0 would read as 'dead calm'
    and could sneak past a naive threshold check. Missing must stay missing."""
    data = calm_day()
    for h in data[:4]:
        h["wind_kmh"] = None
    v = compute_spray_window(data, CFG, age_hours=0.1)
    # Remaining good hours still form a window; the null hours must not.
    assert v["verdict"] == "YES"
    assert v["best_window"]["start"] == "12:00"


def test_empty_input_is_no():
    assert compute_spray_window([], CFG)["reason"] == REASON_NO_DATA
    assert compute_spray_window(None, CFG)["reason"] == REASON_NO_DATA


def test_garbage_input_does_not_raise():
    """A crash here takes out the morning brief. Degrade to NO, never to nothing."""
    v = compute_spray_window([{"nonsense": True}, "not a dict", {"time": "???"}], CFG)
    assert v["verdict"] == "NO"


# ── Individual constraints ────────────────────────────────────────────────────

def test_too_windy_is_no():
    v = compute_spray_window(calm_day(wind=30), CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_WIND_HIGH


def test_dead_calm_is_no_not_ideal():
    """Dead calm means an inversion can hold spray in suspension and carry it off-target."""
    v = compute_spray_window(calm_day(wind=0.5), CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_WIND_CALM


def test_gusts_block_even_when_average_wind_is_fine():
    v = compute_spray_window(calm_day(wind=8, gust=40), CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_GUSTS


def test_rain_probability_blocks():
    v = compute_spray_window(calm_day(rain=80), CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_RAIN


def test_window_shorter_than_minimum_is_no():
    data = hours([{"h": 8}, {"h": 9, "wind": 40}, {"h": 10}, {"h": 11, "wind": 40}])
    v = compute_spray_window(data, CFG, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] in (REASON_TOO_SHORT, REASON_WIND_HIGH)
    assert v["best_window"] is None


def test_night_hours_are_ignored():
    """Perfect conditions at 3 AM are not a spray window."""
    data = hours([{"h": h} for h in (1, 2, 3, 4)])
    v = compute_spray_window(data, CFG, age_hours=0.1)
    assert v["verdict"] == "NO"


# ── Product-specific overrides ────────────────────────────────────────────────

def test_product_max_temp_overrides_the_general_ceiling():
    """Sulfur burns fruit above ~30 C. A 29 C day is fine generally and fine for sulfur;
    a 31 C day is blocked by the product even though the general ceiling is 28."""
    sulfur = {"trade_name": "Microthiol Disperss", "max_temp_c": 30.0, "rainfast_hours": 4}
    warm = calm_day(temp=26)
    assert compute_spray_window(warm, CFG, sulfur, age_hours=0.1)["verdict"] == "YES"

    hot = calm_day(temp=31)
    v = compute_spray_window(hot, CFG, sulfur, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_TEMP_HIGH
    assert v["temp_ceiling_c"] == 28.0  # min(general 28, product 30)


def test_rainfast_window_looks_ahead_past_the_run():
    """A spray that gets rained off two hours later was never a usable window."""
    data = hours(
        [{"h": 8}, {"h": 9}, {"h": 10}, {"h": 11, "rain": 90}, {"h": 12, "rain": 90}]
    )
    product = {"trade_name": "X", "rainfast_hours": 4}
    v = compute_spray_window(data, CFG, product, age_hours=0.1)
    assert v["verdict"] == "NO"
    assert v["reason"] == REASON_RAIN


def test_verdict_carries_source_and_age_for_the_message():
    v = compute_spray_window(calm_day(), CFG, source="eccc", age_hours=0.4)
    assert v["source"] == "eccc"
    assert v["age_hours"] == 0.4


# ── Timezone: caught against live ECCC data ──────────────────────────────────

def test_utc_input_is_converted_before_daylight_filtering():
    """ECCC publishes UTC. Applying the 05:00-21:00 daylight bounds to UTC hours selects the
    middle of the local night and reports it as a morning window - which is what happened on
    the first live fetch: a confident '05:00-09:00' that was really 22:00-02:00 Pacific."""
    # 05:00-09:00 UTC == 22:00-02:00 PDT: night, and must be excluded.
    night_utc = [
        {"time": f"2026-08-21T{h:02d}:00+00:00", "wind_kmh": 8, "temp_c": 18,
         "precip_prob_pct": 0}
        for h in range(5, 10)
    ]
    v = compute_spray_window(night_utc, CFG, source="eccc", age_hours=0.2,
                             tz="America/Vancouver")
    assert v["verdict"] == "NO", "night hours in UTC must not pass the daylight filter"


def test_utc_window_times_are_reported_in_local_time():
    """A window must be stated in the time the crew reads off their own phone."""
    # 15:00-19:00 UTC == 08:00-12:00 PDT.
    utc = [
        {"time": f"2026-08-21T{h:02d}:00+00:00", "wind_kmh": 8, "temp_c": 18,
         "precip_prob_pct": 0}
        for h in range(15, 20)
    ]
    v = compute_spray_window(utc, CFG, source="eccc", age_hours=0.2, tz="America/Vancouver")
    assert v["verdict"] == "YES"
    assert v["best_window"]["start"] == "08:00"
    assert v["best_window"]["end"] == "12:00"


def test_naive_timestamps_are_treated_as_already_local():
    """Our own cached/normalized data may be naive local; it must not be shifted."""
    naive = [
        {"time": f"2026-08-21T{h:02d}:00", "wind_kmh": 8, "temp_c": 18, "precip_prob_pct": 0}
        for h in range(8, 13)
    ]
    v = compute_spray_window(naive, CFG, age_hours=0.2)
    assert v["verdict"] == "YES"
    assert v["best_window"]["start"] == "08:00"


def test_an_unknown_timezone_does_not_crash_the_brief():
    hours = [
        {"time": f"2026-08-21T{h:02d}:00", "wind_kmh": 8, "temp_c": 18, "precip_prob_pct": 0}
        for h in range(8, 13)
    ]
    assert compute_spray_window(hours, CFG, tz="Mars/Olympus_Mons")["verdict"] == "YES"
