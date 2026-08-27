"""Block registry intake — how owner-provided facts land in `blocks` safely.

The registry starts thin on purpose: an invented acre is worse than a missing acre. This is the
guarded door for real data when the owner or a manager provides it: role-gated, whitelisted
fields, physically-plausible validation, and an audit row for every change. A bad number stored
here poisons every water/GDD/Pre-Harvest calculation downstream, quietly — so validation refuses
rather than stores.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import audit, row_to_dict, utcnow

# lat/lon sanity window = roughly the Okanagan Valley. Catches transposed digits without
# pretending to geocode.
_LAT_RANGE = (48.8, 49.8)
_LON_RANGE = (-120.1, -118.9)

_ALLOWED_FIELDS = {
    "name", "acres", "variety", "row_count", "lat", "lon", "soil_type",
    "irrigation_type", "emitter_lph", "emitters_per_vine", "vines_per_acre", "notes",
}


def _err(code: str, **extra: Any) -> dict[str, Any]:
    return {"error": code, **extra}


def update_block(
    conn: sqlite3.Connection, block_code: str, changes: dict[str, Any], updated_by: str
) -> dict[str, Any]:
    """Apply owner-provided facts to a block. Owner/manager only; every change audited."""
    contact = row_to_dict(
        conn.execute(
            "SELECT * FROM contacts WHERE (wa_phone = ? OR wa_lid = ?) AND active = 1",
            (updated_by, updated_by),
        ).fetchone()
    )
    if contact is None:
        return _err("unknown_caller", updated_by=updated_by)
    if contact["role"] not in ("owner", "manager"):
        return _err("forbidden_role", role=contact["role"],
                    hint="only the owner or a manager can update the block registry")

    block = row_to_dict(
        conn.execute("SELECT * FROM blocks WHERE code = ?", (block_code,)).fetchone()
    )
    if block is None:
        return _err("unknown_block", block_code=block_code)
    if not isinstance(changes, dict) or not changes:
        return _err("no_changes")

    unknown = sorted(set(changes) - _ALLOWED_FIELDS)
    if unknown:
        return _err("unknown_fields", unknown=unknown, allowed=sorted(_ALLOWED_FIELDS))

    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if value is None:
            continue
        if key in ("name", "variety", "soil_type", "notes"):
            text = str(value).strip()[:200]
            if not text and key == "name":
                # blocks.name is NOT NULL - blanking it would raise IntegrityError out of a
                # module whose whole contract is to refuse rather than raise.
                return _err("invalid_value", field=key, value=value,
                            hint="a block name cannot be blank")
            clean[key] = text or None
        elif key == "acres":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if not 0 < v < 10_000:
                return _err("invalid_value", field=key, value=value,
                            hint="acres must be > 0 and plausible")
            clean[key] = v
        elif key in ("row_count", "vines_per_acre"):
            try:
                v = int(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if v < 0 or v > 100_000:
                return _err("invalid_value", field=key, value=value)
            clean[key] = v
        elif key == "emitters_per_vine":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if not 0 < v <= 50:
                return _err("invalid_value", field=key, value=value)
            clean[key] = v
        elif key == "emitter_lph":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if not 0 < v <= 100:
                return _err("invalid_value", field=key, value=value,
                            hint="emitter litres/hour must be > 0")
            clean[key] = v
        elif key == "irrigation_type":
            if value not in ("drip", "sprinkler", "none"):
                return _err("invalid_value", field=key, value=value,
                            hint="irrigation_type is drip | sprinkler | none")
            clean[key] = value
        elif key == "lat":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if not _LAT_RANGE[0] <= v <= _LAT_RANGE[1]:
                return _err("invalid_value", field=key, value=value,
                            hint=f"latitude outside the Okanagan window {_LAT_RANGE}")
            clean[key] = v
        elif key == "lon":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return _err("invalid_value", field=key, value=value)
            if not _LON_RANGE[0] <= v <= _LON_RANGE[1]:
                return _err("invalid_value", field=key, value=value,
                            hint=f"longitude outside the Okanagan window {_LON_RANGE}")
            clean[key] = v

    if not clean:
        return _err("no_changes", hint="every provided field was null")

    sets = ", ".join(f"{k} = ?" for k in clean)
    with conn:
        conn.execute(f"UPDATE blocks SET {sets} WHERE code = ?", (*clean.values(), block_code))
        audit(
            conn,
            actor=contact["wa_phone"],
            action="block.updated",
            entity="blocks",
            entity_id=block["id"],
            detail_json=__import__("json").dumps(
                {"changes": clean, "by_name": contact["short_name"]}, default=str
            ),
        )

    updated = row_to_dict(
        conn.execute("SELECT * FROM blocks WHERE code = ?", (block_code,)).fetchone()
    )
    return {"updated": True, "block_code": block_code, "changes": clean,
            "block": updated, "at_utc": utcnow()}
