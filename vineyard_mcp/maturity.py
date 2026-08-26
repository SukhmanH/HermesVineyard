"""Fruit maturity against winery targets, and the water balance behind irrigation advice.

Same discipline as the rest of the kernel: this computes facts, it does not decide. Ripening
rate, days-to-target, reference evapotranspiration, water deficit — all arithmetic over data the
grower supplied or Hermes fetched. What to actually do with a block sits with a manager.

**The cross-check that motivates putting these two in one module:** post-veraison irrigation
dilutes sugar and pushes ripening back. A block behind its Brix target three weeks from harvest
is a block where watering works *against* the contract. Neither number tells you that on its own.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

from .config import get_settings
from .db import rows_to_dicts

# Solar constant, MJ / m² / min (FAO-56).
_GSC = 0.0820
# Latent heat of vaporisation: MJ/m² -> mm of water.
_LATENT = 2.45


def _today_local() -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def _d(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Fruit maturity
# ──────────────────────────────────────────────────────────────────────────────

def maturity_status(conn, block_code: str | None = None, season: int | None = None) -> dict:
    """Where the fruit is, where the winery wants it, and how fast the gap is closing.

    The useful number is not today's Brix — it is **°Bx per day between the last two samples**,
    which turns "we're at 21.4" into "about nine days out at the current rate". That projection
    is honest only if the samples are recent and there are at least two, so both conditions are
    reported rather than assumed.
    """
    season = season or _today_local().year
    today = _today_local()

    sql = """
        SELECT f.*, b.code AS block_code, b.name AS block_name, b.variety, b.acres
          FROM fruit_samples_current f
          JOIN blocks b ON b.id = f.block_id
    """
    params: list[Any] = []
    if block_code:
        sql += " WHERE b.code = ?"
        params.append(block_code)
    sql += " ORDER BY b.code, f.sampled_on DESC"
    samples = rows_to_dicts(conn.execute(sql, params).fetchall())

    tsql = """
        SELECT t.*, b.code AS block_code FROM fruit_targets t
          JOIN blocks b ON b.id = t.block_id
         WHERE t.season_year = ?
    """
    tparams: list[Any] = [season]
    if block_code:
        tsql += " AND b.code = ?"
        tparams.append(block_code)
    targets = {t["block_code"]: t for t in rows_to_dicts(conn.execute(tsql, tparams).fetchall())}

    by_block: dict[str, list[dict]] = {}
    for s in samples:
        by_block.setdefault(s["block_code"], []).append(s)

    out = []
    for code, rows in by_block.items():
        latest = rows[0]
        tgt = targets.get(code)
        sampled = _d(latest["sampled_on"])
        age = (today - sampled).days if sampled else None

        # Ripening rate from the two most recent samples with a Brix reading.
        with_brix = [r for r in rows if r["brix"] is not None]
        rate = None
        rate_span = None
        if len(with_brix) >= 2:
            a, b = with_brix[0], with_brix[1]
            da, dbb = _d(a["sampled_on"]), _d(b["sampled_on"])
            if da and dbb and da != dbb:
                span = (da - dbb).days
                if span > 0:
                    rate = round((a["brix"] - b["brix"]) / span, 3)
                    rate_span = span

        entry = {
            "block_code": code,
            "block_name": latest["block_name"],
            "variety": latest["variety"],
            "acres": latest["acres"],
            "last_sample": latest["sampled_on"],
            "sample_age_days": age,
            # Ripening moves fast late in the season; a fortnight-old number is not where the
            # fruit is now, and harvest calls get made on these.
            "sample_stale": (age is not None and age > 7),
            "brix": latest["brix"],
            "ta_g_l": latest["ta_g_l"],
            "ph": latest["ph"],
            "brix_per_day": rate,
            "rate_span_days": rate_span,
            "samples_this_season": len(rows),
            "target": None,
            "brix_gap": None,
            "projected_days_to_target": None,
            "projected_date": None,
            "in_spec": None,
            "notes": [],
        }

        if tgt:
            entry["target"] = {
                "winery": tgt["winery"],
                "brix": [tgt["target_brix_min"], tgt["target_brix_max"]],
                "ta_g_l": [tgt["target_ta_min"], tgt["target_ta_max"]],
                "ph": [tgt["target_ph_min"], tgt["target_ph_max"]],
                "harvest_window": [tgt["harvest_window_from"], tgt["harvest_window_to"]],
                "contract_notes": tgt["contract_notes"],
            }
            lo, hi = tgt["target_brix_min"], tgt["target_brix_max"]
            if latest["brix"] is not None and lo is not None:
                gap = round(lo - latest["brix"], 2)
                entry["brix_gap"] = gap
                if gap <= 0:
                    entry["projected_days_to_target"] = 0
                    if hi is not None and latest["brix"] > hi:
                        entry["notes"].append(
                            f"ABOVE the contract window ({latest['brix']} > {hi}) - "
                            "overripe fruit cannot be un-ripened"
                        )
                elif rate and rate > 0:
                    days = math.ceil(gap / rate)
                    entry["projected_days_to_target"] = days
                    entry["projected_date"] = (today + timedelta(days=days)).isoformat()
                elif rate is not None and rate <= 0:
                    entry["notes"].append(
                        "Brix has not risen between the last two samples - no projection possible"
                    )

            entry["in_spec"] = _in_spec(latest, tgt)

            # A harvest window the projection lands outside of is the whole point of tracking it.
            pd = _d(entry.get("projected_date"))
            wf, wt = _d(tgt["harvest_window_from"]), _d(tgt["harvest_window_to"])
            if pd and wt and pd > wt:
                entry["notes"].append(
                    f"projected ripeness {pd.isoformat()} falls AFTER the contract window "
                    f"closes {wt.isoformat()}"
                )
            elif pd and wf and pd < wf:
                entry["notes"].append(
                    f"projected ripeness {pd.isoformat()} falls BEFORE the window opens "
                    f"{wf.isoformat()}"
                )

        if len(with_brix) < 2:
            entry["notes"].append("only one Brix sample - no ripening rate yet")
        if latest["sample_size"] is not None and latest["sample_size"] < 100:
            entry["notes"].append(
                f"sample of {latest['sample_size']} berries is small; Brix varies a lot berry "
                "to berry"
            )

        out.append(entry)

    # Blocks with a contract but no samples at all are the ones most likely to be forgotten.
    sampled_blocks = set(by_block)
    unsampled = [
        {"block_code": c, "winery": t["winery"], "harvest_window":
         [t["harvest_window_from"], t["harvest_window_to"]]}
        for c, t in targets.items() if c not in sampled_blocks
    ]

    return {
        "as_of": today.isoformat(),
        "season": season,
        "blocks": sorted(out, key=lambda x: (x["brix_gap"] is None, -(x["brix_gap"] or 0))),
        "contracted_but_unsampled": unsampled,
    }


def _in_spec(sample: dict, tgt: dict) -> dict[str, Any]:
    """Per-metric pass/fail. Sugar alone is not ripeness - TA and pH decide the wine."""
    def check(value, lo, hi):
        if value is None or (lo is None and hi is None):
            return None
        if lo is not None and value < lo:
            return "below"
        if hi is not None and value > hi:
            return "above"
        return "in"

    return {
        "brix": check(sample["brix"], tgt["target_brix_min"], tgt["target_brix_max"]),
        "ta_g_l": check(sample["ta_g_l"], tgt["target_ta_min"], tgt["target_ta_max"]),
        "ph": check(sample["ph"], tgt["target_ph_min"], tgt["target_ph_max"]),
    }


def record_sample(
    conn,
    block_code: str,
    sampled_on: str | None = None,
    brix: float | None = None,
    ta_g_l: float | None = None,
    ph: float | None = None,
    berry_weight_g: float | None = None,
    sample_size: int | None = None,
    method: str | None = None,
    notes: str | None = None,
    raw_message: str = "",
    wa_phone: str | None = None,
) -> dict[str, Any]:
    """Record a maturity sample. At least one measurement required.

    Append-only, like the compliance tables: these numbers drive harvest calls and contract
    conformance, and a retro-edited ripening curve is one nobody can trust.
    """
    from .compliance import err, resolve_block
    from .db import row_to_dict, transaction, utcnow

    block = resolve_block(conn, block_code)
    if block is None:
        return err("unknown_block", given=block_code)
    if brix is None and ta_g_l is None and ph is None:
        return err("no_measurement", hint="need at least one of brix, ta_g_l, ph")
    for name, value, lo, hi in (
        ("brix", brix, 0, 40), ("ta_g_l", ta_g_l, 0, 30), ("ph", ph, 2, 5),
    ):
        if value is not None and not (lo <= float(value) <= hi):
            # A refractometer misread or a transcription slip lands here. Out-of-range values
            # would otherwise poison the ripening rate and every projection off it.
            return err("implausible_value", field=name, given=value, expected=f"{lo}-{hi}")

    contact_id = None
    if wa_phone:
        row = row_to_dict(
            conn.execute("SELECT id FROM contacts WHERE wa_phone = ?", (wa_phone,)).fetchone()
        )
        contact_id = row["id"] if row else None

    day = sampled_on or _today_local().isoformat()
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO fruit_samples (block_id, sampled_on, brix, ta_g_l, ph,
                   berry_weight_g, sample_size, sampled_by_contact_id, method, notes,
                   raw_message, created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (block["id"], day, brix, ta_g_l, ph, berry_weight_g, sample_size,
             contact_id, method, notes, raw_message, utcnow()),
        )
        sample_id = int(cur.lastrowid)

    return {
        "recorded": row_to_dict(
            conn.execute("SELECT * FROM fruit_samples WHERE id = ?", (sample_id,)).fetchone()
        ),
        "block_code": block["code"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Water balance
# ──────────────────────────────────────────────────────────────────────────────

def compute_et0(daily: list[dict[str, Any]], latitude: float) -> dict[str, Any]:
    """Reference evapotranspiration (mm/day) by Hargreaves-Samani.

    FAO-56 recommends Hargreaves precisely when only temperature is available, which is our
    situation: ECCC citypage gives min/max but no radiation, humidity or wind at daily scale.

        ET0 = 0.0023 * (Ra / 2.45) * (Tmean + 17.8) * sqrt(Tmax - Tmin)

    It is an **approximation**, and it is reported as one. It tends to over-predict in humid
    conditions and under-predict in windy ones. Good enough to say "this block is running a
    deficit"; not good enough to prescribe litres, which is why nothing here does.
    """
    days = []
    total = 0.0
    skipped = 0
    for d in daily or []:
        if not isinstance(d, dict):
            skipped += 1
            continue
        try:
            hi, lo = float(d["tmax_c"]), float(d["tmin_c"])
            when = date.fromisoformat(str(d["date"]))
        except (TypeError, ValueError, KeyError):
            skipped += 1
            continue
        if hi < lo:
            skipped += 1
            continue

        j = when.timetuple().tm_yday
        phi = math.radians(latitude)
        dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
        decl = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
        # Guard the poles / polar day, where the arccos argument leaves [-1, 1].
        x = max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl)))
        ws = math.acos(x)
        ra = (24 * 60 / math.pi) * _GSC * dr * (
            ws * math.sin(phi) * math.sin(decl)
            + math.cos(phi) * math.cos(decl) * math.sin(ws)
        )
        tmean = (hi + lo) / 2
        et0 = 0.0023 * (ra / _LATENT) * (tmean + 17.8) * math.sqrt(hi - lo)
        et0 = max(0.0, round(et0, 2))
        total += et0
        days.append({"date": when.isoformat(), "et0_mm": et0})

    return {
        "et0_total_mm": round(total, 1),
        "days": days,
        "days_used": len(days),
        "days_missing": skipped,
        "complete": skipped == 0 and bool(days),
        "method": "hargreaves-samani",
        "caveat": "temperature-only approximation; over-predicts in humid air, under in wind",
    }


def water_balance(
    conn,
    block_code: str,
    rain_mm: float,
    et0_mm: float,
    kc: float | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """Rain in, estimated crop water use out, and when this block was last irrigated.

    Crop use = ET0 x Kc. Kc varies by growth stage and by how the vineyard is farmed, so it
    comes from settings rather than being assumed here.

    **No volume is ever returned.** Litres depend on soil type, rooting depth, emitter rate and
    spacing. Where those are recorded on the block a run-time estimate is offered; where they
    are not, the answer is a deficit in millimetres and an explicit note that the conversion is
    unavailable. Inventing a number here would be inventing agronomy (docs/01 §D12).
    """
    from .compliance import err, resolve_block

    block = resolve_block(conn, block_code)
    if block is None:
        return err("unknown_block", given=block_code)

    settings = get_settings()
    kc = kc if kc is not None else settings.irrigation.kc_default
    today = _today_local()
    since = (today - timedelta(days=days)).isoformat()

    last = conn.execute(
        """SELECT log_date, hours_total, quantity, quantity_unit FROM task_log_current
            WHERE block_id = ? AND task_type = 'riego'
            ORDER BY log_date DESC LIMIT 1""",
        (block["id"],),
    ).fetchone()
    last_irrigation = last["log_date"] if last else None
    days_since = None
    if last_irrigation:
        d = _d(last_irrigation)
        days_since = (today - d).days if d else None

    etc = round(et0_mm * kc, 1)
    deficit = round(etc - rain_mm, 1)

    notes = []
    runtime_hint = None
    if block.get("emitter_lph") and block.get("emitters_per_vine") and block.get("vines_per_acre"):
        # mm over an acre = litres / 4046.86 m² * 1000 -> 1 mm = 4.047 L/m² = 4046.86 L/acre
        litres_needed = max(0.0, deficit) * 4046.86
        lph_per_acre = (
            block["emitter_lph"] * block["emitters_per_vine"] * block["vines_per_acre"]
        )
        if lph_per_acre > 0:
            runtime_hint = round(litres_needed / lph_per_acre, 1)
    else:
        notes.append(
            "no emitter rate / vine density on this block - deficit reported in mm only, "
            "no run time can be estimated"
        )

    if deficit <= 0:
        notes.append("rainfall met or exceeded estimated crop use over the window")

    return {
        "block_code": block["code"],
        "window_days": days,
        "since": since,
        "rain_mm": round(rain_mm, 1),
        "et0_mm": round(et0_mm, 1),
        "kc": kc,
        "crop_use_mm": etc,
        "deficit_mm": deficit,
        "last_irrigation": last_irrigation,
        "days_since_irrigation": days_since,
        "estimated_run_hours_per_acre": runtime_hint,
        "notes": notes,
        "caveat": "ET0 is a temperature-only estimate; treat as a direction, not a dose",
    }


# ──────────────────────────────────────────────────────────────────────────────
# The cross-check
# ──────────────────────────────────────────────────────────────────────────────

def irrigation_vs_ripening(conn, block_code: str, balance: dict, maturity: dict) -> dict:
    """Reconcile a water deficit against the contract Brix target.

    This is the one piece of reasoning neither number gives you alone. Post-veraison irrigation
    moves water into the berry: it dilutes sugar and pushes ripening back. So a block that is
    *behind* its Brix target with the harvest window closing is one where watering works against
    the contract - and a block already at spec is one where it does not.

    Nothing here decides. It states the tension so a manager can weigh vine health against the
    delivery spec, which is their call and genuinely not an obvious one.
    """
    if balance.get("error"):
        return balance

    entry = next(
        (b for b in maturity.get("blocks", []) if b["block_code"] == balance["block_code"]),
        None,
    )
    deficit = balance.get("deficit_mm") or 0.0
    settings = get_settings()
    threshold = settings.irrigation.deficit_alert_mm
    significant = deficit >= threshold

    out = {
        "block_code": balance["block_code"],
        "deficit_mm": deficit,
        "deficit_significant": significant,
        "days_since_irrigation": balance.get("days_since_irrigation"),
        "brix": entry.get("brix") if entry else None,
        "brix_gap": entry.get("brix_gap") if entry else None,
        "projected_days_to_target": entry.get("projected_days_to_target") if entry else None,
        "tension": None,
        "considerations": [],
    }

    if entry is None:
        out["considerations"].append(
            "no maturity samples for this block - the water decision has no ripening context"
        )
        return out

    gap = entry.get("brix_gap")
    days_out = entry.get("projected_days_to_target")

    if significant and gap is not None and gap > 0 and days_out is not None and days_out <= 21:
        out["tension"] = "irrigating_may_delay_contract_ripeness"
        out["considerations"].append(
            f"{gap} Bx below the contract minimum, roughly {days_out} days to target at the "
            f"current rate. The {deficit:g} mm deficit is real, but water now dilutes sugar and "
            "pushes that date out."
        )
        out["considerations"].append(
            "This is a manager call: vine stress and next season's wood on one side, the "
            "delivery spec on the other. A smaller application is the usual middle ground."
        )
    elif significant and gap is not None and gap <= 0:
        out["tension"] = "target_met_water_freely"
        out["considerations"].append(
            "Brix is already at or past the contract minimum, so the ripening argument against "
            "irrigating does not apply. Vine health decides."
        )
    elif significant:
        out["tension"] = "deficit_without_ripening_context"
        out["considerations"].append(
            f"{deficit:g} mm deficit, and no contract target on file for this block - purely a "
            "vine-health call."
        )
    else:
        out["considerations"].append(
            f"deficit of {deficit:g} mm is below the {threshold:g} mm threshold - not worth "
            "acting on yet"
        )

    if entry.get("sample_stale"):
        out["considerations"].append(
            f"the Brix reading is {entry['sample_age_days']} days old; ripening moves fast this "
            "time of year, so re-sample before deciding on it"
        )
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Contract targets: settable by message, not only by CSV
# ──────────────────────────────────────────────────────────────────────────────

def _plausible(name: str, value, lo: float, hi: float):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} is not a number: {value!r}"
    if not (lo <= v <= hi):
        return f"{name} of {v} is outside the plausible range {lo}-{hi}"
    return None


def set_fruit_target(
    conn,
    block_code: str,
    winery: str,
    target_brix_min: float | None = None,
    target_brix_max: float | None = None,
    target_ta_min: float | None = None,
    target_ta_max: float | None = None,
    target_ph_min: float | None = None,
    target_ph_max: float | None = None,
    harvest_window_from: str | None = None,
    harvest_window_to: str | None = None,
    contract_notes: str | None = None,
    season_year: int | None = None,
    set_by: str = "",
) -> dict[str, Any]:
    """Record or update what a winery wants from a block. Managers set this by message.

    Not append-only — contracts genuinely get renegotiated mid-season — but every change writes
    the BEFORE and AFTER to audit_log. "Who moved the Brix target, and when" is a question that
    gets asked when a load is disputed, and it should have an answer.

    Validation is strict because the failure mode is quiet: a target typed as 2.3 instead of 23
    does not error, it just silently reports every block as ripe.
    """
    from .compliance import err, resolve_block
    from .db import audit, row_to_dict, transaction

    block = resolve_block(conn, block_code)
    if block is None:
        return err("unknown_block", given=block_code)
    if not (winery or "").strip():
        return err("winery_required", hint="which winery is this contract with?")

    problems = [
        p for p in (
            _plausible("target_brix_min", target_brix_min, 10, 35),
            _plausible("target_brix_max", target_brix_max, 10, 35),
            _plausible("target_ta_min", target_ta_min, 1, 20),
            _plausible("target_ta_max", target_ta_max, 1, 20),
            _plausible("target_ph_min", target_ph_min, 2.5, 4.5),
            _plausible("target_ph_max", target_ph_max, 2.5, 4.5),
        ) if p
    ]
    for lo, hi, label in (
        (target_brix_min, target_brix_max, "brix"),
        (target_ta_min, target_ta_max, "ta"),
        (target_ph_min, target_ph_max, "ph"),
    ):
        if lo is not None and hi is not None and float(lo) > float(hi):
            problems.append(f"{label} minimum {lo} is above its maximum {hi}")

    wf, wt = _d(harvest_window_from), _d(harvest_window_to)
    if harvest_window_from and wf is None:
        problems.append(f"harvest_window_from {harvest_window_from!r} is not YYYY-MM-DD")
    if harvest_window_to and wt is None:
        problems.append(f"harvest_window_to {harvest_window_to!r} is not YYYY-MM-DD")
    if wf and wt and wf > wt:
        problems.append("harvest window opens after it closes")

    if problems:
        return err("invalid_target", problems=problems)

    season = season_year or _today_local().year
    before = row_to_dict(
        conn.execute(
            """SELECT * FROM fruit_targets
                WHERE block_id = ? AND season_year = ? AND winery = ?""",
            (block["id"], season, winery),
        ).fetchone()
    )

    fields = {
        "target_brix_min": target_brix_min, "target_brix_max": target_brix_max,
        "target_ta_min": target_ta_min, "target_ta_max": target_ta_max,
        "target_ph_min": target_ph_min, "target_ph_max": target_ph_max,
        "harvest_window_from": harvest_window_from, "harvest_window_to": harvest_window_to,
        "contract_notes": contract_notes,
    }

    with transaction(conn):
        if before:
            # Only overwrite what was supplied; a partial update must not blank the rest.
            supplied = {k: v for k, v in fields.items() if v is not None}
            if supplied:
                sets = ", ".join(f"{k} = ?" for k in supplied)
                conn.execute(
                    f"UPDATE fruit_targets SET {sets} WHERE id = ?",
                    [*supplied.values(), before["id"]],
                )
            target_id = before["id"]
        else:
            cols = ["block_id", "season_year", "winery", *fields]
            conn.execute(
                f"INSERT INTO fruit_targets ({','.join(cols)}) "
                f"VALUES ({','.join('?' for _ in cols)})",
                [block["id"], season, winery, *fields.values()],
            )
            target_id = int(
                conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
            )

        after = row_to_dict(
            conn.execute("SELECT * FROM fruit_targets WHERE id = ?", (target_id,)).fetchone()
        )
        changed = {
            k: [before.get(k) if before else None, after.get(k)]
            for k in fields
            if not before or before.get(k) != after.get(k)
        }
        audit(
            conn,
            actor=set_by or "hermes",
            action="fruit_target.set" if not before else "fruit_target.changed",
            entity="fruit_targets",
            entity_id=target_id,
            detail_json=json.dumps(
                {"block": block["code"], "winery": winery, "season": season,
                 "changed": changed}
            ),
        )

    return {
        "target": after,
        "block_code": block["code"],
        "created": before is None,
        "changed": changed,
    }


def get_fruit_targets(conn, block_code: str | None = None, season: int | None = None) -> dict:
    """Contract targets on file, with when each was last changed and by whom."""
    season = season or _today_local().year
    sql = """
        SELECT t.*, b.code AS block_code, b.name AS block_name, b.variety
          FROM fruit_targets t JOIN blocks b ON b.id = t.block_id
         WHERE t.season_year = ?
    """
    params: list[Any] = [season]
    if block_code:
        sql += " AND b.code = ?"
        params.append(block_code)
    rows = rows_to_dicts(conn.execute(sql + " ORDER BY b.code", params).fetchall())

    for r in rows:
        last = conn.execute(
            """SELECT at_utc, actor FROM audit_log
                WHERE entity = 'fruit_targets' AND entity_id = ?
                ORDER BY id DESC LIMIT 1""",
            (r["id"],),
        ).fetchone()
        r["last_set_at"] = last["at_utc"] if last else None
        r["last_set_by"] = last["actor"] if last else None

    return {"season": season, "targets": rows}


def correct_sample(
    conn, sample_id: int, raw_message: str = "", set_by: str = "", **changes
) -> dict[str, Any]:
    """Supersede a sample with a corrected one. The original is never touched.

    Same shape as the compliance corrections: fruit_samples is append-only because a ripening
    curve that can be quietly rewritten is one nobody can trust when a delivery is disputed. A
    mistyped Brix therefore gets a new row pointing at the old one, and both survive.
    """
    from .compliance import err
    from .db import audit, row_to_dict, transaction, utcnow

    original = row_to_dict(
        conn.execute("SELECT * FROM fruit_samples WHERE id = ?", (sample_id,)).fetchone()
    )
    if original is None:
        return err("unknown_sample", sample_id=sample_id)

    superseded = conn.execute(
        "SELECT id FROM fruit_samples WHERE corrects_sample_id = ?", (sample_id,)
    ).fetchone()
    if superseded:
        return err("already_superseded", sample_id=sample_id,
                   superseded_by=superseded["id"])

    allowed = ("brix", "ta_g_l", "ph", "berry_weight_g", "sample_size", "sampled_on",
               "method", "notes")
    bad = [k for k in changes if k not in allowed]
    if bad:
        return err("unknown_field", fields=bad, allowed=list(allowed))

    merged = {k: changes.get(k, original[k]) for k in allowed}
    for name, lo, hi in (("brix", 0, 40), ("ta_g_l", 0, 30), ("ph", 2, 5)):
        problem = _plausible(name, merged[name], lo, hi)
        if problem:
            return err("implausible_value", detail=problem)

    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO fruit_samples (block_id, sampled_on, brix, ta_g_l, ph,
                   berry_weight_g, sample_size, sampled_by_contact_id, method, notes,
                   raw_message, created_at_utc, corrects_sample_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (original["block_id"], merged["sampled_on"], merged["brix"], merged["ta_g_l"],
             merged["ph"], merged["berry_weight_g"], merged["sample_size"],
             original["sampled_by_contact_id"], merged["method"], merged["notes"],
             (raw_message or original["raw_message"]), utcnow(), sample_id),
        )
        new_id = int(cur.lastrowid)
        audit(conn, actor=set_by or "hermes", action="fruit_sample.corrected",
              entity="fruit_samples", entity_id=new_id,
              detail_json=json.dumps({"corrects": sample_id, "changes": changes}))

    return {
        "corrected": row_to_dict(
            conn.execute("SELECT * FROM fruit_samples WHERE id = ?", (new_id,)).fetchone()
        ),
        "supersedes": sample_id,
        "original": original,
    }
