"""Advisory: the computed facts that recommendations stand on.

Nothing here decides anything. It answers questions like "how long since B3 was last protected
against powdery mildew?" and "has that block had the same resistance group three times running?"
Hermes turns those into options for a manager to choose between (see the `advisory` skill).

**Why this is a tool and not left to the model** (the docs/07 §0 test): these are arithmetic over
the record that must come out the same every time. A recommendation whose supporting numbers were
re-derived by a language model each morning is a recommendation nobody can audit — and the whole
safety argument for letting Hermes advise at all is that every claim traces to a number you can
check.

**What is deliberately NOT here:** any notion of what you *should* spray. Hermes may only ever
propose products that exist in `products`, at their label rate, and only when verified. It does
not know your disease pressure, it cannot see your canopy, and it has no source for agronomy the
owner has not given it. That boundary is enforced by the data, not by prompt wording: there is no
tool that returns "the right product", because no such fact exists in this system.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import rows_to_dicts, utcnow

# Grapes accumulate growing degree days above 10 °C. This is the standard base for Vitis
# vinifera phenology and is what regional guidance is written against.
GDD_BASE_C = 10.0


def _today_local() -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(get_settings().timezone)).date()


# ──────────────────────────────────────────────────────────────────────────────
# Growing degree days
# ──────────────────────────────────────────────────────────────────────────────

def compute_gdd(
    daily: list[dict[str, Any]], base_c: float = GDD_BASE_C
) -> dict[str, Any]:
    """Accumulate growing degree days from daily min/max.

    GDD = max(0, (Tmax + Tmin) / 2 - base). Pure function over already-fetched days, for the
    same reason compute_spray_window is: Hermes fetches, we compute, and the number is stable.

    Days missing either temperature are skipped and counted, so a gap is visible rather than
    quietly depressing the total — an under-reported GDD makes everything look earlier than it
    is, which is the direction that gets a spray timed wrong.
    """
    total = 0.0
    used = 0
    skipped = 0
    for d in daily or []:
        if not isinstance(d, dict):
            skipped += 1
            continue
        tmax, tmin = d.get("tmax_c"), d.get("tmin_c")
        try:
            hi, lo = float(tmax), float(tmin)
        except (TypeError, ValueError):
            skipped += 1
            continue
        total += max(0.0, (hi + lo) / 2.0 - base_c)
        used += 1

    return {
        "gdd": round(total, 1),
        "days_used": used,
        "days_missing": skipped,
        "base_c": base_c,
        # A total built from a gappy record is not comparable to last season's.
        "complete": skipped == 0 and used > 0,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Powdery-mildew pressure proxy (GDM-spirit, no leaf-wetness sensor required)
# ──────────────────────────────────────────────────────────────────────────────

# Daytime hours when Erysiphe necator growth is possible (15–30 °C) and optimal (21–30 °C).
# Above ~32 °C the pathogen is heat-stressed; below ~10 it is effectively dormant.
_GROW_MIN_C = 15.0
_OPT_MIN_C = 21.0
_OPT_MAX_C = 30.0
_WET_PROB_PCT = 40.0
_WET_SKY_TOKENS = ("rain", "drizzle", "showers", "thunder", "wet")


def mildew_pressure(hourly: list[dict[str, Any]]) -> dict[str, Any]:
    """A 0–100 powdery-mildew pressure score for ONE site's next ~24h of forecast hours.

    This is deliberately a PROXY, not the UC Davis GDM: we have no leaf-wetness sensors, so it
    scores forecast hours instead of infection events. The shape follows GDM's logic — warm
    hours build pressure, warm+wet hours are where infection actually happens:

        score = min(100, infection_hours x 8 + optimal_warm_hours x 3)

      band <30 LOW -> standard interval holds
           30–59 MODERATE -> shorten toward the label's short end
           >=60 HIGH -> shortest safe interval; do not let cover lapse over this

    Pure function over already-fetched hours for the same reason as everything else here:
    Hermes fetches, the number is stable and auditable. It says nothing about which product,
    whether to spray, or what the canopy looks like.
    """
    from datetime import datetime

    if not hourly:
        return {"score": None, "band": "no_data", "hours_used": 0,
                "note": "no hourly data passed"}

    tzname = get_settings().timezone
    infection = warm = used = skipped = 0
    wet_hours = 0
    for h in hourly:
        if not isinstance(h, dict):
            skipped += 1
            continue
        t_raw, time_raw = h.get("temp_c"), h.get("time")
        try:
            t = float(t_raw)
            stamp = datetime.fromisoformat(str(time_raw))
        except (TypeError, ValueError):
            skipped += 1
            continue
        # Local wall-clock hour decides "daytime"; offset-aware stamps convert cleanly.
        try:
            local_hour = stamp.astimezone(ZoneInfo(tzname)).hour
        except (ValueError, KeyError):  # pragma: no cover - bad tz string in settings
            local_hour = stamp.hour
        if not (6 <= local_hour <= 20):
            continue
        used += 1
        sky = str(h.get("sky") or "").lower()
        prob = h.get("precip_prob_pct")
        try:
            prob_v = float(prob)
        except (TypeError, ValueError):
            prob_v = None
        wet = (prob_v is not None and prob_v >= _WET_PROB_PCT) or any(
            tok in sky for tok in _WET_SKY_TOKENS
        )
        if wet:
            wet_hours += 1
        if _GROW_MIN_C <= t <= 32.0:
            if wet and t >= _GROW_MIN_C:
                infection += 1
            if _OPT_MIN_C <= t <= _OPT_MAX_C:
                warm += 1

    score = min(100, infection * 8 + warm * 3)
    if used == 0:
        band, note = "no_data", "no daytime hours parseable"
    elif score >= 60:
        band, note = "HIGH", "shortest safe interval; do not let cover lapse"
    elif score >= 30:
        band, note = "MODERATE", "shorten toward the interval's short end"
    else:
        band, note = "LOW", "standard interval holds"

    return {
        "score": score,
        "band": band,
        "note": note,
        "hours_used": used,
        "infection_condition_hours": infection,
        "optimal_temp_hours": warm,
        "wet_hours": wet_hours,
        "hours_skipped": skipped,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Protection status: how long since each block was covered, per pest
# ──────────────────────────────────────────────────────────────────────────────

def spray_status(conn: sqlite3.Connection, block_code: str | None = None) -> dict[str, Any]:
    """Per block and target pest: last application, days since, and whether cover has lapsed.

    "Lapsed" means days-since exceeds the product's own `reapply_days` from its label. Where a
    product has no reapply_days recorded, the interval is reported as unknown rather than
    guessed — the honest answer, and it prompts someone to fill the field in.
    """
    sql = """
        SELECT s.id, s.log_date, s.product_name_raw, s.target_pest,
               b.code AS block_code, b.name AS block_name, b.site, b.acres,
               p.frac_group, p.reapply_days, p.verified, p.phi_days, p.trade_name
          FROM spray_log_current s
          JOIN blocks b ON b.id = s.block_id
          LEFT JOIN products p ON p.id = s.product_id
    """
    params: list[Any] = []
    if block_code:
        sql += " WHERE b.code = ?"
        params.append(block_code)
    sql += " ORDER BY s.log_date DESC, s.id DESC"

    rows = rows_to_dicts(conn.execute(sql, params).fetchall())
    today = _today_local()

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    history: dict[str, list[dict[str, Any]]] = {}

    for r in rows:
        pest = (r["target_pest"] or "unspecified").strip().lower()
        key = (r["block_code"], pest)
        history.setdefault(r["block_code"], []).append(r)
        if key in latest:
            continue  # rows are newest-first, so the first hit is the latest
        try:
            days = (today - date.fromisoformat(r["log_date"])).days
        except (TypeError, ValueError):
            days = None
        interval = r["reapply_days"]
        latest[key] = {
            "block_code": r["block_code"],
            "block_name": r["block_name"],
            "acres": r["acres"],
            "target_pest": pest,
            "last_product": r["product_name_raw"],
            "last_date": r["log_date"],
            "days_since": days,
            "reapply_days": interval,
            "lapsed": (
                None if (days is None or interval is None) else days > int(interval)
            ),
            "interval_known": interval is not None,
            "frac_group": r["frac_group"],
        }

    # Blocks with no spray history at all are their own kind of signal.
    covered = {b for b, _ in latest}
    never = rows_to_dicts(
        conn.execute(
            "SELECT code, name, site, acres FROM blocks WHERE active = 1"
            + (" AND code = ?" if block_code else ""),
            ([block_code] if block_code else []),
        ).fetchall()
    )
    never_sprayed = [b for b in never if b["code"] not in covered]

    return {
        "as_of": today.isoformat(),
        "protection": sorted(
            latest.values(), key=lambda x: (x["days_since"] is None, -(x["days_since"] or 0))
        ),
        "never_sprayed": never_sprayed,
        "rotation": _rotation(history),
    }


def _rotation(history: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Consecutive same-resistance-group applications per block.

    Repeating a FRAC group is how resistance gets bred: the surviving population is exactly the
    one that tolerated the last pass. Two in a row is normal practice; three is worth saying out
    loud, and the grower is the one who decides what to do about it.
    """
    out = []
    for block, rows in history.items():
        # rows are newest-first; walk forward while the group is unchanged
        groups = [r["frac_group"] for r in rows if r["frac_group"]]
        if not groups:
            continue
        current = groups[0]
        run = 0
        for g in groups:
            if g == current:
                run += 1
            else:
                break
        if run >= 2:
            out.append(
                {
                    "block_code": block,
                    "frac_group": current,
                    "consecutive": run,
                    "concern": "high" if run >= 3 else "watch",
                    "last_products": [r["product_name_raw"] for r in rows[:run]],
                }
            )
    return sorted(out, key=lambda x: -x["consecutive"])


