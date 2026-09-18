from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path

import pytest

from vineyard_mcp import dashboard
from vineyard_mcp.config import get_settings

NOW = datetime(2026, 9, 17, 18, tzinfo=UTC)


def snapshot():
    return dashboard.build_dashboard(now=NOW)


def section(data, key):
    return next(item for item in data["sections"] if item["id"] == key)


def metric(data, label):
    return next(item["value"] for item in data["metrics"] if item["label"] == label)


def spray(db, expiry=None, corrects=None):
    return db.execute(
        """INSERT INTO spray_log
           (log_date, start_time, block_id, product_name_raw, raw_message, acres_treated,
            applicator_contact_id, applicator_name, rei_expires_at_utc, corrects_log_id)
           VALUES ('2026-09-16', '06:00', 1, 'Sulfur', 'PRIVATE RAW SPRAY', 1, 1, 'Worker', ?, ?)""",
        (expiry, corrects),
    ).lastrowid


def task(db, hours=8, corrects=None, day="2026-09-16", kind="riego"):
    return db.execute(
        """INSERT INTO task_log (log_date, task_type, block_id, hours_total, raw_message, corrects_log_id)
           VALUES (?, ?, 1, ?, 'PRIVATE RAW TASK', ?)""", (day, kind, hours, corrects),
    ).lastrowid


def test_missing_database_never_created(tmp_path):
    path = tmp_path / "absent" / "secret.db"
    with pytest.raises(dashboard.DashboardUnavailable, match="existing vineyard database") as error:
        dashboard.build_dashboard(path)
    assert not path.exists()
    assert not path.parent.exists()
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize("contents", [b"", b"not a sqlite database"])
def test_unusable_database_is_unavailable(tmp_path, contents):
    path = tmp_path / "invalid.db"
    path.write_bytes(contents)
    with pytest.raises(dashboard.DashboardUnavailable):
        dashboard.build_dashboard(path)
    assert path.read_bytes() == contents


def test_read_only_connection_and_snapshot_do_not_change_database(db):
    path = get_settings().db_path
    before = list(db.iterdump())
    with dashboard.read_snapshot(path) as conn:
        assert conn.in_transaction
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO blocks (code, name, site, acres) VALUES ('X', 'X', 'oliver', 1)")
        conn.execute("PRAGMA query_only = OFF")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE unwanted (id INTEGER)")
    snapshot()
    assert list(db.iterdump()) == before


def test_one_read_transaction_keeps_counts_and_rows_consistent(db, monkeypatch):
    original = dashboard._section
    writes = []

    def concurrent_write(conn, *args, **kwargs):
        assert conn.in_transaction
        if not writes:
            db.execute("INSERT INTO blocks (code, name, site, acres) VALUES ('NEW', 'New', 'oliver', 1)")
            writes.append(True)
        return original(conn, *args, **kwargs)

    monkeypatch.setattr(dashboard, "_section", concurrent_write)
    data = snapshot()
    assert writes
    assert section(data, "blocks")["total"] == 3
    assert metric(data, "Active blocks") == 3
    assert db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 4


def test_empty_records_keep_missing_measurements_unknown(db):
    data = snapshot()
    assert data["generated_at"] == "2026-09-17T18:00:00Z"
    assert data["timezone"] == "America/Vancouver"
    assert metric(data, "Active blocks") == 3
    assert metric(data, "Active acres") == pytest.approx(12.8)
    assert metric(data, "Re-entry restrictions") == 0
    assert metric(data, "Recorded crew-hours (7 days)") is None
    assert section(data, "sprays")["total"] == 0
    assert all(row["recorded_hours_7d"] is None for row in section(data, "crew")["rows"])
    assert all(row["brix"] is None for row in section(data, "maturity")["rows"])
    assert all(row["last_task"] is None and row["emitter_lph"] is None
               for row in section(data, "irrigation")["rows"])
    assert all(row["status"] == "missing" and row["source"] is None
               for row in section(data, "weather")["rows"])
    assert any("Weather" in alert["title"] for alert in data["alerts"])
    product = next(row for row in section(data, "products")["rows"] if row["status"] == "unverified")
    assert product["rei_hours"] is None
    assert product["phi_days"] is None
    json.dumps(data, allow_nan=False)
    assert {s["id"] for s in data["sections"]} == {
        "weather", "restrictions", "blocks", "sprays", "tasks", "crew", "maturity",
        "irrigation", "products", "drafts", "listings", "activity", "packing",
    }
    for item in data["sections"]:
        assert "error" not in item
        assert "capped at 200" in item["description"]
        assert item["total"] == len(item["rows"])
        for row in item["rows"]:
            assert set(row) == {column["key"] for column in item["columns"]}
            assert all(value is None or type(value) in (str, int, float) for value in row.values())


