r"""listings_triage — full pipeline for the listings_poll cron job.

Reads the dedicated listings inbox over IMAP (terminal python; execute_code is blocked in cron),
parses REALTOR.ca / Zealty alert emails, dedupes against the cron notepad `seen_keys`, classifies
each new survivor as INTERRUPT (tell owner now) or DIGEST (EOD report), writes survivors to the
local kernel DB, and updates the notepad. Read-only against IMAP (BODY.PEEK[] on a read-only
SELECT — never marks \Seen).

Deliverable contract: print a JSON to stdout with a "verdict" of "SILENT" or "REPORT" and the
owner-facing "report_text". The cron run's final assistant message is built from that.

Two things here are easy to get wrong and were:

1. **One alert email is not one listing.** REALTOR.ca and Zealty bundle several per message.
   Parsing the whole body as a single record splices field values across listings (MLS from the
   first, area from the last) and silently drops every listing but one. The body is segmented on
   MLS numbers and each segment is parsed on its own.
2. **Half these fields are routinely absent.** A missing price is normal, not exceptional, so
   every price render goes through `money()`. Formatting None with `:,` raises TypeError and
   takes the whole cron run down with it.

The hunt filter lives in config/settings.yaml, not here — the owner tunes it without touching
code, which is the only reason it is tunable at all.
"""

from __future__ import annotations

import contextlib
import email
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr

from imapclient import IMAPClient

# The cron job this script belongs to. setup-jobs.sh mints NEW job ids on every host, so a
# hardcoded value silently writes the notepad for a job that does not exist there. Set
# LISTINGS_JOB_ID in .env on each host; the literal below is this laptop's, kept as a fallback.
JOB_ID = os.environ.get("LISTINGS_JOB_ID") or "1ff50fb0cbdc"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(REPO, "data", "hermes.db")

FOLDERS = ["INBOX", "[Gmail]/Spam"]
FETCH_BATCH = 50          # uids per FETCH round trip
SEEN_KEYS_MAX = 400       # notepad values travel as one CLI argument; keep it bounded
FIRST_RUN_DAYS = 14       # with no watermark yet, look back this far rather than at everything

# Built-in fallback, used only when settings.yaml cannot be read. settings.yaml is the source
# of truth; this exists so a missing config degrades to sane behaviour instead of no run.
_DEFAULT_HUNT = {
    "areas": ["Penticton", "Naramata", "Oliver", "Osoyoos", "Okanagan Falls", "Kaleden",
              "Summerland", "Keremeos"],
    "min_acres": 2.0,
    "max_price": None,
    "keywords": ["vineyard", "grape", "winery", "acreage", "farm", "orchard", "irrigated",
                 "bench"],
    "top_areas": ["Osoyoos", "Oliver", "Penticton", "Naramata"],
    "price_ceilings": {},
}


def load_hunt() -> tuple[dict, list[str]]:
    """The owner's hunt filter from config/settings.yaml. Never guess their budget in code."""
    warnings: list[str] = []
    path = os.environ.get("SETTINGS_PATH") or os.path.join(REPO, "config", "settings.yaml")
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        raw = data.get("listings") or {}
    except Exception as exc:
        return dict(_DEFAULT_HUNT), [f"settings.yaml unreadable ({exc}); using built-in defaults"]

    hunt = dict(_DEFAULT_HUNT)
    for key in hunt:
        if raw.get(key) is not None:
            hunt[key] = raw[key]
    if not raw:
        warnings.append("no `listings:` section in settings.yaml; using built-in defaults")
    return hunt, warnings


def money(value) -> str:
    """Absent prices are ordinary. `f'${None:,}'` is a TypeError that kills the whole run."""
    if isinstance(value, (int, float)):
        return f"${value:,.0f}"
    return "price n/a"


# ----------------------------------------------------------------------------- parsing
def dheader(val) -> str:
    if val is None:
        return ""
    return "".join(
        b.decode(enc or "utf-8", "replace") if isinstance(b, bytes) else str(b)
        for b, enc in decode_header(val)
    )


def sender_addr(raw: str) -> str:
    return (parseaddr(raw or "")[1] or "").strip().lower()


