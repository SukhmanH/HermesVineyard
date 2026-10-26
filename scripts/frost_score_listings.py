r"""frost_score_listings — frost scores for listings, from the vineyard-terrain frost API.

The listings_frost cron job runs this every 2 hours with the terminal's python (execute_code is
blocked in cron). Each run collects the jobs that finished since the last run, submits listings
that have no score yet for the API's current model, stores one listing_frost row per listing and
model version, and prints a JSON verdict. Hermes reads the verdict and makes the calls this
script never makes: whether a newly scored listing is worth interrupting the owner for, and how
to ask the owner which parcel a listing is.

    python scripts/frost_score_listings.py                    # the cron run
    python scripts/frost_score_listings.py --ranking [--top N]
    python scripts/frost_score_listings.py --pending
    python scripts/frost_score_listings.py --confirm F12 --candidate 1
    python scripts/frost_score_listings.py --confirm F12 --pid 012-525-499
    python scripts/frost_score_listings.py --confirm F12 --location "49.134, -119.582"
    python scripts/frost_score_listings.py --confirm F12 --reject
    python scripts/frost_score_listings.py --score-properties [--force]

Three things here are load-bearing:

1. **Listing email text is untrusted.** Only structured fields reach the API: the street address,
   the town, a PID, the acres. Never the title, the subject or the body, which is where an
   injected instruction would live.
2. **Never block for long.** The API scores one parcel at a time and a parcel takes minutes, so
   this submits and comes back on a later run; every request shares one budget of about
   frost_api.run_budget_s seconds.
3. **Say an outage once.** If the API has been unreachable for more than down_notice_hours, the
   verdict carries one notice, and no other run repeats it until the API has come back and gone
   away again. The state lives in audit_log, so there is no per-host job id to configure.

Stdlib only (plus PyYAML for the templates): the production host is a Core 2 Duo without
SSE4.2, and Hermes never imports NumPy, Shapely or rasterio. All user-facing text comes from
templates/en.yaml under `frost:`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_file(path: str) -> None:
    """Populate os.environ from a .env file, without overriding what is already set.

    Stdlib, not python-dotenv, for the same reason as listings_triage.py: a cron-spawned run
    inherits no shell environment, and this must work in whichever interpreter runs it.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


_load_env_file(os.path.join(REPO, ".env"))

DB_PATH = os.environ.get("DB_PATH") or os.path.join(REPO, "data", "hermes.db")
TZ = ZoneInfo(os.environ.get("TZ") or "America/Vancouver")
ACTOR = "frost_score_listings"
IN_FLIGHT = ("submitted", "queued", "resolving", "fetching", "analyzing")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PID_RE = re.compile(r"^\s*(\d{3})-?(\d{3})-?(\d{3})\s*$")
LOW_COVERAGE_PCT = 80.0          # the API's own cut for the low_coverage flag
# The flags worth a word in a one-line ranking: each one says the score is less sure.
SHOWN_FLAGS = ("low_coverage", "buffer_inadequate", "upslope_nodata", "weak_floor",
               "mixed_deliveries", "delivery_mix_refused", "no_plantable_land",
               "aoi_resampled_2m", "multi_pid")

DEFAULTS = {
    "base_url": "http://100.71.243.94:8000",
    "timeout_s": 20,
    "buffer_m": 750,
    "run_budget_s": 60,
    "max_submit_per_run": 5,
    "retry_after_hours": 12,
    "max_attempts": 3,
    "down_notice_hours": 24,
    "ranking_active_days": 180,
    "reference_properties": [],
}


# ----------------------------------------------------------------------------- config
def load_settings() -> tuple[dict, list[str]]:
    """frost_api: from config/settings.yaml, over the defaults above. FROST_API_URL in the
    environment points a dry run at another server without editing the settings."""
    cfg, warnings = dict(DEFAULTS), []
    path = os.environ.get("SETTINGS_PATH") or os.path.join(REPO, "config", "settings.yaml")
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            raw = (yaml.safe_load(fh) or {}).get("frost_api") or {}
    except Exception as exc:
        raw = {}
        warnings.append(f"settings.yaml unreadable ({exc}); using built-in frost_api defaults")
    for key in cfg:
        if raw.get(key) is not None:
            cfg[key] = raw[key]
    if not raw and not warnings:
        warnings.append("no frost_api: section in settings.yaml; using built-in defaults")
    if os.environ.get("FROST_API_URL"):
        cfg["base_url"] = os.environ["FROST_API_URL"]
    return cfg, warnings


