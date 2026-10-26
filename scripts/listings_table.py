r"""listings_table — the running table of every listing shown to the owners, as a CSV and a daily
WhatsApp message.

    python scripts/listings_table.py              # sync the CSV, print the daily message
    python scripts/listings_table.py --sync-only  # sync the CSV, print nothing

The `listings` table (filled by listings_poll) is the source of truth; data/listings_shown.csv is
its owner-facing copy, one row per listing, with how long each has been on the market. Every row
in `listings` was shown to the owners, as an interrupt or in the digest, so the CSV is also the
record of what they have already seen.

**Days listed comes from the alert, not from REALTOR.ca.** The saved searches send "instant
updates", so the first alert for a listing arrives within hours of it going live; REALTOR.ca's
own "Time on REALTOR.ca" agreed to within a day when checked on 2026-10-26. Scraping the site for
it is off the table (CREA terms; see the listings-triage skill). `listed_on` is written once and
never overwritten, so a date corrected by hand in the CSV holds. Sold or expired listings are not
detected: their count keeps running.

The emit_listings_table_<owner> cron jobs run this once a day, one per owner. The output depends
only on the CSV and the clock (new additions are the rows first shown in the last 24 hours), so
the four jobs send the same message without sharing any state.

Stdlib only: it runs under the system python3 from a --no-agent cron job.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import os
import re
import sqlite3
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(REPO, "data", "hermes.db")
CSV_PATH = os.environ.get("LISTINGS_CSV") or os.path.join(REPO, "data", "listings_shown.csv")

FIELDS = ["mls", "address", "area", "price", "acres", "listed_on", "days_listed",
          "first_shown_utc", "url", "dedupe_key"]
NEW_WINDOW = timedelta(hours=24)
MAX_ROWS = 40             # a WhatsApp message, not the whole CSV; the CSV keeps everything


def local_date(utc_iso: str) -> date:
    """The owners' calendar day for a UTC timestamp (the host runs on Pacific time)."""
    return datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).astimezone().date()


def read_csv(path: str = CSV_PATH) -> dict[str, dict]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return {row["dedupe_key"]: row for row in csv.DictReader(fh)}
    except FileNotFoundError:
        return {}


def write_csv(rows: dict[str, dict], path: str = CSV_PATH) -> None:
    """Atomic: the four owner jobs fire in the same minute and must never read half a file."""
    ordered = sorted(rows.values(), key=lambda r: r["first_shown_utc"], reverse=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".csv.tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(ordered)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def db_listings(db_path: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT dedupe_key, mls_number, title, address, area, price, acres, url, "
            "first_seen_utc FROM listings")]
    finally:
        conn.close()


def sync(rows: dict[str, dict], listings: list[dict], today: date) -> dict[str, dict]:
    """Add listings the CSV lacks, fill blanks, refresh days_listed. Never moves listed_on."""
    for item in listings:
        row = rows.get(item["dedupe_key"])
        if row is None:
            row = rows[item["dedupe_key"]] = {
                "dedupe_key": item["dedupe_key"],
                "first_shown_utc": item["first_seen_utc"],
                "listed_on": local_date(item["first_seen_utc"]).isoformat(),
            }
        for field, value in (("mls", item["mls_number"]),
                             ("address", item["address"] or item["title"]),
                             ("area", item["area"]), ("price", item["price"]),
                             ("acres", item["acres"]), ("url", item["url"])):
            if not row.get(field) and value is not None:
                row[field] = f"{value:.0f}" if field == "price" else value
    for row in rows.values():
        row["days_listed"] = (today - date.fromisoformat(row["listed_on"])).days
    return rows


# ----------------------------------------------------------------------------- message
def short_price(value) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"${price / 1e6:.1f}M" if price >= 1e6 else f"${price / 1e3:.0f}K"


def short_address(row: dict) -> str:
    """'000 398 Upper Bench Road S Penticton, British Columbia V' -> '398 Upper Bench Road S'."""
    text = re.sub(r",?\s*(British Columbia|B\.?C\.?)\b.*$", "", row.get("address") or "")
    text = re.sub(r"^0+\s+", "", text.strip().rstrip(","))
    area = row.get("area") or ""
    if area and text.lower().endswith(area.lower()):
        text = text[: -len(area)].rstrip(" ,")
    return text or (f"MLS {row['mls']}" if row.get("mls") else "(no address)")


_STREET = {"road": "Rd", "drive": "Dr", "street": "St", "avenue": "Ave", "place": "Pl",
           "crescent": "Cres", "lane": "Ln", "highway": "Hwy", "court": "Ct"}


def table_address(row: dict) -> str:
    """short_address squeezed for a phone-width monospace line."""
    words = [_STREET.get(w.lower(), w if not w.isupper() else w.title())
             for w in short_address(row).split()]
    return " ".join(words)[:20]


def one_per_property(rows: list[dict]) -> list[dict]:
    """A property listed twice (house and farm, two MLS numbers) is one line in the message."""
    seen: set[str] = set()
    out = []
    for r in rows:
        key = short_address(r).lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def render(rows: dict[str, dict], now: datetime) -> str:
    if not rows:
        return ""
    ordered = one_per_property(sorted(rows.values(), key=lambda r: int(r["days_listed"])))
    new = [r for r in ordered if now - datetime.fromisoformat(
        r["first_shown_utc"].replace("Z", "+00:00")) <= NEW_WINDOW]

    lines = [f"🏡 Listings table — {now.astimezone():%a %d %b}", ""]
    if new:
        lines.append(f"New additions ({len(new)}):")
        for r in new:
            line = f"• {short_address(r)}"
            if r.get("area"):
                line += f", {r['area']}"
            line += f" — {short_price(r.get('price'))}"
            if r.get("acres"):
                line += f", {float(r['acres']):g} ac"
            lines.append(line + f" — listed {r['days_listed']} d")
            lines.append(f"  {r['url']}" if r.get("url") else f"  MLS {r.get('mls') or 'n/a'}")
    else:
        lines.append("New additions: none in the last 24 hours.")

    shown = ordered[:MAX_ROWS]
    lines += ["", f"All properties shown ({len(ordered)}), by days listed:", "```"]
    lines += [f"{'Days':>4} {'Price':>5} {'Area':<9} Address"]
    for r in shown:
        area = (r.get("area") or "").replace("Okanagan Falls", "OK Falls")[:9]
        lines.append(f"{r['days_listed']:>4} {short_price(r.get('price')):>5} {area:<9} "
                     f"{table_address(r)}")
    lines.append("```")
    if len(ordered) > len(shown):
        lines.append(f"+{len(ordered) - len(shown)} older in data/listings_shown.csv")
    lines.append("Days = since the first listing alert. Sold listings are not detected.")
    return "\n".join(lines)


def main() -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sync-only", action="store_true")
    args = parser.parse_args()

    now = datetime.now(UTC)
    rows = sync(read_csv(), db_listings(), now.astimezone().date())
    write_csv(rows)
    if not args.sync_only:
        print(render(rows, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
