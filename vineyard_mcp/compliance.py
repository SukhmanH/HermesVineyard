"""The compliance write path — drafts, the confirmation gate, commits, and corrections.

This module is where docs/01 §3's four obligations are enforced *in Python*, so that a bad model
day, a degraded provider, or a prompt-injected message cannot break them:

  1. A record commits only with the worker's confirmation (the confirm_token gate).
  2. BC-required fields are validated server-side.
  3. The worker's own words are kept verbatim in raw_message.
  4. An unverified REI is never asserted.

Everything here returns **structured data and structured errors**, never prose:
    {"error": "missing_field", "field": "rate_or_total"}
Hermes turns that into the next question in Spanish, Gurmukhi or English. Tools never write
user-facing sentences — templates and Hermes do that.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import secrets
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import audit, row_to_dict, rows_to_dicts, transaction, utcnow

# ── Required fields, straight from BC's IPM Regulation record requirements (docs/02 §4).
# Changing this list changes what the law sees, so it lives in one place and is asserted in tests.
SPRAY_REQUIRED = ["product_name_raw", "block_code", "start_time"]
TASK_REQUIRED = ["task_type", "log_date"]

_SPANISH_NUMBERS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}
_ENGLISH_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def err(code: str, **extra: Any) -> dict[str, Any]:
    return {"error": code, **extra}


def _token() -> str:
    return secrets.token_urlsafe(18)


# ──────────────────────────────────────────────────────────────────────────────
# Resolution helpers
# ──────────────────────────────────────────────────────────────────────────────

def resolve_block(conn: sqlite3.Connection, text: Any) -> dict[str, Any] | None:
    """Map what a worker said to a block row. 'el 3', 'bloque tres', 'B3' -> B3.

    Returns None rather than guessing when nothing matches — an invented block is a compliance
    record attached to the wrong piece of land.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    blocks = rows_to_dicts(
        conn.execute("SELECT * FROM blocks WHERE active = 1").fetchall()
    )
    if not blocks:
        return None

    norm = raw.upper().replace("-", "").replace("_", "").replace(" ", "")
    for b in blocks:
        if b["code"].upper().replace("-", "").replace(" ", "") == norm:
            return b

    # Number-word substitution is applied ONLY when the phrase is a bare block reference —
    # a leading keyword plus a single number and nothing else. Running it over free prose
    # matches the "one" in "the far one by the road" and silently resolves to B1, which is
    # exactly the invented value this function exists to refuse.
    lowered = raw.lower().strip(" .,!?¡¿")
    remainder = re.sub(
        r"^(el|la|los|las|the|en|in|de|del)?\s*(bloque|bloques|block|blk)?\s*",
        "",
        lowered,
    ).strip()

    number_words = {**_SPANISH_NUMBERS, **_ENGLISH_NUMBERS}
    want: str | None = None
    if re.fullmatch(r"\d+", remainder):
        want = remainder.lstrip("0") or "0"
    elif remainder in number_words:
        want = str(number_words[remainder])

    if want is not None:
        matches = [
            b
            for b in blocks
            if (d := re.findall(r"\d+", b["code"])) and (d[0].lstrip("0") or "0") == want
        ]
        # Two blocks could share a number across sites (B3 and N3). Ambiguity is a question,
        # not a coin flip.
        if len(matches) == 1:
            return matches[0]
        return None

    names = {b["name"].lower(): b for b in blocks}
    close = difflib.get_close_matches(lowered, list(names), n=1, cutoff=0.85)
    return names[close[0]] if close else None


def resolve_product(conn: sqlite3.Connection, text: Any) -> dict[str, Any] | None:
    """Match a spoken/typed product name to the registry.

    Tolerates misspellings ('asufre'), but refuses to pick between two plausible candidates —
    ambiguity comes back as None so Hermes asks instead of choosing.
    """
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None

    products = rows_to_dicts(conn.execute("SELECT * FROM products").fetchall())
    if not products:
        return None

    by_name = {p["trade_name"].lower(): p for p in products}
    if raw in by_name:
        return by_name[raw]

    contains = [p for name, p in by_name.items() if raw in name or name in raw]
    if len(contains) == 1:
        return contains[0]

    close = difflib.get_close_matches(raw, list(by_name), n=2, cutoff=0.72)
    if len(close) == 1:
        return by_name[close[0]]
    return None


def _contact(conn: sqlite3.Connection, wa_phone: str) -> dict[str, Any] | None:
    """Resolve a sender by phone number OR WhatsApp lid.

    WhatsApp identifies some senders by phone and others by a device-linked `...@lid`, and which
    one arrives is not the sender's choice. Matching on `wa_phone` alone made every lid-identified
    sender an `unknown_contact` here, so the intake flow refused reports from people who are
    plainly enrolled — while `resolve_contact` and `registry.py` accepted them. Same person, two
    answers, depending on which door they knocked on.
    """
    return row_to_dict(
        conn.execute(
            "SELECT * FROM contacts WHERE wa_phone = ? OR wa_lid = ?",
            (wa_phone, wa_phone),
        ).fetchone()
    )


def _canonical_phone(conn: sqlite3.Connection, identifier: str) -> str:
    """The one identifier a draft is keyed by, whichever door the sender came through.

    Drafts are bound to the identity that opened them (that binding is what stops a forwarded
    confirmation card being signed by someone else). If a worker opens a draft from their phone
    number and the confirmation arrives carrying their lid, a literal string comparison sees two
    different people and refuses a legitimate confirmation. So every identity that enters the
    draft system is first collapsed to the contact's canonical `wa_phone`; unknown identifiers
    pass through unchanged so the caller's own `unknown_contact` check still fires.
    """
    contact = _contact(conn, identifier)
    return contact["wa_phone"] if contact else identifier


