"""The MCP server — how Hermes reaches the compliance kernel.

Tools reach the agent as `mcp_vineyard_<tool_name>`.

Design rules from docs/07 §0, which are worth restating because they are easy to erode:

  * **Broad and composable, not narrow.** `query_logs(filters)` beats five fixed report builders.
    Every narrow tool added here is a decision taken away from Hermes.
  * **Structured data and structured errors, never prose.** `{"error": "missing_field",
    "field": "rate_or_total"}` — Hermes turns that into the next question in the right language.
    Tools never write user-facing sentences; templates and Hermes do that.
  * **Nothing here fetches.** No weather, no IMAP, no XLSX, no report composition. Hermes does
    all of that itself with execute_code (docs/01 §D9).

Before adding a tool, apply the test: *would Hermes be unable to do this, or unsafe doing it,
without us?* If neither, it is a line in a skill, not a tool.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import advisory as A
from . import compliance as C
from . import maturity as M
from . import queries as Q
from . import registry as RG
from .config import get_settings
from .db import connect, is_initialized, rows_to_dicts
from .weather_math import compute_spray_window as _compute

mcp = FastMCP("vineyard")

_conn = None


def db():
    """One long-lived connection. stdio MCP is single-process and serial."""
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


# ──────────────────────────────────────────────────────────────────────────────
# Health / reference
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def ping() -> dict[str, Any]:
    """Check the kernel is alive and the database is initialized."""
    settings = get_settings()
    return {
        "ok": True,
        "db_path": str(settings.db_path),
        "initialized": is_initialized(db()),
        "timezone": settings.timezone,
    }


@mcp.tool()
def resolve_contact(identifier: str) -> dict[str, Any]:
    """Look up a contact by phone number OR WhatsApp lid (e.g. '143976027939069@lid').

    **Call this FIRST on every inbound message, before deciding anything about language.**
    WhatsApp identifies some senders by phone and others by a device-linked lid, and a lookup
    by the wrong one finds nothing — which is what let a real Punjabi speaker's voice notes get
    auto-detected as Portuguese and Polish with no correction, because Hermes never knew who was
    speaking. If `found` is false, ask a manager to enroll them rather than guessing.
    """
    return Q.resolve_contact(db(), identifier)


@mcp.tool()
def get_contacts(role: str | None = None, lang: str | None = None) -> dict[str, Any]:
    """List contacts. `lang` is what they READ; `reports_in` is what they report IN.

    Those differ for the spray applicator, who reads Gurmukhi but types spray reports in
    English (docs/01 §D11) — do not collapse the two.
    """
    sql = "SELECT * FROM contacts WHERE active = 1"
    params: list[Any] = []
    if role:
        sql += " AND role = ?"
        params.append(role)
    if lang:
        sql += " AND lang = ?"
        params.append(lang)
    return {"contacts": rows_to_dicts(db().execute(sql, params).fetchall())}


@mcp.tool()
def get_blocks() -> dict[str, Any]:
    """List vineyard blocks with site, acreage and variety."""
    return {
        "blocks": rows_to_dicts(
            db().execute("SELECT * FROM blocks WHERE active = 1 ORDER BY code").fetchall()
        )
    }


@mcp.tool()
def get_products() -> dict[str, Any]:
    """List products. `verified = 0` means NO re-entry interval may be stated for it."""
    return {
        "products": rows_to_dicts(
            db().execute("SELECT * FROM products ORDER BY trade_name").fetchall()
        )
    }


# ──────────────────────────────────────────────────────────────────────────────
# The compliance write path
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def draft_spray_log(
    wa_phone: str, extraction: dict[str, Any], raw_message: str = ""
) -> dict[str, Any]:
    """Merge an extraction into this worker's open spray draft; report what is still missing.

    Pass ONLY what the worker actually said. Never invent a value — omit it and it comes back
    in `missing_fields`, which is what stops a plausible guess becoming a legal record.

    Fields: product_name_raw, block_code, log_date, start_time, end_time (HH:MM),
    rate_value + rate_units OR total_amount + total_units, target_pest, method, notes,
    label_rei (only when the applicator read it off the label of an unverified product).
    """
    return C.draft_spray_log(db(), wa_phone, extraction, raw_message)


@mcp.tool()
def present_confirmation(confirm_token: str) -> dict[str, Any]:
    """Mark that you are about to SHOW the worker the confirmation card. Required before commit.

    The sequence is three separate acts and may not be collapsed: complete the draft, present
    the card, then commit with what the worker actually replied. Committing without this step
    is refused.
    """
    return C.present_confirmation(db(), confirm_token)


@mcp.tool()
def commit_spray_log(
    confirm_token: str, worker_reply: str, wa_phone: str
) -> dict[str, Any]:
    """Commit the confirmed spray record.

    `worker_reply` is the worker's **own affirmative words**, verbatim — «sí», «yes that's
    right», «ਹਾਂ». It is stored on the record as their signature. **Never invent it.** If they
    have not replied yet, wait; if they corrected something, re-draft instead.

    `wa_phone` is the RESOLVED sender of that reply (from `resolve_contact`). The confirmation
    must come from the same number the draft was opened with — a forwarded card confirmed by a
    different number is refused. That is obligation 1, not an inconvenience.

    Refuses tokens that are unknown, expired, already used, whose draft is incomplete, whose
    card was never presented, whose reply is empty, or whose confirmer is not the draft's own
    number. Each refusal is obligation 1 working — go back a step rather than retrying.
    """
    return C.commit_spray_log(db(), confirm_token, worker_reply, wa_phone)


@mcp.tool()
def draft_task_log(
    wa_phone: str, extraction: dict[str, Any], raw_message: str = ""
) -> dict[str, Any]:
    """Merge an extraction into this worker's open task draft.

    Fields: task_type (poda|deshoje|desbrote|riego|corte_pasto|alambre|cosecha|otro),
    block_code, log_date, hours_total (CREW-hours: 3 people x 4 h = 12), quantity,
    quantity_unit, start_time, end_time, notes, workers (list of contact ids).
    Optional worker_hours: [{"contact_id": 1, "hours": 3}, ...], explicitly reported
    for EVERY listed worker, with a sum matching hours_total. Never divide crew-hours
    to invent individual hours; omit worker_hours when unknown. Show every person's
    hours on the confirmation card using task_hours_confirm before asking for the
    reporter's reply. This confirms the reporter's account, not each worker's signature.
    """
    return C.draft_task_log(db(), wa_phone, extraction, raw_message)


@mcp.tool()
def commit_task_log(
    confirm_token: str, worker_reply: str, wa_phone: str
) -> dict[str, Any]:
    """Commit the confirmed task record. Same three-step gate as sprays.

    `worker_reply` is their own affirmative words, verbatim. Never invent it.
    `wa_phone` is the RESOLVED sender of the reply — same number as the draft, or refused.
    """
    return C.commit_task_log(db(), confirm_token, worker_reply, wa_phone)


@mcp.tool()
def draft_correction(
    table: str, log_id: int, changes: dict[str, Any], raw_message: str = ""
) -> dict[str, Any]:
    """Pre-fill a correction draft from an existing row. `table` is spray_log or task_log.

    The original is never modified — the correction commits as a new superseding row and both
    survive for the auditor. Confirm it in the worker's language like any other commit.
    """
    return C.draft_correction(db(), table, log_id, changes, raw_message)


@mcp.tool()
def find_recent_logs(wa_phone: str, limit: int = 5) -> dict[str, Any]:
    """This worker's recent spray and task records — for picking a correction target."""
    return C.find_recent_logs(db(), wa_phone, limit)


