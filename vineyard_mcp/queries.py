"""Reads, decisions, and job bookkeeping.

Broad and composable by design (docs/07 §0): `query_logs(filters)` beats five fixed report
builders, because the first answers a question nobody anticipated and the second only answers the
five we thought of. Every narrow tool added here is a decision taken away from Hermes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import audit, row_to_dict, rows_to_dicts, transaction, utcnow

# The canonical site vocabulary, mirroring the CHECK on blocks.site. The southernmost
# properties register under `oliver`, whose forecast already comes from the Osoyoos station.
SITE_KEYS = frozenset({"penticton", "naramata", "oliver"})


def _today_local() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).strftime("%Y-%m-%d")


def resolve_contact(conn: sqlite3.Connection, identifier: str) -> dict[str, Any]:
    """Look up a contact by EITHER their phone number or their WhatsApp lid.

    WhatsApp identifies a sender by wa_phone for some platforms and by a device-linked
    "...@lid" identifier for others - found live 2026-08-22, where the gateway logged a real
    contact's messages under a lid with no phone visible at all. Call this FIRST on any inbound
    message before deciding how to handle it: language, reports_in, and every skill that reads
    from `contacts` depend on getting the right row.
    """
    row = row_to_dict(
        conn.execute(
            "SELECT * FROM contacts WHERE wa_phone = ? OR wa_lid = ?",
            (identifier, identifier),
        ).fetchone()
    )
    if row is None:
        return {"found": False, "identifier": identifier}
    return {"found": True, "contact": row}


def record_daily_obs(
    conn: sqlite3.Connection,
    site: str,
    obs_date: str,
    tmax_c: float | None = None,
    tmin_c: float | None = None,
    precip_mm: float | None = None,
    source: str = "wunderground",
) -> dict[str, Any]:
    """Store one measured day for a site (upsert by site+date — instrument data, not law).

    This is what makes season-over-season GDD pace computable from our own record instead of
    ad-hoc fetches. Feed it from the Wunderground hourly_7day actuals (or ECCC daily) once per
    day; refetching a date replaces it.
    """
    import re as _re

    # daily_obs carries no CHECK on `site` (it arrived as an additive migration, and adding a
    # constraint to a live table means rebuilding it). Validate here instead: a typo would
    # otherwise create a phantom site whose observations never appear in any GDD total, and
    # nothing would ever say so.
    site = (site or "").strip().lower()
    if site not in SITE_KEYS:
        return {"error": "unknown_site", "site": site, "known_sites": sorted(SITE_KEYS)}
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", obs_date or ""):
        return {"error": "invalid_date", "obs_date": obs_date, "hint": "expected YYYY-MM-DD"}
    vals: dict[str, float | None] = {}
    for key, value in (("tmax_c", tmax_c), ("tmin_c", tmin_c), ("precip_mm", precip_mm)):
        if value is None:
            vals[key] = None
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            return {"error": "invalid_value", "field": key, "value": value}
        vals[key] = v
    if vals["tmax_c"] is not None and vals["tmin_c"] is not None and vals["tmin_c"] > vals["tmax_c"]:
        return {"error": "invalid_value", "field": "tmin_c",
                "hint": "tmin_c above tmax_c - swapped or mis-entered"}
    with transaction(conn):
        conn.execute(
            """INSERT INTO daily_obs (site, obs_date, tmax_c, tmin_c, precip_mm, source)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(site, obs_date) DO UPDATE SET
                 tmax_c=excluded.tmax_c, tmin_c=excluded.tmin_c,
                 precip_mm=excluded.precip_mm, source=excluded.source,
                 fetched_at_utc=excluded.fetched_at_utc""",
            (site, obs_date, vals["tmax_c"], vals["tmin_c"], vals["precip_mm"], source),
        )
    row = row_to_dict(
        conn.execute(
            "SELECT * FROM daily_obs WHERE site=? AND obs_date=?", (site, obs_date)
        ).fetchone()
    )
    return {"recorded": True, "obs": row}


def season_gdd(
    conn: sqlite3.Connection, site: str, season_year: int | None = None, base_c: float = 10.0
) -> dict[str, Any]:
    """Growing-degree-day total for a site's season from stored daily observations.

    `complete` is False when any calendar day between the first and last observation is
    missing — a gappy total reads EARLIER than reality, which is the direction that mistimes
    a spray. Pair with `compute_gdd` semantics; this is the stored-history version.
    """
    from .advisory import compute_gdd

    year = season_year or int(datetime.now(ZoneInfo(get_settings().timezone)).year)
    rows = rows_to_dicts(
        conn.execute(
            """SELECT obs_date, tmax_c, tmin_c FROM daily_obs
               WHERE site = ? AND obs_date LIKE ? ORDER BY obs_date""",
            (site, f"{year}-%"),
        ).fetchall()
    )
    if not rows:
        return {"site": site, "season_year": year, "gdd": None, "days_used": 0,
                "complete": False, "note": "no daily observations recorded"}
    days = [{"date": r["obs_date"], "tmax_c": r["tmax_c"], "tmin_c": r["tmin_c"]}
            for r in rows if r["tmax_c"] is not None and r["tmin_c"] is not None]
    result = compute_gdd(days, base_c)
    first, last = rows[0]["obs_date"], rows[-1]["obs_date"]
    d1 = datetime.strptime(first, "%Y-%m-%d").date()
    d2 = datetime.strptime(last, "%Y-%m-%d").date()
    calendar_days = (d2 - d1).days + 1
    result.update({
        "site": site, "season_year": year, "first_obs": first, "last_obs": last,
        "calendar_span_days": calendar_days,
        "days_missing": calendar_days - result["days_used"],
        "complete": result["days_used"] == calendar_days,
    })
    return result


def rei_active(conn: sqlite3.Connection) -> dict[str, Any]:
    """Blocks currently under a re-entry interval. Drives every NO-ENTRY message."""
    return {"active": rows_to_dicts(conn.execute("SELECT * FROM rei_active").fetchall())}


def query_logs(
    conn: sqlite3.Connection,
    *,
    table: str = "spray_log",
    date_from: str | None = None,
    date_to: str | None = None,
    block_code: str | None = None,
    worker_phone: str | None = None,
    product: str | None = None,
    task_type: str | None = None,
    include_superseded: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Filtered read over the compliance record.

    Reads the *_current views by default so a corrected record shows its corrected value.
    include_superseded=True is for the compliance export, which must show both sides.
    """
    if table not in ("spray_log", "task_log"):
        return {"error": "bad_table", "table": table}

    source = table if include_superseded else f"{table}_current"
    where: list[str] = []
    params: list[Any] = []

    if date_from:
        where.append("x.log_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("x.log_date <= ?")
        params.append(date_to)
    if block_code:
        where.append("b.code = ?")
        params.append(block_code)

    if table == "spray_log":
        if worker_phone:
            where.append("c.wa_phone = ?")
            params.append(worker_phone)
        if product:
            where.append("lower(x.product_name_raw) LIKE ?")
            params.append(f"%{product.lower()}%")
        sql = f"""SELECT x.*, b.code AS block_code, b.name AS block_name, b.site
                  FROM {source} x
                  LEFT JOIN blocks b ON b.id = x.block_id
                  LEFT JOIN contacts c ON c.id = x.applicator_contact_id"""
    else:
        if task_type:
            where.append("x.task_type = ?")
            params.append(task_type)
        if worker_phone:
            where.append(
                "EXISTS (SELECT 1 FROM task_workers tw JOIN contacts c2 ON c2.id = tw.contact_id"
                "        WHERE tw.task_log_id = x.id AND c2.wa_phone = ?)"
            )
            params.append(worker_phone)
        sql = f"""SELECT x.*, b.code AS block_code, b.name AS block_name, b.site
                  FROM {source} x
                  LEFT JOIN blocks b ON b.id = x.block_id"""

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY x.log_date DESC, x.id DESC LIMIT ?"
    params.append(limit)

    rows = rows_to_dicts(conn.execute(sql, params).fetchall())
    return {"table": table, "count": len(rows), "rows": rows}


def log_decision(
    conn: sqlite3.Connection,
    action: str,
    observed: str,
    reasoning: str,
    *,
    alternatives: str | None = None,
    entity: str | None = None,
    entity_id: int | None = None,
) -> dict[str, Any]:
    """Record an autonomous choice (docs/01 §3.1).

    This is the price of the latitude Hermes has: broad autonomy is made safe by being
    reconstructable, not by being restricted. "Decided not to send" belongs here as much as
    "sent" — a silent no-op is indistinguishable from a crash.
    """
    with transaction(conn):
        row_id = audit(
            conn,
            actor="hermes",
            action="agent.decision",
            entity=entity,
            entity_id=entity_id,
            detail_json=json.dumps(
                {
                    "decided": action,
                    "observed": observed,
                    "reasoning": reasoning,
                    "alternatives": alternatives,
                }
            ),
        )
    return {"logged": True, "audit_id": row_id}


def recent_decisions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = rows_to_dicts(
        conn.execute(
            """SELECT at_utc, detail_json FROM audit_log
               WHERE action = 'agent.decision' ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    )
    out = []
    for r in rows:
        try:
            out.append({"at_utc": r["at_utc"], **json.loads(r["detail_json"] or "{}")})
        except ValueError:
            out.append({"at_utc": r["at_utc"], "detail": r["detail_json"]})
    return out


def silent_workers(conn: sqlite3.Connection, days: int = 3) -> list[dict[str, Any]]:
    """Workers with no committed log in `days`, compared against their own recent baseline.

    A worker who reports twice a week is not silent after two days; one who reports daily is.
    Returning the baseline lets Hermes make that judgement rather than applying a flat rule.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    baseline_from = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    rows = rows_to_dicts(
        conn.execute(
            """SELECT c.id, c.wa_phone, c.short_name, c.lang,
                      MAX(last.when_) AS last_report,
                      (SELECT COUNT(*) FROM spray_log_current s2
                         WHERE s2.applicator_contact_id = c.id AND s2.log_date >= ?)
                    + (SELECT COUNT(*) FROM task_log_current t2
                         JOIN task_workers tw2 ON tw2.task_log_id = t2.id
                        WHERE tw2.contact_id = c.id AND t2.log_date >= ?) AS reports_30d
                 FROM contacts c
                 LEFT JOIN (
                      SELECT applicator_contact_id AS cid, MAX(log_date) AS when_
                        FROM spray_log_current GROUP BY applicator_contact_id
                      UNION ALL
                      SELECT tw.contact_id AS cid, MAX(t.log_date) AS when_
                        FROM task_log_current t
                        JOIN task_workers tw ON tw.task_log_id = t.id
                       GROUP BY tw.contact_id
                 ) last ON last.cid = c.id
                WHERE c.role = 'worker' AND c.active = 1
                GROUP BY c.id
               HAVING last_report IS NULL OR last_report < ?""",
            (baseline_from, baseline_from, cutoff),
        ).fetchall()
    )
    return rows


def get_situation(conn: sqlite3.Connection, scope: str = "full") -> dict[str, Any]:
    """The picture a scheduled run reasons over. **Load-bearing** — see docs/03 §1.2.

    Cron jobs start in a fresh session with no chat context, so a scheduled Hermes cannot notice
    anything it does not explicitly load. If a standing duty is absent from this payload, Hermes
    will never catch it — that, not prompt wording, is the real failure mode for docs/03 §1.1.

    So this deliberately returns more than any single job needs, and when Hermes finds itself
    wanting a fact that is not here, the right fix is to add it here.
    """
    settings = get_settings()
    today = _today_local()

    situation: dict[str, Any] = {
        "as_of_utc": utcnow(),
        "local_date": today,
        "timezone": settings.timezone,
        "scope": scope,
    }

    situation["rei_active"] = rows_to_dicts(
        conn.execute("SELECT * FROM rei_active ORDER BY rei_expires_at_utc").fetchall()
    )

    situation["today_sprays"] = rows_to_dicts(
        conn.execute(
            """SELECT s.*, b.code AS block_code FROM spray_log_current s
               LEFT JOIN blocks b ON b.id = s.block_id
               WHERE s.log_date = ?""",
            (today,),
        ).fetchall()
    )
    situation["today_tasks"] = rows_to_dicts(
        conn.execute(
            """SELECT t.*, b.code AS block_code FROM task_log_current t
               LEFT JOIN blocks b ON b.id = t.block_id
               WHERE t.log_date = ?""",
            (today,),
        ).fetchall()
    )

    situation["silent_workers"] = silent_workers(conn)

    situation["open_drafts"] = rows_to_dicts(
        conn.execute(
            """SELECT confirm_token, wa_phone, intent, state, missing_fields, created_at_utc
                 FROM drafts WHERE state IN ('collecting','ready','awaiting_confirm')""",
        ).fetchall()
    )

    situation["recent_decisions"] = recent_decisions(conn, limit=15)

    # Weather freshness per site — a degraded source Hermes does not know about is a brief
    # that quietly asserts a stale forecast.
    weather = []
    for site in settings.sites:
        row = row_to_dict(
            conn.execute(
                """SELECT site, source, fetched_at_utc, verdict_json FROM weather_cache
                   WHERE site = ? ORDER BY fetched_at_utc DESC LIMIT 1""",
                (site.key,),
            ).fetchone()
        )
        if row is None:
            weather.append({"site": site.key, "status": "no_data"})
            continue
        try:
            fetched = datetime.strptime(row["fetched_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            )
            age = (datetime.now(UTC) - fetched).total_seconds() / 3600.0
        except ValueError:
            age = None
        weather.append(
            {
                "site": row["site"],
                "source": row["source"],
                "fetched_at_utc": row["fetched_at_utc"],
                "age_hours": round(age, 2) if age is not None else None,
                "stale": (age is not None and age > settings.spray_window.max_data_age_hours),
                "verdict": json.loads(row["verdict_json"]) if row["verdict_json"] else None,
            }
        )
    situation["weather"] = weather

    situation["unverified_products_in_use"] = rows_to_dicts(
        conn.execute(
            """SELECT DISTINCT p.trade_name, p.id
                 FROM products p JOIN spray_log_current s ON s.product_id = p.id
                WHERE p.verified = 0""",
        ).fetchall()
    )

    # Tasks logged inside an active REI window — a safety incident, not a data problem.
    situation["rei_near_misses"] = rows_to_dicts(
        conn.execute(
            """SELECT t.id AS task_log_id, t.log_date, t.task_type, b.code AS block_code,
                      s.id AS spray_log_id, s.rei_expires_at_utc
                 FROM task_log_current t
                 JOIN blocks b ON b.id = t.block_id
                 JOIN spray_log_current s ON s.block_id = t.block_id
                WHERE s.rei_expires_at_utc IS NOT NULL
                  AND t.log_date >= s.log_date
                  AND t.created_at_utc < s.rei_expires_at_utc
                  AND t.created_at_utc > s.created_at_utc
                ORDER BY t.log_date DESC LIMIT 20""",
        ).fetchall()
    )

    situation["new_listings"] = rows_to_dicts(
        conn.execute(
            "SELECT * FROM listings WHERE notified = 0 ORDER BY first_seen_utc DESC LIMIT 25"
        ).fetchall()
    )

    return situation


# ──────────────────────────────────────────────────────────────────────────────
# Job bookkeeping — idempotence is ours, never the agent's memory
# ──────────────────────────────────────────────────────────────────────────────

def job_start(conn: sqlite3.Connection, job: str, local_date: str | None = None) -> dict[str, Any]:
    """Claim a job for (job, local_date). Returns already_ran=True if it succeeded today.

    Idempotence lives here rather than in the agent's memory, because a crashed-and-restarted
    process at 06:10 must not send a second morning brief, and "do you remember sending it?"
    is not a question a fresh session can answer.
    """
    day = local_date or _today_local()
    done = conn.execute(
        """SELECT id FROM audit_log
           WHERE action = 'job.finished' AND entity = ? AND detail_json LIKE ?""",
        (job, f'%"local_date": "{day}"%'),
    ).fetchone()
    if done:
        return {"job": job, "local_date": day, "already_ran": True, "proceed": False}

    with transaction(conn):
        audit(
            conn, actor="hermes", action="job.started", entity=job,
            detail_json=json.dumps({"local_date": day}),
        )
    return {"job": job, "local_date": day, "already_ran": False, "proceed": True}


def job_finish(
    conn: sqlite3.Connection,
    job: str,
    *,
    ok: bool = True,
    summary: str = "",
    local_date: str | None = None,
) -> dict[str, Any]:
    day = local_date or _today_local()
    with transaction(conn):
        audit(
            conn, actor="hermes",
            action="job.finished" if ok else "job.failed",
            entity=job,
            detail_json=json.dumps({"local_date": day, "summary": summary, "ok": ok}),
        )
    return {"job": job, "local_date": day, "ok": ok}


def skip_job(
    conn: sqlite3.Connection, job: str, reason: str, local_date: str | None = None
) -> dict[str, Any]:
    """A deliberate 'decided not to act' — a first-class, logged outcome.

    Without this, "nothing needed sending" and "the job crashed" look identical in the audit
    log, and the second one goes unnoticed for a week.
    """
    day = local_date or _today_local()
    with transaction(conn):
        audit(
            conn, actor="hermes", action="job.skipped", entity=job,
            detail_json=json.dumps({"local_date": day, "reason": reason}),
        )
    return {"job": job, "local_date": day, "skipped": True, "reason": reason}


def cache_weather(
    conn: sqlite3.Connection,
    site: str,
    source: str,
    payload: dict[str, Any],
    verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a forecast Hermes fetched itself, plus the verdict computed from it."""
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO weather_cache (site, source, fetched_at_utc, payload_json, verdict_json)
               VALUES (?,?,?,?,?)""",
            (site, source, utcnow(), json.dumps(payload),
             json.dumps(verdict) if verdict else None),
        )
    return {"cached": True, "id": int(cur.lastrowid), "site": site, "source": source}


def log_message(
    conn: sqlite3.Connection,
    *,
    direction: str,
    wa_phone: str,
    msg_type: str = "text",
    body: str | None = None,
    wa_message_id: str | None = None,
    chat_jid: str | None = None,
    is_group: bool = False,
) -> dict[str, Any]:
    """Persist a message verbatim. Deduped on wa_message_id so a replay processes once."""
    if wa_message_id:
        seen = conn.execute(
            "SELECT id FROM messages_raw WHERE wa_message_id = ?", (wa_message_id,)
        ).fetchone()
        if seen:
            return {"logged": False, "duplicate": True, "id": seen["id"]}

    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO messages_raw (direction, wa_phone, wa_message_id, chat_jid,
                                         is_group, msg_type, body, ts_utc)
               VALUES (?,?,?,?,?,?,?,?)""",
            (direction, wa_phone, wa_message_id, chat_jid,
             1 if is_group else 0, msg_type, body, utcnow()),
        )
    return {"logged": True, "duplicate": False, "id": int(cur.lastrowid)}
