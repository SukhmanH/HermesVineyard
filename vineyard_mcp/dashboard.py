from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .config import Settings, get_settings

ROW_LIMIT = 200
ASSETS = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'; object-src 'none'"
)
UNAVAILABLE = "Database unavailable. Check that an existing vineyard database is configured and readable."
SECTION_ERROR = "Unavailable: this database does not support this section or could not be read."
PENDING = "state IN ('collecting', 'ready', 'awaiting_confirm')"
AUDIT_ACTIONS = "('agent.decision','job.started','job.finished','job.failed','job.skipped')"


class DashboardUnavailable(Exception):
    pass


def _epoch(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _text(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    value = re.sub(r"\b(?:Bearer\s+\S+|(?:api[_ -]?key|password|secret|confirm[_ -]?token|access[_ -]?token)\s*[:=]\s*\S+)", "[redacted]", value, flags=re.I)
    value = re.sub(r"(?<!\w)\+?\d[\d ().-]{8,}\d(?!\w)",
                   lambda match: "[redacted phone]" if sum(c.isdigit() for c in match[0]) >= 10 else match[0], value)
    value = re.sub(r"\b\d+@(?:lid|s\.whatsapp\.net)\b", "[redacted identity]", value)
    value = re.sub(r"(?:https?://\S+|[A-Za-z]:[\\/]\S+|(?<!\w)/(?:[^\s/]+/)+\S*|~/\S+)", "[redacted location]", value)
    return value[:500]


def _cell(value: object) -> str | int | float | None:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return None


def _object(value: object) -> dict:
    if not isinstance(value, str):
        return {}
    try:
        result = json.loads(value)
    except (ValueError, RecursionError):
        return {}
    return result if isinstance(result, dict) else {}


def _audit_metadata(value: object, key: str) -> str | None:
    item = _object(value).get(key)
    if key == "ok" and type(item) is bool:
        return "true" if item else "false"
    if key == "local_date" and isinstance(item, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item):
        try:
            return datetime.strptime(item, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return None


def _utc_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        pass
    return "unknown"


def _section_cell(section_id, key, value):
    if key.endswith("_utc"):
        return _utc_timestamp(value)
    if section_id == "listings" and key == "url":
        return value
    return _cell(value)


def _listing_url(value: object) -> str | None:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        if "\\" in value:
            return None
        if url.port == 0:
            return None
        return urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    except ValueError:
        return None


@contextmanager
def read_snapshot(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = None
    try:
        path = Path(db_path).resolve()
        if not path.is_file():
            raise DashboardUnavailable(UNAVAILABLE)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.create_function("expiry_epoch", 1, _epoch, deterministic=True)
        conn.execute("BEGIN")
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise DashboardUnavailable(UNAVAILABLE)
    except (OSError, ValueError, sqlite3.Error):
        if conn is not None:
            conn.close()
        raise DashboardUnavailable(UNAVAILABLE) from None
    except DashboardUnavailable:
        if conn is not None:
            conn.close()
        raise
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _section(conn, section_id, title, description, columns, sql, params=()):
    section = {
        "id": section_id,
        "title": title,
        "description": f"{description} Rows capped at {ROW_LIMIT}; total is the full matching count.",
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": [],
        "total": 0,
    }
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        rows = conn.execute(f"{sql} LIMIT ?", (*params, ROW_LIMIT)).fetchall()
        section["total"] = total
        section["rows"] = [
            {key: _section_cell(section_id, key, row[key]) for key, _ in columns}
            for row in rows
        ]
    except sqlite3.Error:
        section["error"] = SECTION_ERROR
    return section


def _scalar(conn, sql, params=()):
    try:
        return _cell(conn.execute(sql, params).fetchone()[0])
    except sqlite3.Error:
        return None


def _build_snapshot(conn: sqlite3.Connection, settings: Settings, now: datetime) -> dict:
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    date_range = ((today - timedelta(days=6)).isoformat(), today.isoformat())
    year = today.year
    now_epoch = now.timestamp()

    def freshness(source, fetched):
        if fetched is None:
            return "missing"
        stamp = _epoch(fetched)
        if stamp is None or stamp > now_epoch:
            return "unknown"
        if source == "cache-stale" or now_epoch - stamp > settings.spray_window.max_data_age_hours * 3600:
            return "stale"
        return "fresh"

    conn.create_function("weather_status", 2, freshness, deterministic=True)
    conn.create_function("audit_metadata", 2, _audit_metadata, deterministic=True)
    configured = " UNION ALL ".join("SELECT ? AS site" for _ in settings.sites)
    configured = configured or "SELECT NULL AS site WHERE 0"
    weather_sql = f"""
        WITH sites AS (
            {configured}
            UNION SELECT site FROM blocks WHERE active = 1
            UNION SELECT site FROM weather_cache
        )
        SELECT sites.site, w.source, w.fetched_at_utc,
               weather_status(w.source, w.fetched_at_utc) AS status
        FROM sites LEFT JOIN weather_cache w ON w.id = (
            SELECT id FROM weather_cache WHERE site = sites.site
            ORDER BY fetched_at_utc DESC, id DESC LIMIT 1
        ) ORDER BY sites.site
    """
    weather_params = tuple(site.key for site in settings.sites)
    weather = _section(conn, "weather", "Site weather",
        f"Latest saved cache per site; freshness limit {settings.spray_window.max_data_age_hours:g} hours. Cache freshness is not spray approval; saved verdicts are omitted.",
        [("site", "Site"), ("source", "Source"), ("fetched_at_utc", "Fetched (UTC)"), ("status", "Cache freshness")],
        weather_sql, weather_params)
    restrictions_sql = """
        SELECT s.id, b.code AS block, b.site, s.product_name_raw AS product,
               s.log_date, s.rei_expires_at_utc,
               CASE WHEN expiry_epoch(s.rei_expires_at_utc) IS NULL
                    THEN 'unknown expiry — verify before entry' ELSE 'active — no entry' END AS status
        FROM spray_log_current s LEFT JOIN blocks b ON b.id = s.block_id
        WHERE expiry_epoch(s.rei_expires_at_utc) IS NULL OR expiry_epoch(s.rei_expires_at_utc) > ?
        ORDER BY expiry_epoch(s.rei_expires_at_utc), s.id DESC
    """
    restrictions = _section(conn, "restrictions", "Re-entry restrictions",
        "Current corrected applications with future, missing or invalid expiry. Unknown expiry does not grant entry.",
        [("id", "Spray ID"), ("block", "Block"), ("site", "Site"), ("product", "Product"),
         ("log_date", "Application date"), ("rei_expires_at_utc", "Expiry (UTC)"), ("status", "Restriction")],
        restrictions_sql, (now_epoch,))
    blocks = _section(conn, "blocks", "Blocks", "Active block registry; no estimated acreage.",
        [("code", "Block"), ("name", "Name"), ("site", "Site"), ("acres", "Acres"),
         ("variety", "Variety"), ("row_count", "Rows")],
        "SELECT code, name, site, acres, variety, row_count FROM blocks WHERE active = 1 ORDER BY site, code")
    sprays = _section(conn, "sprays", "Spray records", "Latest corrected records, newest first. Recorded REI/PHI are historical application values, not new approvals.",
        [("id", "ID"), ("log_date", "Date"), ("start_time", "Start"), ("block", "Block"),
         ("product", "Product"), ("acres_treated", "Acres treated"), ("rate_value", "Rate"),
         ("rate_units", "Rate units"), ("rei_hours", "Recorded REI hours"), ("phi_days", "Recorded PHI days"),
         ("rei_expires_at_utc", "REI expiry (UTC)")],
        """SELECT s.id, s.log_date, s.start_time, b.code AS block, s.product_name_raw AS product,
                  s.acres_treated, s.rate_value, s.rate_units, s.rei_hours, s.phi_days, s.rei_expires_at_utc
           FROM spray_log_current s LEFT JOIN blocks b ON b.id = s.block_id
           ORDER BY s.log_date DESC, s.id DESC""")
    tasks = _section(conn, "tasks", "Task records", "Latest corrected tasks, newest first. Hours are recorded crew-hours, not individual hours.",
        [("id", "ID"), ("log_date", "Date"), ("task_type", "Task"), ("block", "Block"),
         ("hours_total", "Recorded crew-hours"), ("quantity", "Quantity"), ("quantity_unit", "Unit")],
        """SELECT t.id, t.log_date, t.task_type, b.code AS block, t.hours_total, t.quantity, t.quantity_unit
           FROM task_log_current t LEFT JOIN blocks b ON b.id = t.block_id
           ORDER BY t.log_date DESC, t.id DESC""")
    has_hours = any(row["name"] == "hours" for row in conn.execute("PRAGMA table_info(task_workers)"))
    hours = "tw.hours" if has_hours else "NULL"
    crew = _section(conn, "crew", "Crew", f"Active workers. Explicit individual hours only, {date_range[0]} through {date_range[1]} inclusive; partial totals exclude missing hours. Never apportioned from crew-hours.",
        [("id", "Worker ID"), ("name", "Name"), ("last_task", "Last task date"),
         ("assignments_7d", "Assignments (7 days)"), ("recorded_hours_7d", "Explicit hours (7 days)"),
         ("missing_hours_7d", "Assignments without hours (7 days)")],
        f"""SELECT c.id, c.full_name AS name,
                   (SELECT MAX(t.log_date) FROM task_log_current t JOIN task_workers tw ON tw.task_log_id = t.id
                    WHERE tw.contact_id = c.id) AS last_task,
                   COUNT(t.id) AS assignments_7d, SUM({hours}) AS recorded_hours_7d,
                   COUNT(t.id) - COUNT({hours}) AS missing_hours_7d
            FROM contacts c
            LEFT JOIN (task_workers tw JOIN task_log_current t ON t.id = tw.task_log_id AND t.log_date BETWEEN ? AND ?)
                ON tw.contact_id = c.id
            WHERE c.active = 1 AND c.role = 'worker' GROUP BY c.id ORDER BY c.full_name, c.id""",
        date_range)
    if not has_hours and "error" not in crew:
        crew["error"] = "Individual hours unavailable: this older schema has no task_workers.hours. No crew-hours have been apportioned."
    maturity = _section(conn, "maturity", "Fruit maturity", f"Season {year}: latest current sample through today, repeated for each winery contract. Active blocks without samples or contracts remain visible. Targets are recorded contract values, not projections.",
        [("block", "Block"), ("variety", "Variety"), ("winery", "Winery"), ("sampled_on", "Sample date"),
         ("brix", "Brix"), ("ta_g_l", "TA (g/L)"), ("ph", "pH"), ("sample_size", "Sample size"),
         ("target_brix_min", "Brix min"), ("target_brix_max", "Brix max"),
         ("target_ta_min", "TA min"), ("target_ta_max", "TA max"),
         ("target_ph_min", "pH min"), ("target_ph_max", "pH max"),
         ("harvest_window_from", "Contract window from"), ("harvest_window_to", "Contract window to")],
        """SELECT b.code AS block, b.variety, ft.winery, f.sampled_on, f.brix, f.ta_g_l, f.ph, f.sample_size,
                  ft.target_brix_min, ft.target_brix_max, ft.target_ta_min, ft.target_ta_max,
                  ft.target_ph_min, ft.target_ph_max, ft.harvest_window_from, ft.harvest_window_to
           FROM blocks b LEFT JOIN fruit_targets ft ON ft.block_id = b.id AND ft.season_year = ?
           LEFT JOIN fruit_samples_current f ON f.id = (
               SELECT id FROM fruit_samples_current WHERE block_id = b.id AND sampled_on BETWEEN ? AND ?
               ORDER BY sampled_on DESC, id DESC LIMIT 1)
           WHERE b.active = 1 ORDER BY b.code, ft.winery, ft.id""",
        (year, f"{year}-01-01", today.isoformat()))
    irrigation = _section(conn, "irrigation", "Irrigation", "Active-block equipment and latest corrected irrigation task. No water need or volume is inferred.",
        [("block", "Block"), ("soil_type", "Soil"), ("irrigation_type", "Equipment"),
         ("emitter_lph", "Emitter L/hour"), ("emitters_per_vine", "Emitters/vine"), ("vines_per_acre", "Vines/acre"),
         ("last_task", "Last irrigation date"), ("quantity", "Recorded quantity"), ("quantity_unit", "Unit"),
         ("hours_total", "Recorded crew-hours")],
        """SELECT b.code AS block, b.soil_type, b.irrigation_type, b.emitter_lph,
                  b.emitters_per_vine, b.vines_per_acre, t.log_date AS last_task,
                  t.quantity, t.quantity_unit, t.hours_total
           FROM blocks b LEFT JOIN task_log_current t ON t.id = (
               SELECT id FROM task_log_current WHERE block_id = b.id AND task_type = 'riego'
               ORDER BY log_date DESC, id DESC LIMIT 1)
           WHERE b.active = 1 ORDER BY b.code""")
    products = _section(conn, "products", "Products", "Registry verification status. Unverified label intervals are withheld; consult the physical label.",
        [("trade_name", "Product"), ("pcp_number", "PCP"), ("type", "Type"), ("status", "Verification"),
         ("rei_hours", "Verified REI hours"), ("phi_days", "Verified PHI days"), ("frac_group", "FRAC group")],
        """SELECT trade_name, pcp_number, type,
                  CASE WHEN verified = 1 THEN 'verified' ELSE 'unverified' END AS status,
                  CASE WHEN verified = 1 THEN rei_hours END AS rei_hours,
                  CASE WHEN verified = 1 THEN phi_days END AS phi_days, frac_group
           FROM products ORDER BY verified, trade_name""")
    drafts = _section(conn, "drafts", "Pending drafts", "Pending workflow metadata only; no messages, payloads, identities or confirmation tokens.",
        [("intent", "Intent"), ("state", "State"), ("target_table", "Record type"),
         ("created_at_utc", "Created (UTC)"), ("updated_at_utc", "Updated (UTC)")],
        f"SELECT intent, state, target_table, created_at_utc, updated_at_utc FROM drafts WHERE {PENDING} ORDER BY updated_at_utc DESC, created_at_utc DESC")
    conn.create_function("listing_url", 1, _listing_url, deterministic=True)
    listings = _section(conn, "listings", "Property listings", "Saved listings, newest first. Only HTTP(S) links without credentials; query strings and fragments are omitted.",
        [("id", "ID"), ("title", "Title"), ("price", "Price (CAD)"), ("acres", "Acres"),
         ("area", "Area"), ("source", "Source"), ("first_seen_utc", "First seen (UTC)"), ("url", "URL")],
        """SELECT id, title, price, acres, area, source, first_seen_utc, listing_url(url) AS url
           FROM listings ORDER BY first_seen_utc DESC, id DESC""")
    activity = _section(conn, "activity", "Recent job and agent activity", "Newest audit events. Only structured local-date and success flags are exposed; free-text summaries, raw detail, actors, observations and reasoning are omitted.",
        [("at_utc", "Time (UTC)"), ("action", "Event"),
         ("local_date", "Local date"), ("ok", "Succeeded")],
        f"""SELECT at_utc, action, audit_metadata(detail_json, 'local_date') AS local_date,
                   audit_metadata(detail_json, 'ok') AS ok
            FROM audit_log WHERE action IN {AUDIT_ACTIONS} ORDER BY at_utc DESC, id DESC""")
    packing = _section(conn, "packing", "Packing records", "Recorded packing quantities only, newest first; absent quantities remain unknown.",
        [("id", "ID"), ("log_date", "Date"), ("variety", "Variety"), ("medium", "Medium"),
         ("block", "Block"), ("quantity", "Quantity"), ("quantity_unit", "Unit")],
        """SELECT p.id, p.log_date, p.variety, p.medium, b.code AS block, p.quantity, p.quantity_unit
           FROM packing_log p LEFT JOIN blocks b ON b.id = p.block_id ORDER BY p.log_date DESC, p.id DESC""")
    sections = [weather, restrictions, blocks, sprays, tasks, crew, maturity, irrigation, products, drafts, listings, activity, packing]
    restriction_count = restrictions["total"] if "error" not in restrictions else None
    unverified = _scalar(conn, "SELECT COUNT(*) FROM products WHERE verified IS NOT 1")
    pending = drafts["total"] if "error" not in drafts else None
    metrics = [
        {"label": "Active blocks", "value": blocks["total"] if "error" not in blocks else None, "detail": "Active registry blocks"},
        {"label": "Active acres", "value": _scalar(conn, "SELECT SUM(acres) FROM blocks WHERE active = 1"), "detail": "Recorded acreage only"},
        {"label": "Active workers", "value": _scalar(conn, "SELECT COUNT(*) FROM contacts WHERE active = 1 AND role = 'worker'"), "detail": "Active crew roster"},
        {"label": "Re-entry restrictions", "value": restriction_count, "detail": "Current applications with active or unknown expiry", "tone": "danger" if restriction_count else "neutral"},
        {"label": "Unverified products", "value": unverified, "detail": "Registry labels awaiting verification", "tone": "warning" if unverified else "neutral"},
        {"label": "Pending drafts", "value": pending, "detail": "Collecting, ready or awaiting confirmation"},
        {"label": "Recorded crew-hours (7 days)", "value": _scalar(conn, "SELECT SUM(hours_total) FROM task_log_current WHERE log_date BETWEEN ? AND ?", date_range),
         "detail": f"{date_range[0]} through {date_range[1]}; recorded totals only, missing hours excluded; not individual payroll"},
    ]
    alerts = []
    if restriction_count:
        alerts.append({"title": "Re-entry restrictions require attention", "detail": f"{restriction_count} current applications have active or unresolved expiry. Verify restrictions before entry.", "tone": "danger"})
    if unverified:
        alerts.append({"title": "Unverified product labels", "detail": f"{unverified} products need physical-label verification. No label approval is inferred.", "tone": "warning"})
    weather_gaps = _scalar(conn, f"SELECT COUNT(*) FROM ({weather_sql}) WHERE status != 'fresh'", weather_params)
    if weather_gaps:
        alerts.append({"title": "Weather is missing, stale or uncertain", "detail": f"{weather_gaps} sites lack a fresh saved cache. This dashboard does not approve spraying.", "tone": "warning"})
    for section in sections:
        if "error" in section:
            alerts.append({"title": f"{section['title']} unavailable or incomplete", "detail": section["error"], "tone": "danger" if section["id"] == "restrictions" else "warning"})
    if any(metric["value"] is None for metric in metrics):
        alerts.append({"title": "Some metrics are unavailable", "detail": "Missing measurements or unsupported schema are shown as unknown, not zero.", "tone": "neutral"})
    return {"generated_at": now.isoformat().replace("+00:00", "Z"), "timezone": settings.timezone,
            "metrics": metrics, "alerts": alerts, "sections": sections}


def build_dashboard(db_path: Path | str | None = None, *, settings: Settings | None = None, now: datetime | None = None) -> dict:
    settings = settings or get_settings()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    with read_snapshot(db_path if db_path is not None else settings.db_path) as conn:
        try:
            return _build_snapshot(conn, settings, now)
        except sqlite3.Error:
            raise DashboardUnavailable(UNAVAILABLE) from None


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "VineyardDashboard"
    sys_version = ""

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self._send(code, json.dumps({"error": "Request rejected."}).encode())

    def _local_request(self):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            return False
        origin = f"http://{hosts[0].lower()}"
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0].lower() != origin):
            return False
        sites = self.headers.get_all("Sec-Fetch-Site", [])
        if sites and (len(sites) != 1 or sites[0] not in {"same-origin", "none"}):
            return False
        referers = self.headers.get_all("Referer", [])
        if referers:
            if len(referers) != 1:
                return False
            try:
                parsed = urlsplit(referers[0])
                if parsed.scheme != "http" or f"http://{parsed.netloc.lower()}" != origin:
                    return False
            except ValueError:
                return False
        return True

    def do_GET(self):
        if not self._local_request():
            self.send_error(403)
            return
        if self.requestline.split()[1] != self.path:
            self.send_error(404)
            return
        if self.path == "/api/dashboard":
            try:
                data = build_dashboard(self.server.db_path, settings=self.server.settings)
                body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except DashboardUnavailable:
                self._send(503, json.dumps({"error": UNAVAILABLE}).encode())
                return
            self._send(200, body)
        elif self.path in ASSETS:
            name, content_type = ASSETS[self.path]
            try:
                body = Path(__file__).with_name(name).read_bytes()
            except OSError:
                self._send(404, b'{"error":"Dashboard asset unavailable."}')
                return
            self._send(200, body, content_type)
        else:
            self.send_error(404)

    def do_HEAD(self):
        self.do_GET()


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 8765, db_path: Path | str | None = None, *, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db_path = db_path if db_path is not None else self.settings.db_path
        super().__init__(("127.0.0.1", port), DashboardHandler)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        return sock, address


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local read-only vineyard dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        with DashboardServer(args.port, args.db) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError):
        parser.exit(1, "Dashboard could not start. Check local port availability and configuration.\n")


if __name__ == "__main__":
    main()