def sender_allowed(addr: str, allowed: list[str]) -> bool:
    dom = addr.split("@")[-1] if "@" in addr else ""
    for entry in allowed:
        if entry.startswith("*@"):
            d = entry[2:]
            if dom == d or dom.endswith("." + d):
                return True
        elif addr == entry:
            return True
    return False


def clean_text(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    text = text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text)


def body_text(msg) -> str:
    """Prefer text/html, fall back to text/plain.

    Without the fallback a plain-text alert parses to an empty string, every field comes back
    None, and it is discarded as 'off-region' rather than reported as unparseable.
    """
    html_parts: list[str] = []
    plain_parts: list[str] = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        (html_parts if ctype == "text/html" else plain_parts).append(text)
    if html_parts:
        return clean_text("\n".join(html_parts))
    return re.sub(r"\s+", " ", "\n".join(plain_parts))


_MLS_RE = re.compile(r"MLS\s*(?:®|\(R\))?\s*(?:Number|No\.?|#)?\s*:?\s*([0-9]{6,8})", re.I)
# Metadata that sits next to the address and otherwise gets eaten as part of it: the MLS
# number and the "3 Bedroom 2 Bathroom 1,800 Square Feet" run both lead with digits, which is
# exactly what a street number looks like.
_ADDR_NOISE = re.compile(r"\d[\d,]*\s*(?:Bed\w*|Bath\w*|Square Feet|sq\.?\s*ft)", re.I)
_ADDRESS_RE = re.compile(
    r"(\d{1,6}\s+[A-Z0-9][A-Za-z0-9 .'\-]*?"
    r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|Crescent|Cres|Way|Circle|Court|Ct|Pass|"
    r"Place|Pl|Boulevard|Blvd|Trail|Highway|Hwy)"
    r"[^,.]*,\s*[A-Za-z][A-Za-z ]*(?:,\s*(?:BC|B\.C\.|British Columbia))?)"
)
_BROKERS = ["RE/MAX", "REMAX", "Royal LePage", "Century 21", "Sutton", "Coldwell Banker",
            "eXp", "Keller Williams", "2Percent", "Stonehaus", "Chamberlain", "Parker"]


def split_listings(text: str) -> list[tuple[str | None, str]]:
    """Segment one email body into (mls, segment_text) per listing.

    Alert emails bundle several listings. Segmenting on the MLS number keeps each listing's
    price, address and acreage with its own MLS instead of blending them into one phantom
    record that belongs to none of them.
    """
    hits = list(_MLS_RE.finditer(text))
    if not hits:
        return [(None, text)]
    segments: list[tuple[str | None, str]] = []
    for i, match in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        segments.append((match.group(1), text[match.start():end]))
    # Text before the first MLS (price/address often lead the card) belongs to listing one.
    if hits[0].start() > 0:
        mls, seg = segments[0]
        segments[0] = (mls, text[:hits[0].start()] + seg)
    return segments


def listing_urls(raw_bytes: bytes | None) -> list[str]:
    """Listing hrefs in document order, deduped."""
    if not raw_bytes:
        return []
    blob = raw_bytes.decode("latin-1")
    found: list[str] = []
    for match in re.finditer(
        r'href=["\']([^"\']*(?:realtor\.ca/real-estate/|zealty\.ca/)[^"\']*)["\']', blob, re.I
    ):
        url = match.group(1).replace("&amp;", "&")
        if url not in found:
            found.append(url)
    return found


def match_url(title: str | None, urls: list[str], used: set[str], index: int) -> str | None:
    """Pair a listing with its link by address slug, falling back to position.

    REALTOR.ca URLs carry an internal id rather than the MLS number, so the address slug
    ('1970-sutherland-road') is the only honest join available.
    """
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", (title or "").lower()) if len(t) > 2][:4]
    best, best_score = None, 0
    for url in urls:
        if url in used:
            continue
        low = url.lower()
        score = sum(1 for t in tokens if t in low)
        if score > best_score:
            best, best_score = url, score
    if best and best_score >= 2:
        return best
    if index < len(urls) and urls[index] not in used:
        return urls[index]
    return None