def _local_to_utc(log_date: str, hhmm: str, tzname: str) -> datetime | None:
    try:
        naive = datetime.strptime(f"{log_date} {hhmm}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=ZoneInfo(tzname)).astimezone(UTC)


# ──────────────────────────────────────────────────────────────────────────────
# Drafts
# ──────────────────────────────────────────────────────────────────────────────

def _open_draft(
    conn: sqlite3.Connection, wa_phone: str, intent: str
) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """SELECT * FROM drafts
               WHERE wa_phone = ? AND intent = ? AND state IN ('collecting','ready','awaiting_confirm')
               ORDER BY updated_at_utc DESC LIMIT 1""",
            (wa_phone, intent),
        ).fetchone()
    )


def expire_drafts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Expire drafts past their TTL. Returns them so a skill can send the polite note.

    A worker who answered three questions deserves to know the fourth never arrived.
    """
    ttl = get_settings().draft_ttl_hours
    cutoff = (datetime.now(UTC) - timedelta(hours=ttl)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    stale = rows_to_dicts(
        conn.execute(
            """SELECT * FROM drafts
               WHERE state IN ('collecting','ready','awaiting_confirm') AND created_at_utc < ?""",
            (cutoff,),
        ).fetchall()
    )
    if stale:
        with transaction(conn):
            conn.execute(
                """UPDATE drafts SET state='expired', updated_at_utc=?
                   WHERE state IN ('collecting','ready','awaiting_confirm') AND created_at_utc < ?""",
                (utcnow(), cutoff),
            )
    return stale


def _canonical_date(value: Any) -> bool:
    """True only for a real calendar date in strict YYYY-MM-DD form.

    '2026-02-30' parses in some validators and '2026-2-3' parses in most; neither is what a
    spray record is allowed to say. BC's record must survive an audit three years out, so
    anything non-canonical is treated as missing, not as a date.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _canonical_time(value: Any) -> bool:
    """True only for strict zero-padded HH:MM on a real 24-hour clock."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", str(value)):
        return False
    hh, mm = (int(part) for part in value.split(":"))
    return 0 <= hh < 24 and 0 <= mm < 60


def _finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0


def _validate_memberships(conn: sqlite3.Connection, draft: dict[str, Any]) -> list[dict[str, Any]]:
    workers = draft.get("workers")
    if not isinstance(workers, list) or not workers or any(type(w) is not int for w in workers):
        return [{"field": "workers", "why": "require_contact_ids"}]
    if len(set(workers)) != len(workers) or any(
        conn.execute("SELECT 1 FROM contacts WHERE id=?", (w,)).fetchone() is None for w in workers
    ):
        return [{"field": "workers", "why": "unknown_or_duplicate_contact"}]
    return []


def _validate_worker_hours(draft: dict[str, Any]) -> list[dict[str, Any]]:
    if "worker_hours" not in draft or draft["worker_hours"] is None:
        return []  # legacy/crew-only reports remain honest: no inferred allocation
    entries = draft["worker_hours"]
    invalid = [{"field": "worker_hours", "why": "require_each_worker_finite_hours_and_matching_total"}]
    if not isinstance(entries, list) or not entries:
        return invalid
    ids, values = [], []
    for entry in entries:
        if not isinstance(entry, dict) or type(entry.get("contact_id")) is not int:
            return invalid
        value = entry.get("hours")
        if not _positive(value) or float(value) > 24:
            return invalid
        ids.append(entry["contact_id"])
        values.append(float(value))
    workers = draft.get("workers")
    if (not isinstance(workers, list) or any(type(w) is not int for w in workers)
            or len(set(ids)) != len(ids) or set(ids) != set(workers)):
        return invalid
    if not _positive(draft.get("hours_total")) or not math.isclose(
        sum(values), float(draft["hours_total"]), rel_tol=1e-9, abs_tol=1e-6
    ):
        return invalid
    return []


def _validate_task(draft: dict[str, Any]) -> list[dict[str, Any]]:
    missing = _validate_worker_hours(draft) + [{"field": f, "why": "required"} for f in TASK_REQUIRED
               if not isinstance(draft.get(f), str) or not draft[f].strip()]
    if not _canonical_date(draft.get("log_date")):
        missing.append({"field": "log_date", "why": "bad_format_expect_YYYY-MM-DD"})
    if not _positive(draft.get("hours_total")):
        why = "required" if draft.get("hours_total") is None else "must_be_finite_positive"
        missing.append({"field": "hours_total", "why": why})
    if draft.get("quantity") is not None and not _positive(draft["quantity"]):
        missing.append({"field": "quantity", "why": "must_be_finite_positive"})
    return missing


def _validate_spray(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Server-side validation (obligation 2). Returns structured missing/invalid fields."""
    missing: list[dict[str, Any]] = []

    for field in SPRAY_REQUIRED:
        if not isinstance(draft.get(field), str) or not draft[field].strip():
            missing.append({"field": field, "why": "required"})

    # block_code present but unresolved is a different question from block_code absent:
    # the worker said something, we just could not map it to a block. Ask which one.
    if draft.get("block_id") is None and draft.get("block_code"):
        missing.append({"field": "block_code", "why": "unresolved"})

    has_rate = draft.get("rate_value") is not None
    has_total = draft.get("total_amount") is not None
    if not (has_rate or has_total):
        missing.append({"field": "rate_or_total", "why": "required"})

    if has_rate and not draft.get("rate_units"):
        missing.append({"field": "rate_units", "why": "required_with_rate"})
    if has_total and not draft.get("total_units"):
        missing.append({"field": "total_units", "why": "required_with_total"})

    # Obligation 4: an unverified product yields NO re-entry interval. We ask the applicator to
    # read the label instead of quietly inventing one.
    if draft.get("_product_unverified") or draft.get("rei_hours") is None:
        missing.append({"field": "label_rei", "why": "product_unverified"})

    # BC requires prevailing weather on a pesticide application record (docs/02 §4). If the
    # cache had nothing, ask the worker - that is what weather_source='worker-reported' is for.
    if draft.get("wind_kmh") is None:
        missing.append({"field": "wind_kmh", "why": "required_bc_record"})
    if draft.get("temp_c") is None:
        missing.append({"field": "temp_c", "why": "required_bc_record"})

    # A rate well above the label rate is an over-application: a label violation and a residue
    # risk. Do not block it outright - rates legitimately vary - but refuse to commit it
    # SILENTLY. Hermes must ask, and the answer is recorded on the row.
    _flag = draft.get("_rate_flag")
    if _flag and not draft.get("rate_confirmed"):
        missing.append({"field": "rate_confirmed", "why": _flag})

    for numeric in ("rate_value", "total_amount", "acres_treated"):
        val = draft.get(numeric)
        if val is not None and not _positive(val):
            if isinstance(val, str):
                why = "not_a_number"
            elif isinstance(val, (int, float)) and val < 0:
                why = "must_be_positive"
            else:
                why = "must_be_finite_positive"
            missing.append({"field": numeric, "why": why})

    for numeric in ("wind_kmh", "temp_c", "rh_pct", "phi_days"):
        val = draft.get(numeric)
        if val is not None and (not _finite(val) or
                                (numeric != "temp_c" and float(val) < 0) or
                                (numeric == "rh_pct" and float(val) > 100)):
            missing.append({"field": numeric, "why": "invalid_finite_number"})

    # A re-entry interval is hours after the spray ends: negative would schedule re-entry
    # before the spray happened, non-finite would poison every downstream countdown.
    # Zero is real (some low-risk uses). Do not silently truncate fractions either.
    for rei_field in ("label_rei", "rei_hours"):
        val = draft.get(rei_field)
        if val is None:
            continue
        try:
            rei_f = float(val)
        except (TypeError, ValueError):
            missing.append({"field": rei_field, "why": "not_a_number"})
            continue
        if isinstance(val, bool) or not math.isfinite(rei_f) or rei_f < 0:
            missing.append({"field": rei_field, "why": "must_be_zero_or_positive_hours"})

    # A non-canonical date/time is a silent data-corruption risk: '2026-2-3' or '24:00'
    # would parse somewhere downstream and write a record an auditor cannot read back.
    # Treat them exactly like a missing field: ask the worker, commit nothing.
    val = draft.get("log_date")
    if not _canonical_date(val):
        missing.append({"field": "log_date", "why": "bad_format_expect_YYYY-MM-DD"})
    for tf in ("start_time", "end_time"):
        val = draft.get(tf)
        if val is not None and not _canonical_time(val):
            missing.append({"field": tf, "why": "bad_format_expect_HH:MM"})

    return missing