def load_templates() -> dict:
    import yaml
    with open(os.path.join(REPO, "templates", "en.yaml"), encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {})["frost"]


# ----------------------------------------------------------------------------- time
def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def local(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%a %b %d %H:%M")


# ----------------------------------------------------------------------------- the API
class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, unreachable: bool = False):
        super().__init__(message)
        self.status = status
        self.unreachable = unreachable


class Api:
    """The frost API. Every call shares one deadline, so a run never waits much longer than
    run_budget_s however many listings there are. The base URL comes from settings, never
    from a listing."""

    def __init__(self, base_url: str, token: str | None, timeout_s: float, budget_s: float,
                 clock=time.monotonic):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = float(timeout_s)
        self.clock = clock
        self.deadline = clock() + float(budget_s)

    def remaining(self) -> float:
        return self.deadline - self.clock()

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        left = self.remaining()
        if left < 1.0:
            raise ApiError("run budget spent")
        req = urllib.request.Request(
            self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        if method == "POST" and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, left)) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            raise ApiError(f"HTTP {exc.code}" + (f": {detail}" if detail else ""),
                           status=exc.code) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ApiError(f"unreachable: {exc}", unreachable=True) from exc

    def health(self) -> dict:
        return self._call("GET", "/api/health")

    def submit(self, body: dict) -> dict:
        return self._call("POST", "/api/parcel-jobs", body)

    def job(self, job_id: str) -> dict:
        if not JOB_ID_RE.fullmatch(job_id or ""):
            raise ApiError(f"not a parcel job id: {job_id!r}", status=404)
        return self._call("GET", f"/api/parcel-jobs/{job_id}")


# ----------------------------------------------------------------------------- inputs
def parse_pid(text) -> str | None:
    m = PID_RE.match(str(text or ""))
    return "-".join(m.groups()) if m else None


_COORD = r"(-?\d{1,3}\.\d+)"
_LOCATION_PATTERNS = (
    re.compile(rf"^\s*{_COORD}\s*[, ]\s*{_COORD}\s*$"),                       # 49.13, -119.58
    re.compile(rf"@{_COORD},{_COORD}"),                                         # maps .../@lat,lon,z
    re.compile(rf"[?&](?:q|ll|query|destination)={_COORD}(?:,|%2C)\s*{_COORD}"),  # ?q=lat,lon
    re.compile(rf"^\s*geo:{_COORD},{_COORD}"),                                  # geo:lat,lon
)


def parse_location(text) -> tuple[float, float] | None:
    """(lat, lon) from 'lat,lon', a maps link that carries its coordinates, or a geo: URI.

    Short links (maps.app.goo.gl/...) carry no coordinates and are never fetched: following a
    link from a message is how an injected URL gets visited. The answer is to ask for a pin."""
    for pattern in _LOCATION_PATTERNS:
        m = pattern.search(str(text or ""))
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if 48.0 <= lat <= 51.0 and -121.0 <= lon <= -118.0:
                return lat, lon
            return None
    return None


def _street_and_town(listing: dict) -> tuple[str | None, str | None]:
    address = (listing.get("address") or "").strip()
    if not address:
        return None, None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    street = parts[0]
    town = parts[1] if len(parts) > 1 else None
    if town and re.fullmatch(r"(?i)BC|B\.C\.|British Columbia", town):
        town = None
    return street, town or listing.get("area")


def request_body(listing: dict, cfg: dict) -> dict | None:
    """What the frost API gets for a listing, or None when nothing locates it.

    Structured fields only. The title, subject and email body never leave this machine: they
    are where an injected instruction would be, and the API has no use for them."""
    body = {"ref": listing["dedupe_key"], "buffer_m": cfg["buffer_m"]}
    pid = parse_pid(listing.get("pid"))
    street, town = _street_and_town(listing)
    if pid:
        body["pid"] = pid
    elif street:
        body["address"] = street[:200]
        if town:
            body["town"] = town[:80]
    else:
        return None
    acres = listing.get("acres")
    if isinstance(acres, (int, float)) and 0 < acres <= 5000:
        body["listing_acres"] = float(acres)
    return body


# ----------------------------------------------------------------------------- database
def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def has_frost_table(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                        "name='listing_frost'").fetchone() is not None