def parse_segment(mls: str | None, seg: str, subject: str, hunt: dict) -> dict:
    low = seg.lower()

    price = None
    pm = re.search(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(K|M)?\b", seg, re.I)
    if pm:
        try:
            val = float(pm.group(1).replace(",", ""))
        except ValueError:
            val = None
        if val is not None:
            suffix = (pm.group(2) or "").upper()
            val *= 1000 if suffix == "K" else 1_000_000 if suffix == "M" else 1
            # A bare "$500 off" in a footer is not a listing price.
            price = int(val) if val >= 10_000 else None

    beds = re.search(r"(\d+)\s*Bed", seg, re.I)
    baths = re.search(r"(\d+)\s*Bath", seg, re.I)
    sqft = re.search(r"([\d,]+)\s*(?:Square Feet|sq\.?\s*ft)", seg, re.I)

    acres = None
    am = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(acres?|hectares?|ha)\b", seg, re.I)
    if am:
        try:
            acres = float(am.group(1))
            if am.group(2).lower().startswith(("hectare", "ha")):
                acres *= 2.47105
        except ValueError:
            acres = None

    # Earliest mention wins, not whichever area happens to sort first in the config: a listing
    # that says "20 minutes from Penticton" is not a Penticton listing.
    area, area_pos = None, len(seg) + 1
    for candidate in hunt["areas"]:
        m = re.search(r"\b" + re.escape(candidate.lower()) + r"\b", low)
        if m and m.start() < area_pos:
            area, area_pos = candidate, m.start()

    keyword_hit = any(
        re.search(r"\b" + re.escape(k.lower()) + r"\b", low) for k in hunt["keywords"]
    )

    title = None
    sm = re.search(r"-\s*\d+\s*beds?/\d+\s*baths?\s*-\s*(.+)$", subject, re.I)
    if sm:
        title = sm.group(1).replace("\r", " ").replace("\n", " ").strip().rstrip(",")
    if not title:
        addr_text = seg.replace(mls, " ", 1) if mls else seg
        addr_text = _ADDR_NOISE.sub(" ", addr_text)
        am2 = _ADDRESS_RE.search(addr_text)
        if am2:
            title = re.sub(r"\s+", " ", am2.group(1)).strip().rstrip(",")
    if not title:
        title = subject.strip() or "(untitled listing)"

    broker = None
    if mls:
        post = seg.split(mls, 1)
        if len(post) > 1:
            bm = re.search(r"^\s*([A-Za-z0-9/&.'\- ]+?)\s+\d+\s*Bed", post[1])
            if bm:
                broker = bm.group(1).strip()
    if not broker:
        for b in _BROKERS:
            if b.lower() in low:
                broker = b
                break

    dedupe_key = f"mls-{mls}" if mls else "sha1-" + hashlib.sha1(
        f"{title}|{price}".encode()
    ).hexdigest()[:12]

    return {
        "mls": mls, "price": price,
        "beds": int(beds.group(1)) if beds else None,
        "baths": int(baths.group(1)) if baths else None,
        "sqft": int(sqft.group(1).replace(",", "")) if sqft else None,
        "acres": acres, "area": area, "keyword_hit": keyword_hit, "title": title,
        "broker": broker, "url": None, "dedupe_key": dedupe_key, "subject": subject,
    }


def parse_listings(msg, raw_bytes: bytes | None, hunt: dict) -> list[dict]:
    subject = dheader(msg.get("Subject", ""))
    text = body_text(msg)
    urls = listing_urls(raw_bytes)
    used: set[str] = set()
    out: list[dict] = []
    for i, (mls, seg) in enumerate(split_listings(text)):
        listing = parse_segment(mls, seg, subject, hunt)
        url = match_url(listing["title"], urls, used, i)
        if url:
            used.add(url)
            listing["url"] = url
        out.append(listing)
    return out


# ----------------------------------------------------------------------------- classify
def classify(listing: dict, hunt: dict) -> tuple[str, str]:
    area, price, acres = listing["area"], listing["price"], listing["acres"]
    if area not in hunt["areas"] and not listing["keyword_hit"]:
        return "filtered", "out of target region and no vineyard/acreage keyword"
    if hunt["max_price"] is not None and price is not None and price > hunt["max_price"]:
        return "filtered", f"{money(price)} is over max_price {money(hunt['max_price'])}"
    if listing["keyword_hit"]:
        return "interrupt", "explicit vineyard/acreage/farm keyword in listing"
    ceiling = (hunt["price_ceilings"] or {}).get(area)
    if area in hunt["top_areas"] and price is not None and ceiling is not None and price <= ceiling:
        return "interrupt", (f"core-belt area ({area}) and priced to move "
                             f"({money(price)} <= ceil {money(ceiling)})")
    if acres is not None and acres >= hunt["min_acres"] and area in hunt["areas"]:
        return "interrupt", f"{acres:g} ac in {area} (>= min_acres {hunt['min_acres']:g})"
    return "digest", (f"in target area ({area}) but no keyword and {money(price)} "
                      f"is not a clear 'move' trigger")


# ----------------------------------------------------------------------------- notepad
_MISSING = re.compile(r"^No notepad key '.*' for job ")


def note_get(key: str):
    """Read a notepad key. The CLI prints a sentinel and exits 0 when the key is absent."""
    r = subprocess.run(["hermes", "cron", "notepad", JOB_ID, "get", key],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    value = r.stdout.strip()
    if not value or _MISSING.match(value):
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def note_set(key: str, value) -> tuple[bool, str]:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    r = subprocess.run(["hermes", "cron", "notepad", JOB_ID, "set", key, value],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout.strip() + r.stderr.strip())


def prune_seen(seen: dict, cap: int = SEEN_KEYS_MAX) -> tuple[dict, int]:
    """Keep the newest `cap` entries.

    The whole map travels as a single command-line argument on every write; unbounded, it
    eventually exceeds the OS argument limit and the write starts failing — which silently
    re-reports every listing as new.
    """
    if len(seen) <= cap:
        return seen, 0
    ordered = sorted(
        seen.items(), key=lambda kv: str((kv[1] or {}).get("first_seen") or ""), reverse=True
    )
    return dict(ordered[:cap]), len(seen) - cap


# ----------------------------------------------------------------------------- DB
def db_write(listing: dict, tier: str, uid) -> str:
    if not os.path.exists(DB_PATH):
        return f"no-db({DB_PATH})"
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO listings
                   (dedupe_key, mls_number, source, title, price, acres, address, area, url,
                    first_seen_utc, raw_email_uid, notified)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (listing["dedupe_key"], listing["mls"], listing.get("source", "mls-email"),
                 listing["title"], listing["price"], listing["acres"], listing["title"],
                 listing["area"], listing["url"],
                 datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), str(uid),
                 1 if tier == "interrupt" else 0),
            )
            conn.commit()
        finally:
            conn.close()
        return "ok"
    except Exception as exc:
        return f"err:{exc}"