# Derived identities and provenance cannot be supplied through extracted fields.
_IMMUTABLE = {"id", "created_at_utc", "created_by", "corrects_log_id", "raw_message",
              "confirmed_by_reply", "rei_expires_at_utc", "applicator_contact_id",
              "applicator_name", "wa_phone", "rate_flag"}


def _merge_fields(draft: dict[str, Any], extraction: dict[str, Any], *, correction: bool) -> set[str]:
    changed = set()
    for key, value in (extraction or {}).items():
        if key.startswith("_") or key in _IMMUTABLE or (correction and key == "source_msg_id"):
            continue
        if (correction or key == "worker_hours" or value not in (None, "", [])) and draft.get(key) != value:
            draft[key] = value
            changed.add(key)
    if changed & {"product", "product_name_raw", "product_id"}:
        changed.update(k for k in ("pcp_number", "rei_hours", "phi_days", "label_rei")
                       if k in extraction and extraction[k] not in (None, "", []))
    if changed & {"product", "product_name_raw", "product_id", "rate_value", "rate_units"} and "rate_confirmed" in extraction:
        changed.add("rate_confirmed")
    if "block" in changed and "block_code" not in changed:
        draft["block_code"] = draft["block"]
    if "product" in changed and "product_name_raw" not in changed:
        draft["product_name_raw"] = draft["product"]
    return changed