def active_listings(conn, cfg: dict, now: datetime) -> list[dict]:
    since = iso(now - timedelta(days=int(cfg["ranking_active_days"])))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)")}
    pid = "pid" if "pid" in cols else "NULL AS pid"
    return [dict(r) for r in conn.execute(
        f"SELECT dedupe_key, mls_number, title, price, acres, address, area, url, "
        f"first_seen_utc, {pid} FROM listings WHERE first_seen_utc >= ? "
        f"ORDER BY first_seen_utc", (since,))]


def current_rows(conn, model_version: str | None = None) -> dict[str, dict]:
    """The newest current row per dedupe_key (for one model version, if given)."""
    if model_version:
        rows = conn.execute("SELECT * FROM listing_frost_current WHERE model_version = ? "
                            "ORDER BY id", (model_version,))
    else:
        rows = conn.execute("SELECT * FROM listing_frost_current ORDER BY id")
    return {r["dedupe_key"]: dict(r) for r in rows}


def latest_model(conn) -> str | None:
    row = conn.execute("SELECT model_version FROM listing_frost WHERE status = 'done' "
                       "ORDER BY scored_at_utc DESC, id DESC LIMIT 1").fetchone()
    return row["model_version"] if row else None


def insert_row(conn, key: str, model_version: str, now: datetime, **fields) -> int:
    cols = ["dedupe_key", "model_version", "created_at_utc", "updated_at_utc", *fields]
    vals = [key, model_version, iso(now), iso(now), *fields.values()]
    cur = conn.execute(f"INSERT INTO listing_frost ({', '.join(cols)}) "
                       f"VALUES ({', '.join('?' * len(cols))})", vals)
    return int(cur.lastrowid)


def update_row(conn, row_id: int, now: datetime, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE listing_frost SET {sets}, updated_at_utc = ? WHERE id = ?",
                 [*fields.values(), iso(now), row_id])


def audit(conn, action: str, detail: dict, now: datetime) -> None:
    conn.execute("INSERT INTO audit_log (at_utc, actor, action, entity, detail_json) "
                 "VALUES (?,?,?,?,?)", (iso(now), ACTOR, action, "frost_api",
                                        json.dumps(detail, ensure_ascii=False)))


def api_down_notice(conn, reachable: bool, now: datetime, cfg: dict, templates: dict):
    """Record the API's state in audit_log; return the outage notice exactly once per outage,
    after it has lasted down_notice_hours."""
    last = conn.execute("SELECT action, at_utc FROM audit_log WHERE action IN "
                        "('frost_api.down', 'frost_api.up') ORDER BY id DESC LIMIT 1").fetchone()
    if reachable:
        if last is not None and last["action"] == "frost_api.down":
            audit(conn, "frost_api.up", {"down_since": last["at_utc"]}, now)
        return None
    if last is None or last["action"] == "frost_api.up":
        audit(conn, "frost_api.down", {}, now)
        return None
    since = parse_iso(last["at_utc"])
    if now - since < timedelta(hours=float(cfg["down_notice_hours"])):
        return None
    if conn.execute("SELECT 1 FROM audit_log WHERE action = 'frost_api.down_noticed' AND "
                    "at_utc >= ?", (last["at_utc"],)).fetchone():
        return None
    audit(conn, "frost_api.down_noticed", {"down_since": last["at_utc"]}, now)
    return templates["api_down"].format(since=local(since))


# ----------------------------------------------------------------------------- jobs
def _submit(conn, api: Api, body: dict, key: str, model_version: str, now: datetime,
            row: dict | None = None, supersedes: int | None = None, cfg: dict | None = None):
    """Send one request; record it on row (re-submission) or a new row. Raises ApiError when
    the API is unreachable or the run budget is spent, so the caller stops."""
    try:
        out = api.submit(body)
    except ApiError as exc:
        if exc.unreachable or exc.status is None:
            raise
        # a 4xx is the request, not the weather: retrying it would fail the same way
        attempts = int((cfg or DEFAULTS)["max_attempts"])
        if row is not None and row["status"] != "done":
            update_row(conn, row["id"], now, status="failed", error=str(exc),
                       attempts=attempts)
            return row["id"]
        return insert_row(conn, key, model_version, now, status="failed", error=str(exc),
                          attempts=attempts, listing_acres=body.get("listing_acres"),
                          supersedes_id=supersedes)
    job_id = out.get("job_id") or ""
    if not JOB_ID_RE.fullmatch(job_id):
        raise ApiError(f"the frost API returned no job id ({out})")
    if row is not None and row["status"] != "done":
        update_row(conn, row["id"], now, status="submitted", api_job_id=job_id,
                   attempts=int(row["attempts"]) + 1, error=None, candidates_json=None)
        return row["id"]
    return insert_row(conn, key, model_version, now, status="submitted", api_job_id=job_id,
                      attempts=1, listing_acres=body.get("listing_acres"),
                      supersedes_id=supersedes)