def test_unknown_invalid_and_future_rei_and_corrected_views(db):
    db.execute("DROP VIEW rei_active")
    db.execute("CREATE VIEW rei_active AS SELECT * FROM spray_log_current WHERE 0")
    unknown = spray(db)
    invalid = [spray(db, value) for value in ["broken", "", "2026-09-17T20:00:00", "2026-02-30T00:00:00Z"]]
    future = spray(db, "2026-09-17T12:00:00-07:00")
    expired = spray(db, "2026-09-17T18:00:00Z")
    superseded = spray(db)
    corrected = spray(db, "2026-09-16T00:00:00Z", superseded)
    data = snapshot()
    rows = section(data, "restrictions")["rows"]
    assert {row["id"] for row in rows} == {unknown, future, *invalid}
    assert all("unknown" in row["status"] for row in rows if row["id"] != future)
    assert metric(data, "Re-entry restrictions") == 6
    assert {row["id"] for row in section(data, "sprays")["rows"]} == {unknown, future, expired, corrected, *invalid}
    assert any(alert["tone"] == "danger" for alert in data["alerts"])


def test_current_tasks_explicit_worker_hours_and_irrigation(db):
    old = task(db, 50)
    db.execute("INSERT INTO task_workers VALUES (?, 1, 20)", (old,))
    current = task(db, 9, old)
    db.execute("INSERT INTO task_workers VALUES (?, 1, 3)", (current,))
    db.execute("INSERT INTO task_workers VALUES (?, 2, NULL)", (current,))
    task(db, 100, day="2026-09-10", kind="poda")
    task(db, 100, day="2026-09-18", kind="poda")
    task(db, 2, day="2026-09-11", kind="poda")
    db.execute("UPDATE blocks SET irrigation_type='drip', emitter_lph=2 WHERE id=1")
    data = snapshot()
    assert metric(data, "Recorded crew-hours (7 days)") == 11
    assert old not in {row["id"] for row in section(data, "tasks")["rows"]}
    crew = {row["id"]: row for row in section(data, "crew")["rows"]}
    assert crew[1]["recorded_hours_7d"] == 3
    assert crew[2]["recorded_hours_7d"] is None
    assert crew[2]["missing_hours_7d"] == 1
    assert crew[3]["assignments_7d"] == 0
    irrigation = section(data, "irrigation")["rows"][0]
    assert irrigation["last_task"] == "2026-09-16"
    assert irrigation["hours_total"] == 9
    assert irrigation["emitter_lph"] == 2
    assert irrigation["quantity"] is None


def test_actual_older_schema_degrades_without_migration(db):
    row_id = task(db)
    db.execute("DROP TABLE packing_log")
    db.execute("DROP TABLE task_workers")
    db.execute("CREATE TABLE task_workers (task_log_id INTEGER, contact_id INTEGER, PRIMARY KEY(task_log_id, contact_id))")
    db.execute("INSERT INTO task_workers VALUES (?, 1)", (row_id,))
    db.execute("DELETE FROM schema_version")
    db.execute("INSERT INTO schema_version(version) VALUES (5)")
    before = list(db.iterdump())
    data = snapshot()
    assert "error" in section(data, "packing")
    crew = section(data, "crew")
    assert "task_workers.hours" in crew["error"]
    assert crew["total"] == 3
    assert crew["rows"][0]["recorded_hours_7d"] is None
    assert metric(data, "Recorded crew-hours (7 days)") == 8
    assert "error" not in section(data, "tasks")
    assert "error" not in section(data, "maturity")
    assert list(db.iterdump()) == before