def _prepare_spray(conn: sqlite3.Connection, draft: dict[str, Any], changed: set[str],
                   *, correction: bool) -> None:
    """Resolve explicit identity edits; do not refresh historical label snapshots."""
    identity_changed = bool(changed & {"product", "product_name_raw", "product_id"})
    if "product_id" in changed and not changed & {"product", "product_name_raw"}:
        product = row_to_dict(conn.execute("SELECT * FROM products WHERE id=?",
                                          (draft.get("product_id"),)).fetchone())
        draft["product_name_raw"] = product["trade_name"] if product else ""
    else:
        product = resolve_product(conn, draft.get("product_name_raw") or draft.get("product"))
    if identity_changed:
        for key in ("pcp_number", "rei_hours", "phi_days", "label_rei"):
            if key not in changed:
                draft.pop(key, None)
        draft.pop("_label_resolved", None)
    # Corrections start with historical snapshots, including unknown intervals. The registry
    # only supplies a new snapshot when product identity is explicitly changed.
    if (not correction or identity_changed) and not draft.get("_label_resolved"):
        draft["product_id"] = product["id"] if product else None
        draft["_product_verified"] = bool(product and product["verified"])
        if product and product["verified"]:
            for key in ("pcp_number", "rei_hours", "phi_days"):
                if key not in changed:
                    draft[key] = product[key]
            draft["_label_resolved"] = True
    if "label_rei" in changed:
        draft["rei_hours"] = draft["label_rei"]
        draft["_label_resolved"] = True
    draft["_product_unverified"] = not draft.get("_label_resolved") or draft.get("rei_hours") is None
    if draft["_product_unverified"]:
        draft.pop("rei_hours", None)
    if not correction or changed & {"product", "product_name_raw", "product_id", "rate_value", "rate_units"}:
        if changed & {"product", "product_name_raw", "product_id", "rate_value", "rate_units"} and "rate_confirmed" not in changed:
            draft.pop("rate_confirmed", None)
        _check_rate_against_label(draft, product)
    draft["rate_flag"] = draft.get("_rate_flag")


def _prepare_block(conn: sqlite3.Connection, draft: dict[str, Any], changed: set[str]) -> None:
    if "block_id" in changed and not changed & {"block", "block_code"}:
        block = row_to_dict(conn.execute("SELECT * FROM blocks WHERE id=? AND active=1",
                                        (draft.get("block_id"),)).fetchone())
    else:
        block = resolve_block(conn, draft.get("block_code") or draft.get("block"))
    draft["block_id"] = block["id"] if block else None
    if block:
        draft["block_code"] = block["code"]
        draft["_site"] = block["site"]