def _metrics_fields(view: dict, now: datetime) -> dict:
    m = view.get("metrics") or {}
    pids = m.get("pids") or []
    return {
        "status": "done",
        "model_version": m.get("model_version"),
        "pid": m.get("pid") or (", ".join(pids) if pids else None),
        "parcel_source": m.get("parcel_source"),
        "parcel_confidence": m.get("parcel_confidence"),
        "parcel_acres": m.get("area_acres"),
        "frost_score": m.get("frost_score"),
        "frost_safe_acres": m.get("frost_safe_acres"),
        "largest_contiguous_safe_acres": m.get("largest_contiguous_safe_acres"),
        "pct_high_risk": m.get("pct_high_risk"),
        "frost_risk_mean": m.get("frost_risk_mean"),
        "coverage_pct": m.get("coverage_pct"),
        "drivers_json": json.dumps(m.get("drivers_pct") or {}),
        "flags_json": json.dumps(m.get("flags") or []),
        "confidence": m.get("confidence"),
        "map_url": view.get("map_url"),
        "scored_at_utc": iso(now),
        "error": None,
    }


def collect(conn, api: Api, now: datetime) -> list[dict]:
    """Ask the API about every row still in flight. Returns what changed, as events."""
    events = []
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM listing_frost_current WHERE status IN "
        f"({', '.join('?' * len(IN_FLIGHT))}) AND api_job_id IS NOT NULL", IN_FLIGHT)]
    for row in rows:
        try:
            view = api.job(row["api_job_id"])
        except ApiError as exc:
            if exc.status == 404:
                update_row(conn, row["id"], now, status="failed",
                           error="the frost API no longer has this job")
                events.append({"kind": "failed", "row_id": row["id"], "key": row["dedupe_key"],
                               "error": "the frost API no longer has this job"})
                continue
            if exc.unreachable or exc.status is None:
                break
            continue
        status = view.get("status")
        if status == "done":
            fields = _metrics_fields(view, now)
            fields["model_version"] = fields["model_version"] or row["model_version"]
            update_row(conn, row["id"], now, **fields)
            events.append({"kind": "scored", "row_id": row["id"], "key": row["dedupe_key"],
                           "metrics": view.get("metrics") or {},
                           "map_url": view.get("map_url")})
        elif status == "needs_confirmation":
            parcel = view.get("parcel") or {}
            update_row(conn, row["id"], now, status="needs_confirmation",
                       candidates_json=json.dumps(parcel.get("candidates") or []),
                       error="; ".join(parcel.get("reasons") or []) or None,
                       map_url=view.get("map_url"))
            events.append({"kind": "needs_confirmation", "row_id": row["id"],
                           "key": row["dedupe_key"], "parcel": parcel,
                           "map_url": view.get("map_url")})
        elif status == "failed":
            update_row(conn, row["id"], now, status="failed", error=view.get("error"))
            events.append({"kind": "failed", "row_id": row["id"], "key": row["dedupe_key"],
                           "error": view.get("error")})
        elif status in IN_FLIGHT and status != row["status"]:
            update_row(conn, row["id"], now, status=status)
    return events


def _due_for_retry(row: dict, cfg: dict, now: datetime) -> bool:
    return (row["status"] == "failed" and int(row["attempts"]) < int(cfg["max_attempts"])
            and now - parse_iso(row["updated_at_utc"])
            >= timedelta(hours=float(cfg["retry_after_hours"])))


def submit_new(conn, api: Api, cfg: dict, model_version: str, now: datetime) -> list[dict]:
    """Submit active listings with no row for this model version, and retry failed ones that
    are due. Listings with nothing to locate them get a 'skipped' row (Hermes asks the owner)."""
    events, sent = [], 0
    rows = current_rows(conn, model_version)
    for listing in active_listings(conn, cfg, now):
        if sent >= int(cfg["max_submit_per_run"]) or api.remaining() < 5:
            break
        key = listing["dedupe_key"]
        row = rows.get(key)
        if row is not None and not _due_for_retry(row, cfg, now):
            continue
        body = request_body(listing, cfg)
        if body is None:
            if row is None:
                rid = insert_row(conn, key, model_version, now, status="skipped",
                                 error="no address or PID in the listing")
                events.append({"kind": "needs_location", "row_id": rid, "key": key})
            continue
        try:
            rid = _submit(conn, api, body, key, model_version, now, row=row, cfg=cfg)
        except ApiError:
            break
        sent += 1
        events.append({"kind": "submitted", "row_id": rid, "key": key})
    return events