def test_section_failure_is_not_a_zero_safety_metric(db):
    db.execute("DROP VIEW spray_log_current")
    data = snapshot()
    assert "error" in section(data, "restrictions")
    assert metric(data, "Re-entry restrictions") is None
    assert "error" not in section(data, "blocks")
    assert any(alert["tone"] == "danger" and "unavailable" in alert["title"]
               for alert in data["alerts"])


def test_readonly_uri_escapes_database_filename(db, tmp_path):
    path = tmp_path / "vineyard #1.db"
    with sqlite3.connect(path) as destination:
        db.backup(destination)
    assert dashboard.build_dashboard(path, now=NOW)["sections"]


def test_latest_current_season_maturity_has_multiple_contract_rows(db):
    db.execute("INSERT INTO fruit_samples (id, block_id, sampled_on, brix) VALUES (1, 1, '2026-09-16', 9)")
    db.execute("INSERT INTO fruit_samples (block_id, sampled_on, brix, corrects_sample_id) VALUES (1, '2026-09-16', 22, 1)")
    db.execute("INSERT INTO fruit_samples (block_id, sampled_on, brix) VALUES (1, '2026-09-15', 20)")
    db.execute("INSERT INTO fruit_samples (block_id, sampled_on, brix) VALUES (1, '2026-09-18', 25)")
    db.execute("INSERT INTO fruit_samples (block_id, sampled_on, brix) VALUES (2, '2025-09-16', 24)")
    db.executemany("INSERT INTO fruit_targets (block_id, season_year, winery, target_brix_min) VALUES (1, 2026, ?, ?)", [("Winery A", 21), ("Winery B", 23)])
    db.execute("INSERT INTO fruit_targets (block_id, season_year, winery) VALUES (1, 2025, 'Old winery')")
    rows = section(snapshot(), "maturity")["rows"]
    assert len(rows) == 4
    b1 = [row for row in rows if row["block"] == "B1"]
    assert {row["winery"] for row in b1} == {"Winery A", "Winery B"}
    assert all(row["brix"] == 22 and row["sampled_on"] == "2026-09-16" for row in b1)
    assert next(row for row in rows if row["block"] == "B3")["brix"] is None


@pytest.mark.parametrize("fetched,source,status", [
    ("2026-09-17T17:00:00Z", "eccc", "fresh"),
    ("2026-09-17T16:00:00Z", "eccc", "fresh"),
    ("2026-09-17T15:59:59Z", "eccc", "stale"),
    ("2026-09-17T17:00:00Z", "cache-stale", "stale"),
    ("nonsense", "eccc", "unknown"),
    ("2026-09-17T19:00:00Z", "eccc", "unknown"),
])
def test_weather_freshness_uses_settings_and_never_replays_approval(db, fetched, source, status):
    settings = get_settings().model_copy(deep=True)
    settings.spray_window.max_data_age_hours = 2
    db.execute("INSERT INTO weather_cache (site, source, fetched_at_utc, payload_json, verdict_json) VALUES ('penticton', ?, ?, ?, ?)",
               (source, fetched, '{"secret": "PRIVATE WEATHER"}', '{"verdict":"YES"}'))
    data = dashboard.build_dashboard(settings=settings, now=NOW)
    weather = section(data, "weather")
    row = next(row for row in weather["rows"] if row["site"] == "penticton")
    expected_fetched = "unknown" if fetched == "nonsense" else fetched
    assert row == {"site": "penticton", "source": source, "fetched_at_utc": expected_fetched, "status": status}
    assert {site.key for site in settings.sites} <= {row["site"] for row in weather["rows"]}
    assert "YES" not in json.dumps(data)
    assert "PRIVATE WEATHER" not in json.dumps(data)


def test_latest_weather_row_uses_timestamp_then_id(db):
    for source, stamp in [("old", "2026-09-16T18:00:00Z"), ("eccc", "2026-09-17T17:00:00Z"), ("open-meteo", "2026-09-17T17:00:00Z")]:
        db.execute("INSERT INTO weather_cache (site,source,fetched_at_utc,payload_json) VALUES ('penticton',?,?, '{}')", (source, stamp))
    assert section(snapshot(), "weather")["rows"][-1]["source"] == "open-meteo"


