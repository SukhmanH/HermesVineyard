"""compute_spray_window() — and nothing else.

This is a PURE function over already-fetched hours. It does not know what ECCC is, does not make
network calls, and cannot be persuaded. Hermes fetches the forecast itself (docs/01 §D9) and
feeds it here; that separation is what lets the verdict come from any rung of the degrade ladder,
including one nobody has written yet.

Why it exists at all, when Hermes could do this arithmetic itself: it must **fail safe to NO**
when the data is stale or the wind is missing, and "behaves correctly when the reasoning layer is
impaired" is not a property a reasoning layer can provide for itself. On a bad model day, a
degraded provider, or a prompt-injected message, this function still says NO.

Hermes may not soften a NO into a YES (docs/01 §3).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import SprayWindow

# Reason codes are stable identifiers, not prose. The agent renders them into Spanish, Gurmukhi
# or English from templates/{lang}.yaml — tools never write user-facing sentences.
REASON_OK = "ok"
REASON_NO_DATA = "no_data"
REASON_STALE = "stale_data"
REASON_MISSING_WIND = "missing_wind"
REASON_WIND_HIGH = "wind_too_high"
REASON_WIND_CALM = "wind_too_calm"
REASON_GUSTS = "gusts_too_high"
REASON_TEMP_HIGH = "temp_too_high"
REASON_TEMP_LOW = "temp_too_low"
REASON_RAIN = "rain_risk"
REASON_TOO_SHORT = "window_too_short"


def _parse_hour(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    """Coerce to float, treating None/''/non-numeric as missing rather than as zero.

    This matters more than it looks: a missing wind reading silently coerced to 0.0 would read
    as 'dead calm' and, worse, could pass a naive threshold check. Missing must stay missing.
    """
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and not isinstance(value, bool) else None


def _gust_coverage(hours_: list[dict[str, Any]]) -> str:
    """How much of the daytime data actually carried gust readings."""
    gusts = [_num(h.get("gust_kmh")) for h in hours_]
    have = sum(1 for g in gusts if g is not None)
    if have == 0:
        return "missing"
    return "present" if have == len(gusts) else "partial"


def _hour_ok(
    hour: dict[str, Any], cfg: SprayWindow, temp_ceiling: float
) -> tuple[bool, str | None]:
    """Is this single hour sprayable? Returns (ok, first failing reason)."""
    wind = _num(hour.get("wind_kmh"))
    if wind is None:
        return False, REASON_MISSING_WIND
    if wind > cfg.wind_max_kmh:
        return False, REASON_WIND_HIGH
    if wind < cfg.wind_min_kmh:
        # Dead calm is not "extra safe" — it means a temperature inversion can hold spray
        # in suspension and carry it off-target. This is a real rejection, not a formality.
        return False, REASON_WIND_CALM

    gust = _num(hour.get("gust_kmh"))
    # Missing gusts cannot establish a safe drift gate. Only covered hours may qualify.
    if gust is None or gust < 0:
        return False, "missing_gusts"
    if gust > cfg.gust_max_kmh:
        return False, REASON_GUSTS

    temp = _num(hour.get("temp_c"))
    if temp is not None:
        if temp > temp_ceiling:
            return False, REASON_TEMP_HIGH
        if temp < cfg.temp_min_c:
            return False, REASON_TEMP_LOW

    prob = _num(hour.get("precip_prob_pct"))
    if prob is not None and prob > cfg.rain_prob_max_pct:
        return False, REASON_RAIN

    return True, None


def compute_spray_window(
    hourly: list[dict[str, Any]] | None,
    cfg: SprayWindow | None = None,
    product: dict[str, Any] | None = None,
    *,
    source: str | None = None,
    age_hours: float | None = None,
    tz: str = "America/Vancouver",
) -> dict[str, Any]:
    """Decide whether there is a sprayable window today.

    `hourly` entries use: time (ISO), wind_kmh, gust_kmh, temp_c, precip_prob_pct, rh_pct.
    `product` may carry max_temp_c and rainfast_hours, which override the defaults.

    **Timezone matters and is not optional.** ECCC publishes hours in UTC; the day bounds
    (day_start_hour / day_end_hour) and the reported window times are meaningless unless both
    are in the vineyard's local time. Aware timestamps are converted to `tz`; naive ones are
    assumed already local. Caught in live testing, where a UTC feed produced a confident
    "05:00-09:00" window that was really 22:00-02:00 Pacific - the middle of the night, which
    the daylight filter existed specifically to exclude.

    Returns a structured verdict. Never raises on bad input — a crash here would take out the
    morning brief, and the whole point is to degrade to NO rather than to nothing.
    """
    cfg = cfg or SprayWindow()

    verdict: dict[str, Any] = {
        "verdict": "NO",
        "reason": REASON_NO_DATA,
        "best_window": None,
        "all_windows": [],
        "source": source,
        "age_hours": age_hours,
        "stale": False,
        "temp_ceiling_c": cfg.temp_max_c,
        "product": (product or {}).get("trade_name"),
        "timezone": tz,
    }

    if not hourly:
        return verdict

    # ── Fail-safe gate 1: stale data. Checked BEFORE any analysis, so no amount of
    # good-looking forecast detail can produce a YES from an old file.
    if age_hours is not None and age_hours > cfg.max_data_age_hours:
        verdict["stale"] = True
        verdict["reason"] = REASON_STALE
        return verdict

    # Product ceiling overrides the general one (sulfur burns fruit above ~30 C).
    ceiling = cfg.temp_max_c
    prod_ceiling = _num((product or {}).get("max_temp_c"))
    if prod_ceiling is not None:
        ceiling = min(ceiling, prod_ceiling)
    verdict["temp_ceiling_c"] = ceiling

    rainfast = _num((product or {}).get("rainfast_hours"))
    rain_free_hours = int(rainfast) if rainfast is not None else cfg.rain_free_hours_after

    # Normalize and keep only daytime hours, in order.
    try:
        local_tz = ZoneInfo(tz)
    except Exception:  # noqa: BLE001 - an unknown tz must not take out the brief
        local_tz = ZoneInfo("America/Vancouver")

    parsed: list[dict[str, Any]] = []
    for raw in hourly:
        if not isinstance(raw, dict):
            continue
        when = _parse_hour(raw.get("time"))
        if when is None:
            continue
        # Convert to local BEFORE any hour-of-day reasoning. A naive timestamp is taken as
        # already local; an aware one (ECCC is UTC) is converted.
        if when.tzinfo is not None:
            when = when.astimezone(local_tz)
        parsed.append({**raw, "_dt": when})
    parsed.sort(key=lambda h: h["_dt"])

    if not parsed:
        return verdict

    # ── Fail-safe gate 2: no wind data anywhere. A spray call without wind is not a call.
    if all(_num(h.get("wind_kmh")) is None for h in parsed):
        verdict["reason"] = REASON_MISSING_WIND
        return verdict

    day = [h for h in parsed if cfg.day_start_hour <= h["_dt"].hour < cfg.day_end_hour]
    if not day:
        verdict["reason"] = REASON_NO_DATA
        return verdict

    # Say so out loud (audit #1): a YES must not imply the drift gate was checked. ECCC
    # publishes gusts only on some hours (verified live 2026-09-16: gusts on the windy
    # afternoon hours, none on the calm morning), so coverage is declared per verdict and
    # per window: a window with any gust-less hour was judged on wind alone.
    verdict["gust_data"] = _gust_coverage(day)

    # Evaluate each daytime hour, then extend rain checking past the run by rain_free_hours:
    # a spray that gets rained off two hours later was not a usable window.
    by_time = {h["_dt"]: h for h in parsed}
    ordered_times = sorted(by_time)

    flags: list[tuple[dict[str, Any], bool, str | None]] = []
    for h in day:
        ok, reason = _hour_ok(h, cfg, ceiling)
        if ok and rain_free_hours > 0:
            idx = ordered_times.index(h["_dt"])
            for future in ordered_times[idx + 1 : idx + 1 + rain_free_hours]:
                prob = _num(by_time[future].get("precip_prob_pct"))
                if prob is not None and prob > cfg.rain_prob_max_pct:
                    ok, reason = False, REASON_RAIN
                    break
        flags.append((h, ok, reason))

    # Contiguous runs of sprayable hours.
    windows: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []

    def close_run() -> None:
        if len(run) >= cfg.min_window_hours:
            windows.append(
                {
                    "start": run[0]["_dt"].strftime("%H:%M"),
                    "end": run[-1]["_dt"].strftime("%H:%M"),
                    "hours": len(run),
                    "max_wind_kmh": max(
                        (_num(h.get("wind_kmh")) or 0.0) for h in run
                    ),
                    "max_temp_c": max(
                        (_num(h.get("temp_c")) or -99.0) for h in run
                    ),
                    # A window containing any gust-less hour was judged on wind alone.
                    "gusts_checked": all(_num(h.get("gust_kmh")) is not None for h in run),
                }
            )

    for h, ok, _reason in flags:
        if ok:
            run.append(h)
        else:
            close_run()
            run = []
    close_run()

    verdict["all_windows"] = windows

    if windows:
        best = max(windows, key=lambda w: w["hours"])
        verdict["verdict"] = "YES"
        verdict["reason"] = REASON_OK
        verdict["best_window"] = best
        return verdict

    # No usable window. Report the constraint that blocked the most daytime hours, so the
    # message can say WHY rather than just no ("demasiado viento" vs "riesgo de lluvia").
    counts: dict[str, int] = {}
    for _h, ok, reason in flags:
        if not ok and reason:
            counts[reason] = counts.get(reason, 0) + 1

    if counts:
        verdict["reason"] = max(counts, key=lambda k: counts[k])
        verdict["blocked_hours"] = counts
        if verdict["reason"] == "missing_gusts":
            verdict["reason_template"] = "spray_missing_gusts"
    else:
        # Every hour passed individually but no run reached min_window_hours.
        verdict["reason"] = REASON_TOO_SHORT

    return verdict