def score_properties(conn, api: Api, cfg: dict, model_version: str, now: datetime,
                     force: bool = False) -> list[dict]:
    """Submit the owner's properties (frost_api.reference_properties) as reference rows."""
    events = []
    rows = current_rows(conn, model_version)
    for prop in cfg["reference_properties"]:
        key = f"property:{prop['code']}"
        row = rows.get(key)
        if row is not None and not force and row["status"] in ("done", *IN_FLIGHT):
            continue
        body = {"ref": key, "buffer_m": cfg["buffer_m"]}
        if parse_pid(prop.get("pid")):
            body["pid"] = parse_pid(prop["pid"])
        elif prop.get("lat") is not None and prop.get("lon") is not None:
            body.update(lat=float(prop["lat"]), lon=float(prop["lon"]))
        elif prop.get("address"):
            body.update(address=prop["address"], town=prop.get("town"))
        else:
            continue
        supersedes = row["id"] if (row is not None and row["status"] == "done") else None
        rid = _submit(conn, api, body, key, model_version, now,
                      row=None if supersedes else row, supersedes=supersedes, cfg=cfg)
        events.append({"kind": "submitted", "row_id": rid, "key": key})
    return events


def confirm(conn, api: Api, cfg: dict, ref: str, now: datetime, *, candidate: int | None = None,
            pid: str | None = None, location: str | None = None, reject: bool = False) -> dict:
    """The owner's answer to a parcel question, sent back to the API as confirmed structured
    fields. A scored row is never edited: a corrected parcel gets a row that supersedes it."""
    m = re.fullmatch(r"[Ff]?(\d+)", (ref or "").strip())
    row = conn.execute("SELECT * FROM listing_frost WHERE id = ?",
                       (int(m.group(1)),)).fetchone() if m else None
    if row is None:
        return {"ok": False, "error": f"no frost row {ref!r}"}
    row = dict(row)
    if reject:
        if row["status"] == "done":
            return {"ok": False, "error": "that listing is already scored"}
        update_row(conn, row["id"], now, status="skipped",
                   error="owner: none of these parcels; needs a PID or a location")
        return {"ok": True, "row_id": row["id"], "status": "skipped"}

    body = {"ref": row["dedupe_key"], "buffer_m": cfg["buffer_m"], "confirmed": True}
    if row["listing_acres"]:
        body["listing_acres"] = float(row["listing_acres"])
    if candidate is not None:
        cands = json.loads(row["candidates_json"] or "[]")
        chosen = next((c for c in cands if c.get("index") == candidate), None)
        if chosen is None:
            return {"ok": False, "error": f"no candidate {candidate} on {ref}"}
        if chosen.get("pid"):
            body["pid"] = chosen["pid"]
        elif chosen.get("clss_id"):
            body["clss_id"] = chosen["clss_id"]
        else:
            return {"ok": False, "error": f"candidate {candidate} has no PID or lot id"}
    elif pid:
        pids = [parse_pid(p) for p in re.split(r"[,\s]+", pid) if p]
        if not pids or None in pids:
            return {"ok": False, "error": f"not a PID (###-###-###): {pid!r}"}
        body["pid"] = pids[0] if len(pids) == 1 else pids
    elif location:
        ll = parse_location(location)
        if ll is None:
            return {"ok": False, "error": "no coordinates in that location; ask for a "
                                          "location pin or lat,lon"}
        body["lat"], body["lon"] = ll
    else:
        return {"ok": False, "error": "give --candidate, --pid, --location or --reject"}

    supersedes = row["id"] if row["status"] == "done" else None
    try:
        rid = _submit(conn, api, body, row["dedupe_key"], row["model_version"], now,
                      row=None if supersedes else row, supersedes=supersedes, cfg=cfg)
    except ApiError as exc:
        return {"ok": False, "error": f"frost API: {exc}"}
    return {"ok": True, "row_id": rid, "status": "submitted", "supersedes": supersedes}