def test_global_totals_and_alerts_are_not_capped(db):
    for _ in range(205):
        spray(db)
    data = snapshot()
    restrictions = section(data, "restrictions")
    assert len(restrictions["rows"]) == 200
    assert restrictions["total"] == 205
    assert section(data, "sprays")["total"] == 205
    assert metric(data, "Re-entry restrictions") == 205
    assert any("205" in alert["detail"] for alert in data["alerts"])


def test_allowlisted_activity_drafts_and_packing_omit_private_fields(db):
    db.execute("""INSERT INTO drafts (confirm_token,wa_phone,intent,draft_json,missing_fields,worker_reply,created_at_utc,updated_at_utc)
                  VALUES ('PRIVATE TOKEN','+15215550001','task_report','PRIVATE PAYLOAD','PRIVATE FIELDS','PRIVATE REPLY','2026-09-17T10:00:00Z','2026-09-17T11:00:00Z')""")
    db.execute("INSERT INTO packing_log (log_date,variety,medium,raw_message) VALUES ('2026-09-17','Pinot Noir','olive oil','PRIVATE PACKING')")
    details = [
        ("job.finished", {"summary": "Daily report delivered", "ok": True, "local_date": "2026-09-17", "raw_message": "PRIVATE AUDIT", "confirm_token": "PRIVATE TOKEN"}),
        ("agent.decision", {"decided": "Wait for label verification", "observed": "PRIVATE OBSERVATION", "reasoning": "PRIVATE REASONING"}),
        ("job.skipped", {"reason": "Already completed today"}),
        ("job.failed", {"summary": "phone +15215550001 api_key=PRIVATEKEY path C:\\private\\db.sqlite"}),
    ]
    for action, detail in details:
        db.execute("INSERT INTO audit_log (actor,action,entity,detail_json) VALUES ('+15215550001',?,'daily_brief',?)", (action, json.dumps(detail)))
    for detail in ["not JSON PRIVATE", "[]", '{"summary":{"raw":"PRIVATE"}}']:
        db.execute("INSERT INTO audit_log (actor,action,detail_json) VALUES ('hermes','job.failed',?)", (detail,))
    db.execute("INSERT INTO audit_log (actor,action,detail_json) VALUES ('hermes','contact.changed','PRIVATE')")
    data = snapshot()
    text = json.dumps(data)
    assert "PRIVATE" not in text
    assert "+15215550001" not in text
    assert "confirm_token" not in text
    assert "raw_message" not in text
    assert "Daily report delivered" not in text
    assert "Wait for label verification" not in text
    assert "Already completed today" not in text
    activity = section(data, "activity")
    finished = next(row for row in activity["rows"] if row["action"] == "job.finished")
    assert finished["local_date"] == "2026-09-17"
    assert finished["ok"] == "true"
    assert all(set(row) == {"at_utc", "action", "local_date", "ok"} for row in activity["rows"])
    assert section(data, "activity")["total"] == 7
    assert metric(data, "Pending drafts") == 1
    assert section(data, "packing")["rows"][0]["quantity"] is None


@pytest.mark.parametrize("detail,expected_date,expected_ok", [
    ({"local_date": "2026-09-17", "ok": True}, "2026-09-17", "true"),
    ({"local_date": "2026-09-17", "ok": False}, "2026-09-17", "false"),
    ({"local_date": "2026-02-30", "ok": 1}, None, None),
    ({"local_date": "2026-9-17", "ok": 0}, None, None),
    ({"local_date": "DUMMY_NOT_A_REAL_KEY", "ok": "true"}, None, None),
    ({"local_date": {"secret": "DUMMY_NOT_A_REAL_KEY"}, "ok": []}, None, None),
    ({"local_date": 20260917, "ok": "DUMMY_NOT_A_REAL_KEY"}, None, None),
])
def test_audit_exposes_only_validated_metadata(db, detail, expected_date, expected_ok):
    secret_text = '\"api_key\": \"DUMMY_NOT_A_REAL_KEY\", \"secret\": \"DUMMY SECRET WITH SPACES\"'
    detail.update(dict.fromkeys(("summary", "reason", "decided", "observed", "reasoning"), secret_text))
    db.execute("INSERT INTO audit_log (actor,action,entity,detail_json) VALUES (?, 'job.finished', ?, ?)",
               (secret_text, secret_text, json.dumps(detail)))
    data = snapshot()
    row = section(data, "activity")["rows"][0]
    assert row["local_date"] == expected_date
    assert row["ok"] == expected_ok
    assert set(row) == {"at_utc", "action", "local_date", "ok"}
    assert "DUMMY" not in json.dumps(data)
    assert "api_key" not in json.dumps(data)