@mcp.tool()
def verify_product(
    trade_name: str,
    verified_by: str,
    pcp_number: str,
    rei_hours: int,
    phi_days: int | None = None,
    max_temp_c: float | None = None,
    rainfast_hours: float | None = None,
) -> dict[str, Any]:
    """Record that a HUMAN read the physical label and confirmed these values.

    `verified_by` must identify the person (e.g. 'manager:+1250...'). This is the only route
    out of obligation 4, and it is deliberately a human act — never call it on your own
    initiative, on the strength of a photo, or from a web page.

    **`pcp_number` and `rei_hours` are required and must come off the label**, not from the
    existing row. Someone saying "yes I read it" is not verification: ask them to read you the
    registration number and the re-entry interval. Placeholder values are rejected. If they
    cannot tell you those two things, they did not read the label.
    """
    return C.verify_product(
        db(), trade_name, verified_by=verified_by, pcp_number=pcp_number,
        rei_hours=rei_hours, phi_days=phi_days, max_temp_c=max_temp_c,
        rainfast_hours=rainfast_hours,
    )


@mcp.tool()
def expire_drafts() -> dict[str, Any]:
    """Expire drafts past their TTL. Returns them so you can send the polite note."""
    return {"expired": C.expire_drafts(db())}


# ──────────────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def update_block(block_code: str, changes: dict[str, Any], updated_by: str) -> dict[str, Any]:
    """Update registry facts for a property: acres, variety, row_count, irrigation setup,
    soil, coordinates, notes. **Owner or manager only** — a worker cannot alter the registry.

    `updated_by` is the RESOLVED phone/lid of the person who asked. Every change is validated
    (physically plausible values only — a bad acre count poisons water/GDD/PHI math) and
    audited. Read the block back after updating so they can confirm what landed.
    """
    return RG.update_block(db(), block_code, changes, updated_by)