def pending(conn) -> list[dict]:
    """Rows waiting on the owner: parcel confirmations and listings with no location."""
    out = []
    for row in conn.execute("SELECT f.*, l.address, l.title FROM listing_frost_current f "
                            "LEFT JOIN listings l ON l.dedupe_key = f.dedupe_key "
                            "WHERE f.status IN ('needs_confirmation', 'skipped') "
                            "ORDER BY f.id"):
        out.append({"ref": f"F{row['id']}", "dedupe_key": row["dedupe_key"],
                    "status": row["status"], "address": row["address"] or row["title"],
                    "reason": row["error"], "map_url": row["map_url"],
                    "candidates": json.loads(row["candidates_json"] or "[]")})
    return out


# ----------------------------------------------------------------------------- rendering
def money(value) -> str:
    if isinstance(value, (int, float)):
        return f"${value:,.0f}"
    return None


def _flags(row: dict, templates: dict) -> str:
    flags = json.loads(row.get("flags_json") or "[]")
    words = []
    for f in SHOWN_FLAGS:
        if f in flags and f in templates["flag"]:
            words.append(templates["flag"][f].format(coverage=_num(row.get("coverage_pct"))))
    return templates["flags_suffix"].format(flags=", ".join(words)) if words else ""


def _num(v, nd=0) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{nd}f}" if nd else f"{round(v):d}"


def per_safe_acre(price, safe_acres, templates: dict) -> str:
    if not isinstance(price, (int, float)):
        return templates["price_missing"]
    if not safe_acres:
        return templates["no_safe_acres"]
    return templates["per_safe_acre"].format(amount=money(price / safe_acres))


def _partial(row: dict) -> bool:
    flags = json.loads(row.get("flags_json") or "[]")
    cov = row.get("coverage_pct")
    return "low_coverage" in flags or (cov is not None and cov < LOW_COVERAGE_PCT)


def _listing_lines(rank: int, listing: dict, row: dict, templates: dict) -> list[str]:
    lines = [templates["row"].format(
        rank=rank, address=listing.get("address") or listing.get("title") or row["dedupe_key"],
        price=money(listing.get("price")) or templates["price_missing"],
        score=_num(row["frost_score"]), safe_ac=_num(row["frost_safe_acres"], 1),
        per_safe_ac=per_safe_acre(listing.get("price"), row["frost_safe_acres"], templates),
        confidence=row["confidence"] or "n/a", flags=_flags(row, templates))]
    if listing.get("url"):
        lines.append(templates["url_line"].format(url=listing["url"]))
    if row.get("map_url"):
        lines.append(templates["map_line"].format(map_url=row["map_url"]))
    return lines


def ranking(conn, cfg: dict, templates: dict, now: datetime | None = None,
            top: int | None = None, model_version: str | None = None) -> str:
    """The frost ranking of active listings. The owner's properties sit among them as
    reference rows (or, with --top, on one scale line) so the numbers have a scale; listings
    with partial LiDAR coverage are ranked separately, below, and say so."""
    now = now or now_utc()
    model_version = model_version or latest_model(conn)
    rows = current_rows(conn, model_version) if model_version else {}
    scored, counts = [], Counter()
    for listing in active_listings(conn, cfg, now):
        row = rows.get(listing["dedupe_key"])
        if row is None or row["status"] in IN_FLIGHT:
            counts["running"] += 1
        elif row["status"] == "done":
            scored.append((listing, row))
        else:
            counts[row["status"]] += 1
    refs = []
    for prop in cfg["reference_properties"]:
        row = rows.get(f"property:{prop['code']}")
        if row is not None and row["status"] == "done":
            refs.append((prop, row))

    def score(item):
        return item[1]["frost_score"] if item[1]["frost_score"] is not None else -1.0

    full = sorted([s for s in scored if not _partial(s[1])], key=score, reverse=True)
    partial = sorted([s for s in scored if _partial(s[1])], key=score, reverse=True)
    if top:
        full, partial = full[:top], partial[:max(0, top - len(full))]
    lines = [templates["ranking_header"].format(n=len(scored))] if scored else \
        [templates["empty"]]

    rank = 0
    ordered = sorted([("listing", s) for s in full] +
                     ([] if top else [("ref", r) for r in refs]),
                     key=lambda kv: score(kv[1]), reverse=True)
    for kind, (item, row) in ordered:
        if kind == "listing":
            rank += 1
            lines.extend(_listing_lines(rank, item, row, templates))
        else:
            lines.append(templates["ref_row"].format(
                name=item["name"], score=_num(row["frost_score"]),
                safe_ac=_num(row["frost_safe_acres"], 1)))
    if partial:
        lines.append(templates["partial_header"])
        for listing, row in partial:
            rank += 1
            lines.extend(_listing_lines(rank, listing, row, templates))
    if top and refs:
        scale = ", ".join(f"{p['name']} {_num(r['frost_score'])}"
                          for p, r in sorted(refs, key=score, reverse=True))
        lines.append(templates["scale_line"].format(scale=scale))
    if any(counts.values()):
        lines.append(templates["pending"].format(
            n_confirm=counts["needs_confirmation"], n_running=counts["running"],
            n_failed=counts["failed"], n_skipped=counts["skipped"]))
    return "\n".join(lines)