@pytest.mark.parametrize("stamp,expected", [
    ("2026-09-17 19:00:00+00:00", "2026-09-17T19:00:00Z"),
    ("2026-09-17T12:00:00.123456-07:00", "2026-09-17T19:00:00.123456Z"),
    ("2026-09-17 12:00:00.123456-07:00", "2026-09-17T19:00:00.123456Z"),
    ("2026-09-18T01:00:00+06:00", "2026-09-17T19:00:00Z"),
    ("2026-09-17T19:00:00Z", "2026-09-17T19:00:00Z"),
    ("2026-09-17 19:00:00", "unknown"),
    ("2026-02-30T19:00:00Z", "unknown"),
    ('invalid timestamp \"api_key\": \"DUMMY_NOT_A_REAL_KEY\"', "unknown"),
])
def test_utc_columns_preserve_and_normalize_timestamps(db, stamp, expected):
    spray(db, stamp)
    db.execute("INSERT INTO weather_cache (site,source,fetched_at_utc,payload_json) VALUES ('penticton','eccc',?,'{}')", (stamp,))
    db.execute("""INSERT INTO drafts (confirm_token,wa_phone,intent,draft_json,created_at_utc,updated_at_utc)
                  VALUES ('private-token','+15215550001','task_report','{}',?,?)""", (stamp, stamp))
    db.execute("INSERT INTO listings (dedupe_key,source,first_seen_utc) VALUES ('listing','mls-email',?)", (stamp,))
    db.execute("INSERT INTO audit_log (actor,action,at_utc) VALUES ('hermes','job.started',?)", (stamp,))
    data = snapshot()
    for section_id, keys in [
        ("restrictions", ["rei_expires_at_utc"]), ("sprays", ["rei_expires_at_utc"]),
        ("weather", ["fetched_at_utc"]), ("drafts", ["created_at_utc", "updated_at_utc"]),
        ("listings", ["first_seen_utc"]), ("activity", ["at_utc"]),
    ]:
        rows = section(data, section_id)["rows"]
        row = next(row for row in rows if row["site"] == "penticton") if section_id == "weather" else rows[0]
        for key in keys:
            assert row[key] == expected, (section_id, key, row[key])
    assert "DUMMY" not in json.dumps(data)
    assert "[redacted phone]" not in json.dumps(data)


@pytest.mark.parametrize("url,expected", [
    ("https://example.test/listing/1?token=private#private", "https://example.test/listing/1"),
    ("http://example.test/listing/2", "http://example.test/listing/2"),
    ("javascript:alert(1)", None), ("file:///private", None), ("//example.test", None),
    ("https://user:secret@example.test/", None), ("https://", None),
    ("https://example.test:bad/", None), ("https://example.test/\nprivate", None),
])
def test_listing_links_are_http_only(db, url, expected):
    db.execute("INSERT INTO listings (dedupe_key,source,url,first_seen_utc) VALUES ('listing','mls-email',?,'2026-09-17T12:00:00Z')", (url,))
    assert section(snapshot(), "listings")["rows"][0]["url"] == expected