@mcp.tool()
def record_daily_obs(
    site: str, obs_date: str, tmax_c: float | None = None, tmin_c: float | None = None,
    precip_mm: float | None = None, source: str = "wunderground",
) -> dict[str, Any]:
    """Store one measured day of weather for a site (upsert by site+date).

    This builds the history that `gdd_season` sums. Feed it once a day from the Wunderground
    PWS hourly_7day actuals (aggregate per LOCAL date: daily max temp, min temp, precip sum)
    or ECCC daily values. Celsius. Refetching a date replaces it — instrument data, not law.
    """
    return Q.record_daily_obs(db(), site, obs_date, tmax_c, tmin_c, precip_mm, source)


@mcp.tool()
def gdd_season(
    site: str, season_year: int | None = None, base_c: float = 10.0
) -> dict[str, Any]:
    """Growing-degree-day total for a site's season from stored daily observations.

    Check `complete` before quoting the total: a gappy record reads EARLIER than reality,
    which is the direction that mistimes a spray. Missing days can be backfilled by recording
    the missing obs dates.
    """
    return Q.season_gdd(db(), site, season_year, base_c)


@mcp.tool()
def get_situation(scope: str = "full") -> dict[str, Any]:
    """The picture to reason over. **Call this first in every scheduled job.**

    A cron run starts with no chat context, so anything not in this payload is something you
    structurally cannot notice. Returns: active REIs, today's sprays and tasks, silent workers,
    open drafts, recent decisions, per-site weather freshness, unverified products in use,
    REI near-misses, and new listings.

    If you need a fact that is not here, say so — the payload should grow.
    """
    return Q.get_situation(db(), scope)


@mcp.tool()
def rei_active() -> dict[str, Any]:
    """Blocks currently under a re-entry interval. Nobody may enter these."""
    return Q.rei_active(db())