def _listing(conn, key: str) -> dict:
    row = conn.execute("SELECT * FROM listings WHERE dedupe_key = ?", (key,)).fetchone()
    return dict(row) if row else {"dedupe_key": key}


def _name(conn, key: str, cfg: dict) -> str:
    if key.startswith("property:"):
        code = key.split(":", 1)[1]
        return next((p["name"] for p in cfg["reference_properties"] if p["code"] == code), key)
    listing = _listing(conn, key)
    return listing.get("address") or listing.get("title") or key


def render_events(conn, events: list[dict], cfg: dict, templates: dict) -> tuple[str, dict]:
    """The owner-facing text for what this run changed, and the structured items Hermes
    decides on."""
    lines, items = [], {"scored": [], "needs_confirmation": [], "failed": []}
    for ev in events:
        name = _name(conn, ev["key"], cfg)
        ref = f"F{ev['row_id']}"
        if ev["kind"] == "scored":
            m = ev["metrics"]
            listing = _listing(conn, ev["key"])
            row = {"flags_json": json.dumps(m.get("flags") or []),
                   "coverage_pct": m.get("coverage_pct")}
            lines.append(templates["scored"].format(
                address=name, score=_num(m.get("frost_score")),
                safe_ac=_num(m.get("frost_safe_acres"), 1),
                plantable_ac=_num(m.get("plantable_acres"), 1),
                confidence=m.get("confidence") or "n/a", flags=_flags(row, templates)))
            if listing.get("url"):
                lines.append(templates["url_line"].format(url=listing["url"]))
            if ev.get("map_url"):
                lines.append(templates["map_line"].format(map_url=ev["map_url"]))
            items["scored"].append({
                "ref": ref, "dedupe_key": ev["key"], "name": name,
                "price": listing.get("price"), "area": listing.get("area"),
                "listing_acres": listing.get("acres"), "url": listing.get("url"),
                "frost_score": m.get("frost_score"),
                "frost_safe_acres": m.get("frost_safe_acres"),
                "largest_contiguous_safe_acres": m.get("largest_contiguous_safe_acres"),
                "pct_high_risk": m.get("pct_high_risk"), "confidence": m.get("confidence"),
                "flags": m.get("flags") or [], "map_url": ev.get("map_url"),
                "per_safe_acre": per_safe_acre(listing.get("price"),
                                               m.get("frost_safe_acres"), templates)})
        elif ev["kind"] == "needs_confirmation":
            parcel = ev.get("parcel") or {}
            cands = parcel.get("candidates") or []
            reason = "; ".join(parcel.get("reasons") or [])
            if cands:
                cand_lines = "\n".join(
                    (templates["candidate_line"] if c.get("pid") else
                     templates["candidate_lot_line"]).format(
                        index=c.get("index"), pid=c.get("pid"), acres=c.get("acres"),
                        designator=c.get("designator"))
                    for c in cands)
                text = templates["confirm"].format(address=name, reason=reason,
                                                   candidate_lines=cand_lines,
                                                   map_url=ev.get("map_url"), ref=ref)
            else:
                text = templates["ask_location"].format(address=name, reason=reason, ref=ref)
            lines.append(text.rstrip())
            items["needs_confirmation"].append({"ref": ref, "dedupe_key": ev["key"],
                                                "name": name, "reasons": parcel.get("reasons"),
                                                "candidates": cands,
                                                "map_url": ev.get("map_url"),
                                                "confirm_text": text.rstrip()})
        elif ev["kind"] == "needs_location":
            text = templates["ask_location"].format(
                address=name, reason="the listing has no address or PID", ref=ref)
            lines.append(text)
            items["needs_confirmation"].append({"ref": ref, "dedupe_key": ev["key"],
                                                "name": name, "candidates": [],
                                                "confirm_text": text})
        elif ev["kind"] == "failed":
            lines.append(templates["failed"].format(address=name, error=ev.get("error")))
            items["failed"].append({"ref": ref, "dedupe_key": ev["key"], "name": name,
                                    "error": ev.get("error")})
    return "\n".join(lines), items