@pytest.fixture()
def http_server(db):
    server = dashboard.DashboardServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(server, path="/api/dashboard", headers=None, method="GET"):
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_http_endpoint_contract_and_security_headers(http_server):
    assert http_server.server_address[0] == "127.0.0.1"
    status, headers, body = request(http_server)
    assert status == 200
    data = json.loads(body)
    assert set(data) == {"generated_at", "timezone", "metrics", "alerts", "sections"}
    assert datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == dashboard.CSP
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
    assert not any(key.lower().startswith("access-control-") for key in headers)
    assert request(http_server, method="HEAD")[2] == b""


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"}, {"Host": "127.0.0.1.evil.example"},
    {"Host": "0.0.0.0"}, {"Host": "localhost@evil.example"}, {"Host": ""},
    {"Host": "localhost:1"}, {"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
    {"Referer": "https://evil.example/"},
])
def test_http_rejects_nonlocal_hosts_and_cross_origin(http_server, headers):
    status, response_headers, _ = request(http_server, headers=headers)
    assert status == 403
    assert response_headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" in response_headers


def test_http_accepts_only_matching_origin_and_localhost_port(http_server):
    host = f"localhost:{http_server.server_port}"
    assert request(http_server, headers={"Host": host, "Origin": f"http://{host}", "Referer": f"http://{host}/", "Sec-Fetch-Site": "same-origin"})[0] == 200
    assert request(http_server, headers={"Origin": f"http://{host}"})[0] == 403


def test_duplicate_host_and_origin_are_rejected(http_server):
    for extra_header in ["Host", "Origin"]:
        conn = HTTPConnection("127.0.0.1", http_server.server_port, timeout=5)
        try:
            conn.putrequest("GET", "/api/dashboard")
            value = f"127.0.0.1:{http_server.server_port}"
            if extra_header == "Origin":
                value = "http://" + value
                conn.putheader(extra_header, value)
            conn.putheader(extra_header, value)
            conn.endheaders()
            response = conn.getresponse()
            assert response.status == 403
            response.read()
        finally:
            conn.close()


@pytest.mark.parametrize("path", ["/schema.sql", "/../schema.sql", "/%2e%2e/schema.sql", "/vineyard_mcp/", "/dashboard.html", "/dashboard.js/", "//", "//api/dashboard", "/api/dashboard?site=oliver", "/?x=1", "http://evil.example/api/dashboard"])
def test_only_exact_routes_are_served(http_server, path):
    assert request(http_server, path, headers={"Host": f"127.0.0.1:{http_server.server_port}"})[0] == 404


def test_exact_assets_without_editing_frontend(http_server, monkeypatch):
    original = Path.read_bytes
    visited = []

    def asset_bytes(path):
        if path.name in {asset[0] for asset in dashboard.ASSETS.values()}:
            visited.append(path)
            return b"frontend fixture"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", asset_bytes)
    for route, (name, mime) in dashboard.ASSETS.items():
        status, headers, body = request(http_server, route)
        assert status == 200
        assert headers["Content-Type"] == mime
        assert body == b"frontend fixture"
        assert visited[-1] == Path(dashboard.__file__).with_name(name)


def test_missing_asset_is_sanitized(http_server, monkeypatch):
    def missing(path):
        raise FileNotFoundError("PRIVATE PATH")

    monkeypatch.setattr(Path, "read_bytes", missing)
    status, _, body = request(http_server, "/")
    assert status == 404
    assert b"PRIVATE" not in body


def test_http_missing_database_503_and_no_creation(http_server, tmp_path):
    path = tmp_path / "private-missing.db"
    http_server.db_path = path
    status, headers, body = request(http_server)
    assert status == 503
    assert "existing vineyard database" in json.loads(body)["error"]
    assert b"private-missing" not in body
    assert headers["Cache-Control"] == "no-store"
    assert not path.exists()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
def test_http_never_accepts_writes(http_server, method):
    status, headers, body = request(http_server, method=method)
    assert status == 501
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body)["error"] == "Request rejected."


def test_cli_defaults_and_database_override(monkeypatch):
    calls = []

    class Server:
        def __init__(self, port, db):
            calls.append((port, db))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def serve_forever(self):
            pass

    monkeypatch.setattr(dashboard, "DashboardServer", Server)
    dashboard.main([])
    dashboard.main(["--port", "9000", "--db", "existing.db"])
    assert calls == [(8765, None), (9000, Path("existing.db"))]
    with pytest.raises(SystemExit):
        dashboard.main(["--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        dashboard.main(["--port", "0"])