def draft_spray_log(
    conn: sqlite3.Connection,
    wa_phone: str,
    extraction: dict[str, Any],
    raw_message: str = "",
) -> dict[str, Any]:
    """Merge an extraction into the open draft (or start one) and report what is missing.

    Never invents a value. Anything absent stays absent and comes back in missing_fields, which
    is what stops a plausible guess from becoming a legal record.
    """
    settings = get_settings()
    contact = _contact(conn, wa_phone)
    if not contact:
        return err("unknown_contact", wa_phone=wa_phone)
    wa_phone = contact["wa_phone"]

    existing = _open_draft(conn, wa_phone, "spray_report")
    draft: dict[str, Any] = json.loads(existing["draft_json"]) if existing else {}
    token = existing["confirm_token"] if existing else _token()

    correction = bool(existing and existing["corrects_log_id"] is not None)
    changed = _merge_fields(draft, extraction, correction=correction)

    # Obligation 3: keep the worker's own words, accumulated across the interview.
    # Dedupe: the agent often re-sends the same summary on each follow-up call, and
    # three identical paragraphs make the real sequence unreadable at audit time.
    if raw_message:
        prior = draft.get("raw_message") or ""
        if raw_message.strip() not in prior:
            draft["raw_message"] = f"{prior}\n{raw_message}".strip() if prior else raw_message

    draft.setdefault("log_date", datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d"))

    _prepare_block(conn, draft, changed)
    if not correction and draft.get("block_id"):
        block = conn.execute("SELECT acres FROM blocks WHERE id=?", (draft["block_id"],)).fetchone()
        draft.setdefault("acres_treated", block["acres"])
    _prepare_spray(conn, draft, changed, correction=correction)

    if not correction:
        draft["applicator_contact_id"] = contact["id"]
        draft["applicator_name"] = contact["full_name"]

    _attach_weather(conn, draft)

    missing = _validate_spray(draft)
    state = "ready" if not missing else "collecting"
    now = utcnow()

    with transaction(conn):
        if existing:
            conn.execute(
                """UPDATE drafts SET draft_json=?, missing_fields=?, state=?, updated_at_utc=?
                   WHERE confirm_token=?""",
                (json.dumps(draft), json.dumps(missing), state, now, token),
            )
        else:
            conn.execute(
                """INSERT INTO drafts (confirm_token, wa_phone, intent, target_table,
                                       draft_json, missing_fields, state,
                                       created_at_utc, updated_at_utc)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (token, wa_phone, "spray_report", "spray_log", json.dumps(draft),
                 json.dumps(missing), state, now, now),
            )

    return {
        "confirm_token": token,
        "draft": {k: v for k, v in draft.items() if not k.startswith("_")},
        "missing_fields": missing,
        "ready_to_confirm": not missing,
        "product_verified": draft.get("_product_verified"),
    }


def _check_rate_against_label(draft: dict[str, Any], product: dict[str, Any] | None) -> None:
    """Flag a rate materially above the product's label rate.

    Caught in real testing: 20 kg/ha committed against a 6 kg/ha label rate with nothing asked.
    That is a 3.3x over-application - a label violation and a residue risk - and exactly the kind
    of thing the record should carry rather than hide.
    """
    draft.pop("_rate_flag", None)
    if not product:
        return
    rate, label = draft.get("rate_value"), product.get("default_rate")
    if rate is None or label in (None, ""):
        return
    try:
        rate_f, label_f = float(rate), float(label)
    except (TypeError, ValueError):
        return
    if label_f <= 0:
        return
    # Units must match before a comparison means anything.
    du, pu = draft.get("rate_units"), product.get("rate_units")
    if du and pu and str(du).strip().lower() != str(pu).strip().lower():
        return
    if rate_f > label_f * 1.5:
        draft["_rate_flag"] = f"above_label_rate:{rate_f:g} vs label {label_f:g} {pu or ''}".strip()



def _attach_weather(conn: sqlite3.Connection, draft: dict[str, Any]) -> None:
    """Pre-fill weather-at-application from cache. Worker confirms it like any other field."""
    site = draft.get("_site")
    if not site or draft.get("wind_kmh") is not None:
        return
    row = conn.execute(
        """SELECT payload_json, source FROM weather_cache
           WHERE site = ? ORDER BY fetched_at_utc DESC LIMIT 1""",
        (site,),
    ).fetchone()
    if not row:
        return
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return
    hours = payload.get("hourly") if isinstance(payload, dict) else None
    if not hours:
        return

    target = draft.get("start_time")
    chosen = None
    if target:
        for h in hours:
            if str(h.get("time", "")).endswith(f"T{target}") or str(
                h.get("time", "")
            ).endswith(f" {target}"):
                chosen = h
                break
    chosen = chosen or hours[0]

    for src, dst in (
        ("wind_kmh", "wind_kmh"),
        ("wind_dir", "wind_dir"),
        ("temp_c", "temp_c"),
        ("rh_pct", "rh_pct"),
        ("sky", "sky"),
    ):
        if chosen.get(src) is not None and draft.get(dst) is None:
            draft[dst] = chosen[src]
    draft["weather_source"] = row["source"]


def present_confirmation(conn: sqlite3.Connection, confirm_token: str) -> dict[str, Any]:
    """Mark that the confirmation card has been SHOWN to the worker. Call before commit.

    This exists because of a real failure found in testing: draft_* used to set the state to
    'awaiting_confirm' by itself the moment the fields were complete, so the agent could draft
    and commit in one breath and no human ever agreed to anything. The token gate was checking
    that a draft was *ready*, not that a person had *said yes*.

    Splitting the transition means committing takes three distinct acts - complete the draft,
    show the card, receive a reply - and the reply itself is recorded on the record.
    """
    row = row_to_dict(
        conn.execute("SELECT * FROM drafts WHERE confirm_token = ?", (confirm_token,)).fetchone()
    )
    if row is None:
        return err("unknown_token")
    if row["state"] == "committed":
        return err("token_already_used")
    if row["state"] == "expired":
        return err("draft_expired")
    if row["state"] == "collecting":
        return err("draft_not_ready", missing_fields=json.loads(row["missing_fields"] or "[]"))

    with transaction(conn):
        conn.execute(
            """UPDATE drafts SET state='awaiting_confirm', presented_at_utc=?, updated_at_utc=?
               WHERE confirm_token=?""",
            (utcnow(), utcnow(), confirm_token),
        )
    return {
        "presented": True,
        "confirm_token": confirm_token,
        "draft": json.loads(row["draft_json"]),
        "next": "Send the card, then call commit with the worker's reply verbatim.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Commit — obligation 1 lives here
# ──────────────────────────────────────────────────────────────────────────────

# Replies that are not a person agreeing to anything. A commit carrying one of these is either
# a bug or a fabrication, and either way it must not become a signature on a legal record.
_EMPTY_REPLIES = {"", "-", "n/a", "na", "none", "null", "ok?", "?"}


def _load_committable(
    conn: sqlite3.Connection,
    confirm_token: str,
    intent: str,
    worker_reply: str,
    wa_phone: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve a token to a committable draft, or return a structured refusal.

    This is obligation 1. Every rejection path here is a case where a record would otherwise
    commit without the worker actually having confirmed it.

    `wa_phone`, when provided, is the RESOLVED sender of the confirmation reply. A draft is
    bound to the number it was opened with: a card forwarded to a friend, a group chat, or a
    different device cannot confirm someone else's record. The token alone is not the
    signature — the token PLUS the same number is.
    """
    row = row_to_dict(
        conn.execute(
            "SELECT * FROM drafts WHERE confirm_token = ?", (confirm_token,)
        ).fetchone()
    )
    if row is None:
        return None, err("unknown_token")
    if row["intent"] != intent:
        return None, err("wrong_intent", expected=intent, actual=row["intent"])
    if wa_phone is not None and row["wa_phone"] != _canonical_phone(conn, wa_phone):
        return None, err(
            "confirmation_from_wrong_number",
            draft_phone=row["wa_phone"],
            hint="the confirmation must come from the same number the draft was opened with",
        )
    if row["state"] == "committed":
        return None, err("token_already_used")
    if row["state"] == "expired":
        return None, err("draft_expired")
    if row["state"] == "ready":
        # The fields are complete but nobody has been shown the card yet.
        return None, err(
            "not_presented",
            hint="call present_confirmation, send the card, then commit with their reply",
        )
    if row["state"] != "awaiting_confirm":
        return None, err(
            "draft_not_ready",
            state=row["state"],
            missing_fields=json.loads(row["missing_fields"] or "[]"),
        )

    # Obligation 1: the worker's agreement is theirs to give, not the agent's to supply.
    reply = (worker_reply or "").strip()
    if reply.lower() in _EMPTY_REPLIES:
        return None, err(
            "no_worker_confirmation",
            hint="pass the worker's own affirmative words verbatim; do not invent them",
        )

    missing = json.loads(row["missing_fields"] or "[]")
    if missing:
        return None, err("missing_fields", missing_fields=missing)

    return row, None


def _commit_guard(conn: sqlite3.Connection, row: dict[str, Any], worker_reply: str,
                  wa_phone: str | None) -> dict[str, Any] | None:
    """Re-read token and target while holding the write lock, before any INSERT."""
    current, refusal = _load_committable(conn, row["confirm_token"], row["intent"],
                                        worker_reply, wa_phone)
    if refusal:
        return refusal
    if current != row:
        return err("draft_changed_reconfirm")
    if row["corrects_log_id"] is not None:
        table = "spray_log" if row["intent"] == "spray_report" else "task_log"
        superseded = conn.execute(f"SELECT id FROM {table} WHERE corrects_log_id=?",
                                  (row["corrects_log_id"],)).fetchone()
        if superseded:
            return err("already_superseded", log_id=row["corrects_log_id"],
                       superseded_by=superseded["id"])
    return None


def commit_spray_log(
    conn: sqlite3.Connection,
    confirm_token: str,
    worker_reply: str,
    wa_phone: str | None = None,
) -> dict[str, Any]:
    """Insert the confirmed record. Returns the committed row and the REI broadcast payload."""
    row, refusal = _load_committable(conn, confirm_token, "spray_report", worker_reply, wa_phone)
    if refusal:
        return refusal
    assert row is not None

    settings = get_settings()
    d = json.loads(row["draft_json"])

    # Re-validate what is actually about to be written, not the stored verdict. The drafts
    # row is mutable outside this flow; a draft edited (stale, buggy, tampered) after it
    # went ready must fail here exactly as it would have at draft time.
    residual = _validate_spray(d)
    if residual:
        return err(
            "missing_fields",
            missing_fields=residual,
            hint="the draft changed after confirmation was requested; re-collect and re-confirm",
        )

    rei_expires = None
    rei_hours = d.get("rei_hours")
    end = d.get("end_time") or d.get("start_time")
    if rei_hours is not None and end:
        base = _local_to_utc(d["log_date"], end, settings.timezone)
        if base:
            # Add the interval in UTC: an REI is a duration in real hours, so this stays
            # correct across a DST transition where local arithmetic would drift an hour.
            rei_expires = (base + timedelta(hours=float(rei_hours))).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

    with transaction(conn):
        refusal = _commit_guard(conn, row, worker_reply, wa_phone)
        if refusal:
            return refusal
        cur = conn.execute(
            """INSERT INTO spray_log (
                   log_date, start_time, end_time, block_id, acres_treated,
                   product_id, product_name_raw, pcp_number,
                   rate_value, rate_units, total_amount, total_units,
                   target_pest, method,
                   applicator_contact_id, applicator_name,
                   wind_kmh, wind_dir, temp_c, rh_pct, sky, weather_source,
                   rei_hours, rei_expires_at_utc, phi_days, notes,
                   raw_message, confirmed_by_reply, rate_flag,
                   source_msg_id, created_at_utc, created_by, corrects_log_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d.get("log_date"), d.get("start_time"), d.get("end_time"),
                d.get("block_id"), d.get("acres_treated"),
                d.get("product_id"), d.get("product_name_raw"), d.get("pcp_number"),
                d.get("rate_value"), d.get("rate_units"),
                d.get("total_amount"), d.get("total_units"),
                d.get("target_pest"), d.get("method"),
                d.get("applicator_contact_id"), d.get("applicator_name"),
                d.get("wind_kmh"), d.get("wind_dir"), d.get("temp_c"),
                d.get("rh_pct"), d.get("sky"), d.get("weather_source"),
                rei_hours, rei_expires, d.get("phi_days"), d.get("notes"),
                d.get("raw_message") or "", worker_reply.strip(), d.get("_rate_flag"),
                d.get("source_msg_id"),
                utcnow(), "hermes", row["corrects_log_id"],
            ),
        )
        log_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE drafts SET state='committed', updated_at_utc=? WHERE confirm_token=?",
            (utcnow(), confirm_token),
        )
        audit(
            conn,
            actor=row["wa_phone"],
            action="spray.committed",
            entity="spray_log",
            entity_id=log_id,
            detail_json=json.dumps({"corrects": row["corrects_log_id"]}),
        )

    committed = row_to_dict(
        conn.execute("SELECT * FROM spray_log WHERE id = ?", (log_id,)).fetchone()
    )
    block = row_to_dict(
        conn.execute("SELECT * FROM blocks WHERE id = ?", (d.get("block_id"),)).fetchone()
    )

    return {
        "committed": committed,
        "rei_broadcast": (
            {
                "block_code": block["code"] if block else None,
                "block_name": block["name"] if block else None,
                "product": d.get("product_name_raw"),
                "expires_at_utc": rei_expires,
                "rei_hours": rei_hours,
            }
            if rei_expires
            else None
        ),
        "supersedes": row["corrects_log_id"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Task log
# ──────────────────────────────────────────────────────────────────────────────

def draft_task_log(
    conn: sqlite3.Connection,
    wa_phone: str,
    extraction: dict[str, Any],
    raw_message: str = "",
) -> dict[str, Any]:
    settings = get_settings()
    contact = _contact(conn, wa_phone)
    if not contact:
        return err("unknown_contact", wa_phone=wa_phone)
    wa_phone = contact["wa_phone"]

    existing = _open_draft(conn, wa_phone, "task_report")
    draft: dict[str, Any] = json.loads(existing["draft_json"]) if existing else {}
    token = existing["confirm_token"] if existing else _token()

    changed = _merge_fields(draft, extraction, correction=bool(existing and existing["corrects_log_id"] is not None))

    if raw_message:
        prior = draft.get("raw_message") or ""
        draft["raw_message"] = f"{prior}\n{raw_message}".strip() if prior else raw_message

    draft.setdefault("log_date", datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d"))
    draft.setdefault("workers", [contact["id"]])

    _prepare_block(conn, draft, changed)

    missing = _validate_task(draft) + _validate_memberships(conn, draft)

    state = "ready" if not missing else "collecting"
    now = utcnow()

    with transaction(conn):
        if existing:
            conn.execute(
                """UPDATE drafts SET draft_json=?, missing_fields=?, state=?, updated_at_utc=?
                   WHERE confirm_token=?""",
                (json.dumps(draft), json.dumps(missing), state, now, token),
            )
        else:
            conn.execute(
                """INSERT INTO drafts (confirm_token, wa_phone, intent, target_table,
                                       draft_json, missing_fields, state,
                                       created_at_utc, updated_at_utc)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (token, wa_phone, "task_report", "task_log", json.dumps(draft),
                 json.dumps(missing), state, now, now),
            )

    return {
        "confirm_token": token,
        "draft": {k: v for k, v in draft.items() if not k.startswith("_")},
        "missing_fields": missing,
        "ready_to_confirm": not missing,
    }


def commit_task_log(
    conn: sqlite3.Connection,
    confirm_token: str,
    worker_reply: str,
    wa_phone: str | None = None,
) -> dict[str, Any]:
    row, refusal = _load_committable(conn, confirm_token, "task_report", worker_reply, wa_phone)
    if refusal:
        return refusal
    assert row is not None

    d = json.loads(row["draft_json"])

    residual = _validate_task(d) + _validate_memberships(conn, d)
    if residual:
        return err("missing_fields", missing_fields=residual,
                   hint="the draft changed after confirmation was requested; re-collect and re-confirm")

    with transaction(conn):
        refusal = _commit_guard(conn, row, worker_reply, wa_phone)
        if refusal:
            return refusal
        cur = conn.execute(
            """INSERT INTO task_log (
                   log_date, task_type, block_id, hours_total, quantity, quantity_unit,
                   start_time, end_time, notes, raw_message, confirmed_by_reply,
                   source_msg_id,
                   created_at_utc, created_by, corrects_log_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d.get("log_date"), d.get("task_type"), d.get("block_id"),
                d.get("hours_total"), d.get("quantity"), d.get("quantity_unit"),
                d.get("start_time"), d.get("end_time"), d.get("notes"),
                d.get("raw_message") or "", worker_reply.strip(), d.get("source_msg_id"),
                utcnow(), "hermes", row["corrects_log_id"],
            ),
        )
        log_id = int(cur.lastrowid)

        individual = {w["contact_id"]: w["hours"] for w in d.get("worker_hours") or []}
        for contact_id in d.get("workers") or []:
            conn.execute(
                "INSERT INTO task_workers (task_log_id, contact_id, hours) VALUES (?,?,?)",
                (log_id, contact_id, individual.get(contact_id)),
            )

        conn.execute(
            "UPDATE drafts SET state='committed', updated_at_utc=? WHERE confirm_token=?",
            (utcnow(), confirm_token),
        )
        audit(
            conn, actor=row["wa_phone"], action="task.committed",
            entity="task_log", entity_id=log_id,
            detail_json=json.dumps({"corrects": row["corrects_log_id"]}),
        )

    return {
        "committed": row_to_dict(
            conn.execute("SELECT * FROM task_log WHERE id = ?", (log_id,)).fetchone()
        ),
        "supersedes": row["corrects_log_id"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Corrections — supersede, never mutate
# ──────────────────────────────────────────────────────────────────────────────

def find_recent_logs(
    conn: sqlite3.Connection, wa_phone: str, limit: int = 5
) -> dict[str, Any]:
    contact = _contact(conn, wa_phone)
    if not contact:
        return err("unknown_contact", wa_phone=wa_phone)

    sprays = rows_to_dicts(
        conn.execute(
            """SELECT s.*, b.code AS block_code FROM spray_log_current s
               LEFT JOIN blocks b ON b.id = s.block_id
               WHERE s.applicator_contact_id = ?
               ORDER BY s.created_at_utc DESC LIMIT ?""",
            (contact["id"], limit),
        ).fetchall()
    )
    tasks = rows_to_dicts(
        conn.execute(
            """SELECT t.*, b.code AS block_code FROM task_log_current t
               LEFT JOIN blocks b ON b.id = t.block_id
               JOIN task_workers tw ON tw.task_log_id = t.id
               WHERE tw.contact_id = ?
               ORDER BY t.created_at_utc DESC LIMIT ?""",
            (contact["id"], limit),
        ).fetchall()
    )
    return {"spray_log": sprays, "task_log": tasks}


def draft_correction(
    conn: sqlite3.Connection,
    table: str,
    log_id: int,
    changes: dict[str, Any],
    raw_message: str = "",
) -> dict[str, Any]:
    """Pre-fill a NEW draft from an existing row with changes applied.

    The original row is never touched — the append-only trigger would refuse anyway. The
    correction commits as a new row carrying corrects_log_id, and both survive for the auditor.
    """
    if table not in ("spray_log", "task_log"):
        return err("bad_table", table=table)

    original = row_to_dict(
        conn.execute(f"SELECT * FROM {table} WHERE id = ?", (log_id,)).fetchone()
    )
    if original is None:
        return err("unknown_log", table=table, log_id=log_id)

    superseded = conn.execute(
        f"SELECT id FROM {table} WHERE corrects_log_id = ?", (log_id,)
    ).fetchone()
    if superseded:
        return err("already_superseded", log_id=log_id, superseded_by=superseded["id"])

    contact = row_to_dict(
        conn.execute(
            "SELECT * FROM contacts WHERE id = ?",
            (original.get("applicator_contact_id"),),
        ).fetchone()
    ) if table == "spray_log" else None

    wa_phone = contact["wa_phone"] if contact else changes.get("wa_phone")
    if not wa_phone:
        return err("cannot_determine_reporter", log_id=log_id)
    reporter = _contact(conn, wa_phone)
    if table == "task_log" and (not reporter or not conn.execute(
        "SELECT 1 FROM task_workers WHERE task_log_id=? AND contact_id=?",
        (log_id, reporter["id"]),
    ).fetchone()):
        return err("reporter_not_task_worker", log_id=log_id)
    wa_phone = _canonical_phone(conn, wa_phone)

    draft = {k: v for k, v in original.items() if k not in ("id", "created_at_utc", "created_by")}
    draft["corrects_log_id"] = log_id
    block = conn.execute("SELECT code FROM blocks WHERE id=?", (draft.get("block_id"),)).fetchone()
    if block:
        draft["block_code"] = block["code"]
    if table == "task_log":
        memberships = conn.execute(
            "SELECT contact_id,hours FROM task_workers WHERE task_log_id=? ORDER BY contact_id",
            (log_id,),
        ).fetchall()
        draft["workers"] = [r["contact_id"] for r in memberships]
        if any(r["hours"] is not None for r in memberships):
            draft["worker_hours"] = [dict(r) for r in memberships]
    else:
        draft["_rate_flag"] = original.get("rate_flag")
        draft["rate_confirmed"] = bool(original.get("rate_flag"))
        draft["_label_resolved"] = original.get("rei_hours") is not None
    changed = _merge_fields(draft, changes, correction=True)
    _prepare_block(conn, draft, changed)
    if table == "spray_log":
        _prepare_spray(conn, draft, changed, correction=True)

    if raw_message:
        draft["raw_message"] = f"{original.get('raw_message', '')}\n{raw_message}".strip()

    intent = "spray_report" if table == "spray_log" else "task_report"
    missing = (_validate_spray(draft) if table == "spray_log"
               else _validate_task(draft) + _validate_memberships(conn, draft))
    state = "ready" if not missing else "collecting"
    token = _token()
    now = utcnow()

    with transaction(conn):
        conn.execute(
            """INSERT INTO drafts (confirm_token, wa_phone, intent, target_table, draft_json,
                                   missing_fields, corrects_log_id, state,
                                   created_at_utc, updated_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (token, wa_phone, intent, table, json.dumps(draft),
             json.dumps(missing), log_id, state, now, now),
        )

    return {
        "confirm_token": token,
        "draft": {k: v for k, v in draft.items() if not k.startswith("_")},
        "missing_fields": missing,
        "ready_to_confirm": not missing,
        "corrects_log_id": log_id,
        "original": original,
    }


_PLACEHOLDER = re.compile(r"^(pcp-?)?(x+|n/?a|tbd|todo|\?+|0+)$", re.I)


def verify_product(
    conn: sqlite3.Connection,
    trade_name: str,
    *,
    verified_by: str,
    pcp_number: str,
    rei_hours: int,
    phi_days: int | None = None,
    max_temp_c: float | None = None,
    rainfast_hours: float | None = None,
) -> dict[str, Any]:
    """Flip a product to verified=1 after a human read the physical label.

    This is the only path out of obligation 4, and it is deliberately a human act with a named
    actor, recorded in audit_log.

    **pcp_number and rei_hours are REQUIRED**, and this is the whole point. In testing, a product
    was verified on the strength of "yes he read it" while the row kept its seeded placeholder
    (`PCP-XXXXX`) and an unconfirmed REI - so obligation 4 was satisfied on paper and defeated in
    fact. If someone actually read the label, they can state the registration number and the
    re-entry interval. If they cannot, they did not read it.
    """
    product = row_to_dict(
        conn.execute(
            "SELECT * FROM products WHERE lower(trade_name) = lower(?)", (trade_name,)
        ).fetchone()
    )
    if product is None:
        return err("unknown_product", trade_name=trade_name)

    if not str(pcp_number).strip() or _PLACEHOLDER.match(str(pcp_number).strip()):
        return err(
            "placeholder_pcp_number",
            given=pcp_number,
            hint="read the PCP registration number off the physical label",
        )
    try:
        rei = int(rei_hours)
    except (TypeError, ValueError):
        return err("bad_rei_hours", given=rei_hours)
    if rei < 0:
        return err("bad_rei_hours", given=rei_hours)

    fields = {
        "pcp_number": pcp_number,
        "rei_hours": rei,
        "phi_days": phi_days,
        "max_temp_c": max_temp_c,
        "rainfast_hours": rainfast_hours,
    }
    sets, params = [], []
    for key, value in fields.items():
        if value is not None:
            sets.append(f"{key} = ?")
            params.append(value)
    sets += ["verified = 1", "verified_by = ?", "verified_at_utc = ?"]
    params += [verified_by, utcnow(), product["id"]]

    with transaction(conn):
        conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ?", params)
        audit(
            conn, actor=verified_by, action="product.verified",
            entity="products", entity_id=product["id"],
            detail_json=json.dumps({k: v for k, v in fields.items() if v is not None}),
        )

    return {
        "verified": row_to_dict(
            conn.execute("SELECT * FROM products WHERE id = ?", (product["id"],)).fetchone()
        )
    }