# ----------------------------------------------------------------------------- the run
def run_cron(conn, api: Api, cfg: dict, templates: dict, now: datetime) -> dict:
    out = {"verdict": "SILENT", "report_text": "", "model_version": None, "submitted": [],
           "scored": [], "needs_confirmation": [], "failed": [], "warnings": [],
           "api": {"reachable": False, "notice": None}}
    reachable = False
    try:
        health = api.health()
        reachable = bool(health.get("ok"))
        out["model_version"] = health.get("model_version")
        if not health.get("parcel_jobs"):
            out["warnings"].append("the frost API has parcel jobs disabled "
                                   "(VTA_API_TOKEN is not set on the server)")
    except ApiError as exc:
        out["warnings"].append(f"frost API: {exc}")
    notice = api_down_notice(conn, reachable, now, cfg, templates)
    out["api"] = {"reachable": reachable, "notice": notice}
    if not reachable or not out["model_version"]:
        if notice:
            out.update(verdict="REPORT", report_text=notice)
        return out

    events = collect(conn, api, now)
    if not api.token:
        out["warnings"].append("FROST_API_TOKEN is not set: nothing new can be submitted")
    else:
        events += submit_new(conn, api, cfg, out["model_version"], now)
    out["submitted"] = [e["key"] for e in events if e["kind"] == "submitted"]
    text, items = render_events(conn, [e for e in events if e["kind"] != "submitted"], cfg,
                                templates)
    out.update(items)
    if out["scored"] or out["needs_confirmation"] or out["failed"]:
        out.update(verdict="REPORT", report_text=text)
    return out


def emit(doc: dict) -> None:
    print(json.dumps(doc, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    # Cron pipes stdout, and a Windows pipe defaults to cp1252
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="frost_score_listings.py",
                                 description="Frost scores for listings (frost API)")
    ap.add_argument("--ranking", action="store_true", help="print the frost ranking")
    ap.add_argument("--top", type=int, help="with --ranking: the top N listings only")
    ap.add_argument("--pending", action="store_true", help="parcels waiting on the owner")
    ap.add_argument("--confirm", metavar="REF", help="answer a parcel question (F<id>)")
    ap.add_argument("--candidate", type=int)
    ap.add_argument("--pid")
    ap.add_argument("--location")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--score-properties", action="store_true",
                    help="submit frost_api.reference_properties as reference rows")
    ap.add_argument("--force", action="store_true", help="re-score scored properties")
    args = ap.parse_args(argv)

    cfg, warnings = load_settings()
    try:
        templates = load_templates()
    except Exception as exc:
        emit({"verdict": "REPORT", "error": "templates_unreadable",
              "report_text": f"frost_score_listings could not read templates/en.yaml: {exc}"})
        return 1
    if not os.path.exists(DB_PATH):
        emit({"verdict": "REPORT", "error": "no_db",
              "report_text": f"frost_score_listings: no database at {DB_PATH}"})
        return 1
    conn = connect()
    try:
        if not has_frost_table(conn):
            emit({"verdict": "REPORT", "error": "not_migrated",
                  "report_text": "The database has no listing_frost table yet: run "
                                 "`python -m vineyard_mcp init-db` (schema v8) first."})
            return 1
        if args.ranking:
            print(ranking(conn, cfg, templates, top=args.top))
            return 0
        if args.pending:
            emit({"pending": pending(conn)})
            return 0
        api = Api(cfg["base_url"], os.environ.get("FROST_API_TOKEN"), cfg["timeout_s"],
                  cfg["run_budget_s"])
        now = now_utc()
        if args.confirm:
            emit(confirm(conn, api, cfg, args.confirm, now, candidate=args.candidate,
                         pid=args.pid, location=args.location, reject=args.reject))
            return 0
        if args.score_properties:
            try:
                model_version = api.health().get("model_version")
                events = score_properties(conn, api, cfg, model_version, now, force=args.force)
            except ApiError as exc:
                emit({"ok": False, "error": f"frost API: {exc}"})
                return 1
            emit({"ok": True, "submitted": [e["key"] for e in events]})
            return 0
        out = run_cron(conn, api, cfg, templates, now)
        out["warnings"] = warnings + out["warnings"]
        emit(out)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