# ----------------------------------------------------------------------------- fetch
def folder_uids(server, folder: str, marks: dict) -> tuple[list, dict | None, str | None]:
    """UIDs not yet processed in this folder, plus the watermark to store afterwards.

    BODY.PEEK[] never sets \\Seen, so a plain UNSEEN search re-downloads the entire mailbox on
    every run, forever. The watermark is what keeps the work proportional to new mail. UIDs are
    only comparable within a UIDVALIDITY, so a change there resets to a bounded look-back.
    """
    try:
        info = server.select_folder(folder, readonly=True)
    except Exception as exc:
        return [], None, f"select_fail:{exc}"

    uidvalidity = info.get(b"UIDVALIDITY")
    mark = marks.get(folder) or {}
    last_uid = mark.get("last_uid") if mark.get("uidvalidity") == uidvalidity else None

    try:
        if last_uid:
            # IMAP returns the final message for `N:*` even when its UID < N, so filter again.
            uids = [u for u in server.search(["UID", f"{int(last_uid) + 1}:*"]) if u > last_uid]
        else:
            since = (datetime.now(UTC) - timedelta(days=FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
            uids = server.search(["SINCE", since])
    except Exception as exc:
        return [], None, f"search_fail:{exc}"

    uids = sorted(uids)
    new_mark = {"uidvalidity": uidvalidity, "last_uid": max(uids) if uids else last_uid}
    return uids, new_mark, None


def render(listing: dict) -> str:
    parts = [f"  • {listing['title']} — {money(listing['price'])}"]
    if listing.get("area"):
        parts.append(f" ({listing['area']})")
    if listing.get("acres"):
        parts.append(f" | {listing['acres']:g} ac")
    if listing.get("beds"):
        parts.append(f" | {listing['beds']}bd/{listing.get('baths') or '?'}ba")
        if listing.get("sqft"):
            parts.append(f"/{listing['sqft']}sqft")
    if listing.get("broker"):
        parts.append(f" | {listing['broker']}")
    if listing.get("url"):
        parts.append(f"\n    {listing['url']}")
    parts.append(f"\n    why: {listing['why']}")
    return "".join(parts)


def _handle_seen(listing: dict, seen_keys: dict, dedupe_hits: list, today: str) -> None:
    """A listing we already know about: the only thing worth noticing is a price move."""
    key = listing["dedupe_key"]
    prev = seen_keys[key] if isinstance(seen_keys.get(key), dict) else {}
    new_price, old_price = listing["price"], prev.get("price")
    if new_price is not None and old_price != new_price:
        dedupe_hits.append({
            "key": key, "mls": listing["mls"],
            "title": prev.get("title") or listing["title"],
            "area": prev.get("area") or listing["area"],
            "url": prev.get("url") or listing["url"],
            "price_change": True, "prev_price": old_price, "new_price": new_price,
        })
        prev["price"] = new_price
        prev.setdefault("price_history", []).append(
            {"on": today, "from": old_price, "to": new_price}
        )
        seen_keys[key] = prev
    else:
        dedupe_hits.append({"key": key, "mls": listing["mls"], "price_change": False})


def build_report(interrupt: list, digest: list, filtered: list, price_moves: list) -> list[str]:
    lines: list[str] = []
    if interrupt:
        lines.append("NEW — worth a look now:")
        lines.extend(render(x) for x in interrupt)
    if price_moves:
        lines.append("Price changed on a listing already seen:")
        for d in price_moves:
            arrow = "▼" if (d["prev_price"] or 0) > d["new_price"] else "▲"
            line = (f"  • {arrow} {d.get('title') or d['key']} — "
                    f"{money(d['prev_price'])} → {money(d['new_price'])}")
            if d.get("area"):
                line += f" ({d['area']})"
            if d.get("url"):
                line += f"\n    {d['url']}"
            lines.append(line)
    if digest:
        lines.append("New — holding for EOD digest:")
        for x in digest:
            line = f"  • {x['title']} — {money(x['price'])}"
            if x.get("area"):
                line += f" ({x['area']})"
            if x.get("url"):
                line += f" | {x['url']}"
            lines.append(line + f"  [why: {x['why']}]")
    if filtered:
        lines.append(f"(filtered out as off-region/no-keyword: {len(filtered)} — not shown)")
    return lines


def main() -> int:
    # Cron pipes stdout, and on Windows a pipe defaults to cp1252 - which cannot encode the
    # report glyphs. Printing a price-move arrow would then raise UnicodeEncodeError and take
    # down a run that had already done all its work.
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")

    hunt, warnings = load_hunt()

    missing = [v for v in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS") if not os.environ.get(v)]
    if missing:
        print(json.dumps({
            "verdict": "REPORT",
            "report_text": f"listings_triage could not run: missing env {', '.join(missing)}",
            "error": "missing_env", "missing": missing,
        }, indent=2))
        return 1

    allowed = [s.strip().lower()
               for s in os.environ.get("LISTINGS_ALLOWED_SENDERS", "").split(",") if s.strip()]
    if not allowed:
        warnings.append("LISTINGS_ALLOWED_SENDERS is empty; every message is treated as noise")

    seen_keys = note_get("seen_keys")
    if not isinstance(seen_keys, dict):
        seen_keys = {}
    marks = note_get("uid_marks")
    if not isinstance(marks, dict):
        marks = {}

    new_items: list[dict] = []
    dedupe_hits: list[dict] = []
    noise: list[str] = []
    today = date.today().isoformat()

    server = IMAPClient(os.environ["IMAP_HOST"], ssl=True, timeout=30)
    try:
        server.login(os.environ["IMAP_USER"], os.environ["IMAP_PASS"])
        for folder in FOLDERS:
            uids, new_mark, err = folder_uids(server, folder, marks)
            if err:
                warnings.append(f"{folder}: {err}")
                continue
            for start in range(0, len(uids), FETCH_BATCH):
                batch = uids[start:start + FETCH_BATCH]
                resp = server.fetch(batch, ["BODY.PEEK[]"])
                for uid in batch:
                    raw = (resp.get(uid) or {}).get(b"BODY[]")
                    if not raw:
                        continue
                    msg = email.message_from_bytes(raw)
                    addr = sender_addr(dheader(msg.get("From", "")))
                    if not sender_allowed(addr, allowed):
                        noise.append(f"{folder} uid{uid} {addr}")
                        continue
                    source = "zealty" if "zealty" in addr else "mls-email"
                    for listing in parse_listings(msg, raw, hunt):
                        listing.update({"source": source, "uid": uid, "folder": folder})
                        if listing["dedupe_key"] in seen_keys:
                            _handle_seen(listing, seen_keys, dedupe_hits, today)
                            continue

                        tier, why = classify(listing, hunt)
                        listing["tier"], listing["why"] = tier, why
                        # Record in seen_keys only once the row is safely stored, or a failed
                        # write would be marked seen and never retried.
                        listing["db"] = ("filtered-skip" if tier == "filtered"
                                         else db_write(listing, tier, uid))
                        if listing["db"].startswith("err:"):
                            warnings.append(
                                f"db write failed for {listing['dedupe_key']}: {listing['db']}"
                            )
                        else:
                            seen_keys[listing["dedupe_key"]] = {
                                "title": listing["title"], "price": listing["price"],
                                "beds": listing["beds"], "baths": listing["baths"],
                                "sqft": listing["sqft"], "area": listing["area"],
                                "acres": listing["acres"], "url": listing["url"],
                                "broker": listing["broker"], "first_seen": today,
                                "tier": tier, "note": why,
                            }
                        new_items.append(listing)
            if new_mark:
                marks[folder] = new_mark
    finally:
        with contextlib.suppress(Exception):
            server.logout()

    interrupt = [x for x in new_items if x.get("tier") == "interrupt"]
    digest = [x for x in new_items if x.get("tier") == "digest"]
    filtered = [x for x in new_items if x.get("tier") == "filtered"]
    price_moves = [d for d in dedupe_hits if d.get("price_change")]

    lines = build_report(interrupt, digest, filtered, price_moves)
    # Filtered-only runs are a silent success: nothing survived that the owner asked to see.
    verdict = "REPORT" if (interrupt or digest or price_moves) else "SILENT"

    seen_keys, dropped = prune_seen(seen_keys)
    if dropped:
        warnings.append(f"pruned {dropped} oldest seen_keys entries (cap {SEEN_KEYS_MAX})")

    ok_seen, seen_msg = note_set("seen_keys", seen_keys)
    ok_marks, _ = note_set("uid_marks", marks)
    if not ok_seen:
        # Every listing re-reports as new next run if this write is lost. Say so out loud.
        warnings.append(f"seen_keys notepad write FAILED ({seen_msg}); next run will re-report")
        verdict = "REPORT"
        lines.append("⚠ seen_keys could not be saved; the next run may repeat these listings.")

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    blk = (f"OK_{ts}. {'+'.join(FOLDERS)} by UID watermark. new={len(new_items)} "
           f"(interrupt={len(interrupt)}, digest={len(digest)}, filtered={len(filtered)}); "
           f"dedupe_hits={len(dedupe_hits)} (price_moves={len(price_moves)}); "
           f"noise_excluded={len(noise)}. verdict={verdict}. seen_keys size={len(seen_keys)}.")
    ok_blk, _ = note_set("imap_blocker", blk)

    print(json.dumps({
        "verdict": verdict,
        "report_text": "\n".join(lines) if lines else "",
        "new_items": [{k: v for k, v in x.items() if k != "subject"} for x in new_items],
        "dedupe_hits": dedupe_hits,
        "noise_excluded": noise,
        "warnings": warnings,
        "seen_keys_size": len(seen_keys),
        "notepad_updated": {"seen_keys": ok_seen, "uid_marks": ok_marks, "imap_blocker": ok_blk},
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