# ──────────────────────────────────────────────────────────────────────────────
# Task cadence: what is overdue against this vineyard's own habit
# ──────────────────────────────────────────────────────────────────────────────

def task_cadence(conn: sqlite3.Connection, task_type: str | None = None) -> dict[str, Any]:
    """Days since each block last had each task type, against the median across all blocks.

    The comparison is to **your own practice**, not to a textbook. "B7 is 34 days since leaf
    removal; the median across your blocks is 19" is a fact about this vineyard that a manager
    can act on. A generic recommended interval would not be.
    """
    sql = """
        SELECT t.task_type, t.log_date, b.code AS block_code, b.name AS block_name, b.acres
          FROM task_log_current t
          JOIN blocks b ON b.id = t.block_id
    """
    params: list[Any] = []
    if task_type:
        sql += " WHERE t.task_type = ?"
        params.append(task_type)
    sql += " ORDER BY t.log_date DESC"

    rows = rows_to_dicts(conn.execute(sql, params).fetchall())
    today = _today_local()

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["block_code"], r["task_type"])
        if key in latest:
            continue
        try:
            days = (today - date.fromisoformat(r["log_date"])).days
        except (TypeError, ValueError):
            continue
        latest[key] = {
            "block_code": r["block_code"],
            "block_name": r["block_name"],
            "acres": r["acres"],
            "task_type": r["task_type"],
            "last_date": r["log_date"],
            "days_since": days,
        }

    by_task: dict[str, list[int]] = {}
    for v in latest.values():
        by_task.setdefault(v["task_type"], []).append(v["days_since"])

    medians = {
        t: sorted(vals)[len(vals) // 2] for t, vals in by_task.items() if vals
    }
    for v in latest.values():
        med = medians.get(v["task_type"])
        v["median_days_across_blocks"] = med
        # Only meaningful with a few blocks to compare against; below that it is noise.
        v["behind"] = (
            None if med is None or len(by_task[v["task_type"]]) < 3
            else v["days_since"] > med * 1.5
        )

    return {
        "as_of": today.isoformat(),
        "median_days_by_task": medians,
        "blocks": sorted(latest.values(), key=lambda x: -x["days_since"]),
    }


# ──────────────────────────────────────────────────────────────────────────────
# What may legitimately be proposed
# ──────────────────────────────────────────────────────────────────────────────

def spray_options(
    conn: sqlite3.Connection, block_code: str, target_pest: str
) -> dict[str, Any]:
    """Products in the shed that are registered for this pest, with what disqualifies each.

    This is the guardrail that makes advising safe: **Hermes cannot propose a product that is
    not in this list**, because the list is the shed. Anything it suggested beyond this would be
    a product nobody owns, at a rate nobody verified.

    Unverified products are returned but flagged unusable - visible, so a manager can see what
    verifying would unlock, and refused, so obligation 4 holds.
    """
    pest = (target_pest or "").strip().lower()
    products = rows_to_dicts(
        conn.execute("SELECT * FROM products ORDER BY trade_name").fetchall()
    )

    status = spray_status(conn, block_code)
    recent = {
        p["target_pest"]: p for p in status["protection"] if p["block_code"] == block_code
    }
    last_here = recent.get(pest)
    last_group = last_here["frac_group"] if last_here else None

    options = []
    for p in products:
        targets = [t.strip().lower() for t in (p["target_pests"] or "").split(",") if t.strip()]
        if pest and targets and pest not in targets:
            continue

        blockers = []
        if pest and not targets:
            # An empty registration is an unknown, not a match-all (audit #11): a product
            # with no pest registration on file must not read as usable for everything.
            blockers.append("no pest registration on file - cannot confirm it covers this pest")
        if not p["verified"]:
            blockers.append("unverified - no REI may be stated (obligation 4)")
        if not p["default_rate"]:
            blockers.append("no label rate on file")

        notes = []
        if last_group and p["frac_group"] and p["frac_group"] == last_group:
            notes.append(
                f"same resistance group ({p['frac_group']}) as the last application here"
            )
        if p["max_temp_c"] is not None:
            notes.append(f"do not apply above {p['max_temp_c']}°C")
        if p["phi_days"]:
            notes.append(f"pre-harvest interval {p['phi_days']} days")

        options.append(
            {
                "trade_name": p["trade_name"],
                "frac_group": p["frac_group"],
                "label_rate": f"{p['default_rate']} {p['rate_units'] or ''}".strip(),
                "rei_hours": p["rei_hours"] if p["verified"] else None,
                "phi_days": p["phi_days"],
                "max_temp_c": p["max_temp_c"],
                "usable": not blockers,
                "blockers": blockers,
                "notes": notes,
            }
        )

    return {
        "block_code": block_code,
        "target_pest": pest or None,
        "last_application": last_here,
        "options": options,
        "usable_count": sum(1 for o in options if o["usable"]),
    }


def log_recommendation(
    conn: sqlite3.Connection,
    subject: str,
    options: str,
    evidence: str,
    recommended: str | None = None,
) -> dict[str, Any]:
    """Record advice given, so it can be judged later.

    This is what turns recommendations from opinions into something that earns trust or loses
    it. At season end you can read back what Hermes advised, what was done, and what happened -
    and the advice it got wrong is the most valuable thing in the log.
    """
    from .db import audit, transaction

    with transaction(conn):
        row_id = audit(
            conn,
            actor="hermes",
            action="agent.recommendation",
            entity=subject,
            detail_json=json.dumps(
                {
                    "subject": subject,
                    "options": options,
                    "evidence": evidence,
                    "recommended": recommended,
                    "at": utcnow(),
                }
            ),
        )
    return {"logged": True, "audit_id": row_id}


def recent_recommendations(conn: sqlite3.Connection, days: int = 30) -> list[dict[str, Any]]:
    cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
    rows = rows_to_dicts(
        conn.execute(
            """SELECT at_utc, entity, detail_json FROM audit_log
               WHERE action = 'agent.recommendation' AND at_utc >= ?
               ORDER BY id DESC LIMIT 50""",
            (cutoff,),
        ).fetchall()
    )
    out = []
    for r in rows:
        try:
            out.append({"at_utc": r["at_utc"], **json.loads(r["detail_json"] or "{}")})
        except ValueError:
            out.append({"at_utc": r["at_utc"], "entity": r["entity"]})
    return out