@mcp.tool()
def query_logs(
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
    """Filtered read over the record. Compose it for reports, anomalies, and ad-hoc questions.

    Reads the corrected (current) view by default. Set include_superseded=True for the
    compliance export, which must show both sides of every correction.
    """
    return Q.query_logs(
        db(), table=table, date_from=date_from, date_to=date_to, block_code=block_code,
        worker_phone=worker_phone, product=product, task_type=task_type,
        include_superseded=include_superseded, limit=limit,
    )


@mcp.tool()
def compute_spray_window(
    site: str,
    hourly: list[dict[str, Any]], product: dict[str, Any] | None = None,
    source: str | None = None, age_hours: float | None = None,
) -> dict[str, Any]:
    """Compute the spray verdict from hours YOU fetched, and record it. No network.

    Each hour: {time (ISO), wind_kmh, gust_kmh, temp_c, precip_prob_pct}. Always pass `source`
    and `age_hours` — the verdict fails safe to NO on stale or wind-less data. `site` is the
    block's site (penticton / naramata / oliver); call this **once per site**.

    **You may not soften a NO into a YES**, reword it into a maybe, or add context implying
    otherwise. Name the source and any caveat in your message.

    The forecast and the verdict are written to `weather_cache` for you — `recorded` in the
    result says whether that succeeded. You do not need to call `cache_weather` afterwards.
    """
    verdict = _compute(hourly, None, product, source=source, age_hours=age_hours)

    # Persisted here rather than left to a follow-up call. A spray verdict is a decision with
    # legal weight, and the caching step is the one that goes missing: verified 2026-08-23,
    # Hermes fetched and judged correctly, then delivered a right answer that left no record of
    # itself. An IPM auditor asking "what were the conditions?" six months on needs this row.
    # Instructions to cache existed in both the skill and the standing brief and did not fire —
    # the same lesson as §D14. Enforcement belongs in the runtime.
    try:
        cached = Q.cache_weather(
            db(), site, source or "unknown", {"hourly": hourly}, verdict,
        )
        verdict["recorded"] = True
        verdict["weather_cache_id"] = cached["id"]
    except Exception as exc:  # noqa: BLE001 — a storage failure must not swallow the verdict
        # Surfaced, never silent: an unrecorded verdict is still safe to act on today, but it
        # is not defensible later, and the operator needs to know which of the two they have.
        verdict["recorded"] = False
        verdict["record_error"] = str(exc)
    verdict["site"] = site
    return verdict


# ──────────────────────────────────────────────────────────────────────────────
# Advisory — computed facts that recommendations must stand on
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def mildew_risk(hourly: list[dict[str, Any]]) -> dict[str, Any]:
    """Powdery-mildew pressure score (0–100 + LOW/MODERATE/HIGH band) for one site's forecast.

    Pass the SAME normalized hourly payload you feed `compute_spray_window`, per site — this is
    a pure function over hours, not a verdict on spraying. Warm hours build pressure; warm+wet
    hours are where infection happens. It is a proxy built from temperature and rain signals
    because we have no leaf-wetness sensors; say so when you quote the band.

    Use it to set INTERVAL expectations in recommendations ("HIGH — hold the 7-day cadence"),
    never as a reason to name a product or soften a NO verdict.
    """
    return A.mildew_pressure(hourly)


@mcp.tool()
def spray_status(block_code: str | None = None) -> dict[str, Any]:
    """Per block and pest: last application, days since, whether cover has lapsed, and
    consecutive same-resistance-group runs.

    This is the backbone of a spray recommendation. Cite these numbers when you advise —
    "16 days since, label interval is 10" is checkable; "it's probably due" is not.
    """
    return A.spray_status(db(), block_code)


@mcp.tool()
def spray_options(block_code: str, target_pest: str) -> dict[str, Any]:
    """Products IN THE SHED registered for this pest, with what disqualifies each.

    **You may only ever propose products this returns.** It is the shed. Anything outside it is
    a product nobody owns at a rate nobody verified. Unverified products come back flagged
    unusable — show them so a manager sees what verifying would unlock, but never state their
    REI. Present options with trade-offs; the choice is the manager's.
    """
    return A.spray_options(db(), block_code, target_pest)


@mcp.tool()
def task_cadence(task_type: str | None = None) -> dict[str, Any]:
    """Days since each block last had each task, against the median across your own blocks.

    The comparison is to THIS vineyard's practice, not a textbook. "B7 is 34 days since leaf
    removal, median across your blocks is 19" is actionable; a generic interval is not.
    """
    return A.task_cadence(db(), task_type)


@mcp.tool()
def compute_gdd(daily: list[dict[str, Any]], base_c: float = 10.0) -> dict[str, Any]:
    """Growing degree days from daily min/max you fetched. Base 10 °C for grapes.

    Each day: {tmax_c, tmin_c}. Days missing a temperature are skipped AND COUNTED — check
    `complete` before comparing a total to another season, because a gappy record reads earlier
    than reality, which is the direction that mistimes a spray.
    """
    return A.compute_gdd(daily, base_c)


@mcp.tool()
def log_recommendation(
    subject: str, options: str, evidence: str, recommended: str | None = None
) -> dict[str, Any]:
    """Record advice you gave: what you laid out, the evidence, and what you leaned toward.

    Call this **every time you recommend something**. It is what lets the owner read back at
    season end and judge whether your advice was any good — and the advice you got wrong is the
    most useful thing in that log.
    """
    return A.log_recommendation(db(), subject, options, evidence, recommended)



# ──────────────────────────────────────────────────────────────────────────────
# Fruit maturity and irrigation
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def record_sample(
    block_code: str, sampled_on: str | None = None, brix: float | None = None,
    ta_g_l: float | None = None, ph: float | None = None,
    berry_weight_g: float | None = None, sample_size: int | None = None,
    method: str | None = None, notes: str | None = None,
    raw_message: str = "", wa_phone: str | None = None,
) -> dict[str, Any]:
    """Record a fruit maturity sample. Needs at least one of brix / ta_g_l / ph.

    Append-only, like the compliance tables — these drive harvest calls and contract
    conformance. Implausible readings are refused rather than stored, because one bad number
    poisons the ripening rate and every projection made from it.

    Always capture `sample_size` when you know it: Brix varies a lot berry to berry, and a
    30-berry sample is a much softer number than a 200-berry one.
    """
    return M.record_sample(db(), block_code, sampled_on, brix, ta_g_l, ph, berry_weight_g,
                           sample_size, method, notes, raw_message, wa_phone)


@mcp.tool()
def maturity_status(
    block_code: str | None = None, season: int | None = None, winery: str | None = None,
) -> dict[str, Any]:
    """Fruit vs winery target: current Brix/TA/pH, ripening rate, projected days to target.

    The number worth quoting is **degrees Brix per day**, not today's Brix — it turns "we're at
    21.4" into "about nine days out". Check `sample_stale` before relying on any of it, and say
    when a projection rests on a single sample.

    Also flags fruit above the contract window (which cannot be undone), projections falling
    outside the contract harvest dates, and contracted blocks nobody has sampled.
    """
    return M.maturity_status(db(), block_code, season, winery=winery)


@mcp.tool()
def set_fruit_target(
    block_code: str, winery: str,
    target_brix_min: float | None = None, target_brix_max: float | None = None,
    target_ta_min: float | None = None, target_ta_max: float | None = None,
    target_ph_min: float | None = None, target_ph_max: float | None = None,
    harvest_window_from: str | None = None, harvest_window_to: str | None = None,
    contract_notes: str | None = None, season_year: int | None = None,
    set_by: str = "",
) -> dict[str, Any]:
    """Record or update what a winery wants from a block. **A manager can set this by message.**

    Pass `set_by` as who told you (e.g. 'manager:+1250...'), because every change is audited and
    "who moved the Brix target and when" gets asked when a load is disputed.

    Partial updates are fine — supply only what changed and the rest is left alone.

    **Read the target back to them before you consider it set.** A figure typed as 2.3 instead of
    23 does not error, it silently reports every block as ripe, and nobody notices until harvest.
    Out-of-range values and inverted min/max are refused; read the `problems` list back rather
    than trying to guess what they meant.
    """
    return M.set_fruit_target(
        db(), block_code, winery, target_brix_min, target_brix_max, target_ta_min,
        target_ta_max, target_ph_min, target_ph_max, harvest_window_from,
        harvest_window_to, contract_notes, season_year, set_by,
    )


@mcp.tool()
def get_fruit_targets(block_code: str | None = None, season: int | None = None) -> dict[str, Any]:
    """Contract targets on file, with when each was last changed and by whom."""
    return M.get_fruit_targets(db(), block_code, season)


@mcp.tool()
def correct_sample(
    sample_id: int, raw_message: str = "", set_by: str = "",
    brix: float | None = None, ta_g_l: float | None = None, ph: float | None = None,
    berry_weight_g: float | None = None, sample_size: int | None = None,
    sampled_on: str | None = None, method: str | None = None, notes: str | None = None,
) -> dict[str, Any]:
    """Supersede a fruit sample with a corrected one. The original is never modified.

    Use this when someone mistyped a reading. `fruit_samples` is append-only for the same reason
    the compliance tables are: a ripening curve that can be quietly rewritten is one nobody can
    trust if a delivery is disputed. Both rows survive, linked.

    Find the id with `maturity_status` first if you do not have it.
    """
    changes = {k: v for k, v in {
        "brix": brix, "ta_g_l": ta_g_l, "ph": ph, "berry_weight_g": berry_weight_g,
        "sample_size": sample_size, "sampled_on": sampled_on, "method": method,
        "notes": notes,
    }.items() if v is not None}
    return M.correct_sample(db(), sample_id, raw_message, set_by, **changes)


@mcp.tool()
def compute_et0(daily: list[dict[str, Any]], latitude: float) -> dict[str, Any]:
    """Reference evapotranspiration (mm/day), Hargreaves-Samani, from daily min/max you fetched.

    Each day: {date, tmax_c, tmin_c}. Use the site latitude from settings.

    This is a **temperature-only approximation** — FAO-56's recommendation when radiation and
    humidity are unavailable, which is our case with ECCC. It over-predicts in humid air and
    under-predicts in wind. Good enough to say "this block is running a deficit"; not good
    enough to prescribe a dose, and nothing here does.
    """
    return M.compute_et0(daily, latitude)


@mcp.tool()
def water_balance(
    block_code: str, rain_mm: float, et0_mm: float,
    kc: float | None = None, days: int = 14,
) -> dict[str, Any]:
    """Rain in, estimated crop use out, days since this block was last irrigated.

    Crop use = ET0 x Kc, with Kc from settings (a farming decision, not a fact).

    **Returns a deficit in millimetres, never a volume.** Litres depend on soil, rooting depth
    and emitter spacing; where a block records emitter rate and vine density you also get a
    run-time estimate, and where it does not you get an explicit note saying why not.
    """
    return M.water_balance(db(), block_code, rain_mm, et0_mm, kc, days)


@mcp.tool()
def irrigation_vs_ripening(block_code: str, rain_mm: float, et0_mm: float) -> dict[str, Any]:
    """**The cross-check.** Reconcile a water deficit against the contract Brix target.

    Post-veraison irrigation dilutes sugar and pushes ripening back. A block behind its Brix
    target with the harvest window closing is one where watering works against the contract; a
    block already at spec is not. Neither number tells you that alone.

    States the tension; does not resolve it. Weighing vine health against the delivery spec is
    a manager's call and genuinely not obvious.
    """
    conn = db()
    balance = M.water_balance(conn, block_code, rain_mm, et0_mm)
    mat = M.maturity_status(conn, block_code)
    return M.irrigation_vs_ripening(conn, block_code, balance, mat)


# ──────────────────────────────────────────────────────────────────────────────
# Decisions, jobs, and durable side-writes
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def log_decision(
    action: str, observed: str, reasoning: str, alternatives: str | None = None
) -> dict[str, Any]:
    """Record a choice you made on your own initiative. Includes choosing NOT to act.

    This is the price of your latitude: autonomy is bounded by transparency, not permission.
    "Skipped the midday recheck — verdict unchanged" belongs here as much as anything you sent.
    """
    return Q.log_decision(db(), action, observed, reasoning, alternatives=alternatives)


@mcp.tool()
def job_start(job: str, local_date: str | None = None) -> dict[str, Any]:
    """Claim a scheduled job. If proceed=False it already succeeded today — stop, don't resend."""
    return Q.job_start(db(), job, local_date)


@mcp.tool()
def job_finish(
    job: str, ok: bool = True, summary: str = "", local_date: str | None = None
) -> dict[str, Any]:
    """Close out a job. ok=False marks it failed and leaves it retryable."""
    return Q.job_finish(db(), job, ok=ok, summary=summary, local_date=local_date)


@mcp.tool()
def skip_job(job: str, reason: str, local_date: str | None = None) -> dict[str, Any]:
    """Record that you deliberately did nothing, and why.

    Use this rather than returning silently — an unlogged no-op is indistinguishable from a
    crash, and the crash then goes unnoticed for a week.
    """
    return Q.skip_job(db(), job, reason, local_date)


@mcp.tool()
def cache_weather(
    site: str, source: str, payload: dict[str, Any], verdict: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Store a forecast you fetched, with the verdict computed from it.

    The spray-log flow reads this to pre-fill weather-at-application, so a missing entry
    silently degrades compliance records hours later.
    """
    return Q.cache_weather(db(), site, source, payload, verdict)


@mcp.tool()
def log_message(
    direction: str, wa_phone: str, msg_type: str = "text", body: str | None = None,
    wa_message_id: str | None = None, chat_jid: str | None = None, is_group: bool = False,
) -> dict[str, Any]:
    """Persist a message verbatim. Deduped on wa_message_id, so a replay processes once."""
    return Q.log_message(
        db(), direction=direction, wa_phone=wa_phone, msg_type=msg_type, body=body,
        wa_message_id=wa_message_id, chat_jid=chat_jid, is_group=is_group,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
