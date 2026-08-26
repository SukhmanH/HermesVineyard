# 02 — Data Model

SQLite, WAL mode. All timestamps stored as UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`); display always
converted to `America/Vancouver`. Compliance tables are **append-only** (enforced by triggers, not
convention). The builder (Opus) creates `schema.sql` verbatim from the DDL below (M0).

> **This file is the system of record — Hermes Agent's memory is not.** Everything here is written
> exclusively by `vineyard-mcp` tools with server-side validation. The agent's `~/.hermes/` store
> holds conversational context only and is compressible/lossy by design; it must never be the
> source of a compliance answer. See docs/01 §D2 and §3.
>
> This schema is deliberately **runtime-agnostic**: nothing below depends on Hermes Agent, Baileys,
> or Meta. If the runtime is ever replaced, the compliance record and its exports survive unchanged.

## 1. Entities

```
contacts ──< task_workers >── task_log ──> blocks
    │                                        ▲
    └────────── spray_log ───────────────────┘──> products
drafts · messages_raw · media · listings · weather_cache · audit_log
```

## 2. DDL specification

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- People: workers, managers, owner. One row per WhatsApp number.
CREATE TABLE contacts (
  id                 INTEGER PRIMARY KEY,
  wa_phone           TEXT NOT NULL UNIQUE,      -- E.164, e.g. +12505551234
  full_name          TEXT NOT NULL,
  short_name         TEXT NOT NULL,             -- how Hermes addresses them
  lang               TEXT NOT NULL DEFAULT 'es' CHECK (lang IN ('es','en','pa')),
  role               TEXT NOT NULL CHECK (role IN ('worker','manager','owner')),
  voice_replies      INTEGER NOT NULL DEFAULT 0, -- 1 = also send briefs/alerts as voice (Edge TTS,
                                                --     docs/01 §7.1). Asked at onboarding; matters
                                                --     where reading is harder than listening
  active             INTEGER NOT NULL DEFAULT 1,
  consent_ts_utc     TEXT,                      -- when they texted ALTA/HOLA (message opt-in)
  created_at_utc     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Vineyard blocks/fields registry.
CREATE TABLE blocks (
  id        INTEGER PRIMARY KEY,
  code      TEXT NOT NULL UNIQUE,               -- what workers say: 'B3', 'bloque 3' → 'B3'
  name      TEXT NOT NULL,
  site      TEXT NOT NULL CHECK (site IN ('penticton','naramata','oliver')),
  acres     REAL NOT NULL,
  variety   TEXT,
  row_count INTEGER,
  lat       REAL, lon REAL,                     -- for site-accurate weather (falls back to site coords)
  notes     TEXT,
  active    INTEGER NOT NULL DEFAULT 1
);

-- Pesticide/product registry. REI/PHI values are UNVERIFIED until a human
-- confirms them against the physical label; Hermes must not assert REI from
-- an unverified row — it asks the applicator to read the label instead.
CREATE TABLE products (
  id             INTEGER PRIMARY KEY,
  trade_name     TEXT NOT NULL UNIQUE,
  pcp_number     TEXT,                          -- PCP registration no. from label
  type           TEXT,                          -- fungicide / insecticide / herbicide / other
  rei_hours      INTEGER,
  phi_days       INTEGER,
  max_temp_c     REAL,                          -- phytotoxicity ceiling (e.g. sulfur ~30)
  rainfast_hours REAL,
  default_rate   TEXT, rate_units TEXT,
  verified       INTEGER NOT NULL DEFAULT 0,    -- 1 only after label check
  verified_by    TEXT, verified_at_utc TEXT,
  notes          TEXT
);

-- ── COMPLIANCE TABLE: append-only. One row per confirmed application. ──
CREATE TABLE spray_log (
  id                   INTEGER PRIMARY KEY,
  log_date             TEXT NOT NULL,           -- local date of application YYYY-MM-DD
  start_time           TEXT NOT NULL,           -- local HH:MM
  end_time             TEXT,
  block_id             INTEGER NOT NULL REFERENCES blocks(id),
  acres_treated        REAL NOT NULL,
  product_id           INTEGER REFERENCES products(id),
  product_name_raw     TEXT NOT NULL,           -- exactly what the worker said
  pcp_number           TEXT,                    -- copied from product at commit (label value)
  rate_value           REAL, rate_units TEXT,   -- e.g. 8, 'kg/ha'
  total_amount         REAL, total_units TEXT,
  target_pest          TEXT,                    -- e.g. powdery mildew / oídio
  method               TEXT,                    -- e.g. airblast sprayer, backpack
  applicator_contact_id INTEGER NOT NULL REFERENCES contacts(id),
  applicator_name      TEXT NOT NULL,           -- denormalized: record stands alone for auditors
  wind_kmh             REAL, wind_dir TEXT,     -- weather AT application (auto-prefilled, worker-confirmed)
  temp_c               REAL, rh_pct REAL, sky TEXT,
  weather_source       TEXT,                    -- 'open-meteo' | 'eccc' | 'worker-reported'
  rei_hours            INTEGER,
  rei_expires_at_utc   TEXT,                    -- end_time + rei_hours; drives NO-ENTRY warnings
  phi_days             INTEGER,
  notes                TEXT,
  raw_message          TEXT NOT NULL,           -- original Spanish message(s), verbatim (audit gold)
  source_msg_id        TEXT,                    -- WhatsApp message id
  created_at_utc       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by           TEXT NOT NULL DEFAULT 'hermes',
  corrects_log_id      INTEGER REFERENCES spray_log(id)  -- non-null ⇒ this row supersedes that one
);

CREATE TRIGGER trg_spray_no_update BEFORE UPDATE ON spray_log
BEGIN SELECT RAISE(ABORT, 'spray_log is append-only; insert a correction row'); END;
CREATE TRIGGER trg_spray_no_delete BEFORE DELETE ON spray_log
BEGIN SELECT RAISE(ABORT, 'spray_log is append-only'); END;

-- General task log (pruning, canopy, irrigation, mowing…). Same append-only rules.
CREATE TABLE task_log (
  id              INTEGER PRIMARY KEY,
  log_date        TEXT NOT NULL,
  task_type       TEXT NOT NULL,                -- poda|deshoje|desbrote|riego|corte_pasto|alambre|cosecha|otro
  block_id        INTEGER REFERENCES blocks(id),
  hours_total     REAL,                         -- crew-hours (drives weekly payroll export)
  quantity        REAL, quantity_unit TEXT,     -- e.g. 14, 'hileras'
  start_time      TEXT, end_time TEXT,
  notes           TEXT,
  raw_message     TEXT NOT NULL,
  source_msg_id   TEXT,
  created_at_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by      TEXT NOT NULL DEFAULT 'hermes',
  corrects_log_id INTEGER REFERENCES task_log(id)
);
CREATE TRIGGER trg_task_no_update BEFORE UPDATE ON task_log
BEGIN SELECT RAISE(ABORT, 'task_log is append-only; insert a correction row'); END;
CREATE TRIGGER trg_task_no_delete BEFORE DELETE ON task_log
BEGIN SELECT RAISE(ABORT, 'task_log is append-only'); END;

CREATE TABLE task_workers (                     -- who worked on a logged task
  task_log_id INTEGER NOT NULL REFERENCES task_log(id),
  contact_id  INTEGER NOT NULL REFERENCES contacts(id),
  PRIMARY KEY (task_log_id, contact_id)
);

-- Every inbound/outbound WhatsApp message, verbatim. Append-only.
-- Written by vineyard-mcp's log_message tool, called by the agent on every turn — this is our
-- own durable copy, independent of Hermes Agent's memory and of WhatsApp history.
CREATE TABLE messages_raw (
  id            INTEGER PRIMARY KEY,
  direction     TEXT NOT NULL CHECK (direction IN ('in','out')),
  wa_phone      TEXT NOT NULL,                  -- sender (in) or recipient (out), E.164
  wa_message_id TEXT UNIQUE,                    -- Baileys message key id; dedupe key on replay
  chat_jid      TEXT,                           -- Baileys chat id; distinguishes 1:1 from group
  is_group      INTEGER NOT NULL DEFAULT 0,     -- 1 = crew group broadcast (docs/01 §D1)
  msg_type      TEXT NOT NULL,                  -- text|audio|image|document|interactive
  body          TEXT,
  media_id      INTEGER REFERENCES media(id),
  ts_utc        TEXT NOT NULL
);
CREATE TRIGGER trg_msgs_no_update BEFORE UPDATE ON messages_raw
BEGIN SELECT RAISE(ABORT, 'messages_raw is append-only'); END;
CREATE TRIGGER trg_msgs_no_delete BEFORE DELETE ON messages_raw
BEGIN SELECT RAISE(ABORT, 'messages_raw is append-only'); END;

CREATE TABLE media (                            -- WhatsApp media (label photos, voice notes)
  id           INTEGER PRIMARY KEY,
  wa_media_id  TEXT NOT NULL,                   -- Baileys media key / message id
  local_path   TEXT NOT NULL,                   -- decrypted file on disk (MEDIA_DIR)
  mime         TEXT, sha256 TEXT,
  transcript   TEXT,                            -- voice notes: ASR text, kept for audit
  linked_table TEXT, linked_id INTEGER,         -- e.g. 'spray_log', 42
  created_at_utc TEXT NOT NULL
);

-- Drafts in progress. Hermes Agent owns the *conversation*; this table owns the *pending record*
-- and the commit gate. A draft is created by draft_spray_log / draft_task_log, which returns
-- confirm_token; commit_* refuses any call whose token does not match an unconsumed draft whose
-- worker replied «SÍ». This is what makes "nothing commits without confirmation" structural
-- rather than a prompt instruction the model could skip (docs/01 §3.1).
CREATE TABLE drafts (
  confirm_token  TEXT PRIMARY KEY,              -- random, single-use
  wa_phone       TEXT NOT NULL,
  intent         TEXT NOT NULL,                 -- spray_report|task_report|correction
  draft_json     TEXT NOT NULL,                 -- partially- or fully-filled record
  missing_fields TEXT,                          -- JSON array; empty ⇒ ready to show the card
  corrects_log_id INTEGER,                      -- set for correction drafts
  state          TEXT NOT NULL DEFAULT 'collecting'
                 CHECK (state IN ('collecting','awaiting_confirm','committed','expired')),
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);
CREATE INDEX idx_drafts_phone ON drafts (wa_phone, state);

CREATE TABLE listings (
  id            INTEGER PRIMARY KEY,
  dedupe_key    TEXT NOT NULL UNIQUE,           -- MLS# if present, else sha1(address|price)
  mls_number    TEXT,
  source        TEXT NOT NULL,                  -- 'mls-email' | 'zealty'
  title         TEXT, price REAL, acres REAL,
  address       TEXT, area TEXT, url TEXT,
  first_seen_utc TEXT NOT NULL,
  raw_email_uid TEXT,
  notified      INTEGER NOT NULL DEFAULT 0      -- set 1 once included in a manager report
);

CREATE TABLE weather_cache (
  id             INTEGER PRIMARY KEY,
  site           TEXT NOT NULL,
  source         TEXT NOT NULL,
  fetched_at_utc TEXT NOT NULL,
  payload_json   TEXT NOT NULL
);

-- Append-only audit trail for everything that is not itself append-only
-- (product verification, contact changes, exports, job runs, failures) AND for every autonomous
-- decision Hermes makes (docs/01 §3.1). Hermes leads, so this table is how its leadership stays
-- reviewable: action='agent.decision' rows carry what it chose, what it saw, and why.
CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY,
  at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  actor       TEXT NOT NULL,                    -- 'hermes' | wa_phone | 'admin-cli'
  action      TEXT NOT NULL,                    -- 'agent.decision' | 'product.verified'
                                                -- | 'export.monthly' | 'job.failed' | 'job.skipped'
  entity      TEXT, entity_id INTEGER,
  detail_json TEXT                              -- agent.decision: {observed, reasoning, alternatives}
);
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- ── Views ──
-- Latest version of each record (corrections supersede their target).
CREATE VIEW spray_log_current AS
  SELECT * FROM spray_log s
  WHERE NOT EXISTS (SELECT 1 FROM spray_log c WHERE c.corrects_log_id = s.id);
CREATE VIEW task_log_current AS
  SELECT * FROM task_log t
  WHERE NOT EXISTS (SELECT 1 FROM task_log c WHERE c.corrects_log_id = t.id);

-- Blocks currently under a re-entry interval.
CREATE VIEW rei_active AS
  SELECT s.id, s.block_id, b.code AS block_code, s.product_name_raw,
         s.rei_expires_at_utc
  FROM spray_log_current s JOIN blocks b ON b.id = s.block_id
  WHERE s.rei_expires_at_utc > strftime('%Y-%m-%dT%H:%M:%SZ','now');
```

## 3. Corrections flow (append-only, auditable)

1. Worker: «CORREGIR» or "me equivoqué, fueron 6 kg no 8".
2. Agent calls `find_recent_logs(wa_phone)` → picks the target (or asks which), then
   `draft_correction(log_id, changes)` builds a **new** draft pre-filled from the old row with the
   change applied, and returns a fresh `confirm_token`. Re-confirmed in Spanish like any commit.
3. `commit_spray_log` inserts a new row with `corrects_log_id = <old id>`. Old row never changes —
   the append-only trigger guarantees it even if the agent tries otherwise.
4. Reports and exports use `*_current` views; the compliance export includes **both** rows,
   with superseded rows flagged `SUPERSEDED-BY <id>` — auditors see the full history.

## 4. BC compliance mapping (IPM Regulation pesticide-use records, 3-yr retention)

| BC record requirement | Column(s) |
|---|---|
| Date & time of application | `log_date`, `start_time`, `end_time` |
| Trade name + PCP registration number | `product_name_raw`/`products.trade_name`, `pcp_number` |
| Application rate & quantity | `rate_value`+`rate_units`, `total_amount`+`total_units` |
| Location & size of area treated | `block_id` (→ code/name/site), `acres_treated` |
| Target pest / purpose | `target_pest` |
| Method / equipment | `method` |
| Prevailing weather (wind speed & direction, temp) | `wind_kmh`, `wind_dir`, `temp_c`, `rh_pct`, `sky` |
| Applicator name | `applicator_name` |

> **Removed by owner decision, 2026-08-21:** `applicator_cert_no` and `ppe`. The certificate
> is named in BC's IPM record requirements, so the compliance export no longer carries it — if
> an inspector asks, it is supplied out of band. PPE was never a BC *record-keeping* field (it is
> a WorkSafeBC/label matter), so dropping it costs nothing on the record.
| Integrity / provenance | append-only triggers, `raw_message`, `source_msg_id`, `created_at_utc`, corrections chain |

REI/PHI are not strictly record-keeping fields but drive worker-safety warnings, so they are
first-class columns. **Builder note:** have the owner double-check the final export columns
against the current BCMA "Pesticide Application Record" form before first spray season.

## 5. Seed data (Opus creates `seed/*.csv` from these specs; owner fills real values)

- **blocks.csv** — `code,name,site,acres,variety,row_count,lat,lon,notes`. Example row:
  `B3,Home North,penticton,4.5,Merlot,52,,,`
- **contacts.csv** — `wa_phone,full_name,short_name,lang,role,voice_replies,reports_in`.
  Example: `+15211234567,Juan Pérez,Juan,es,worker,,1` / `+12505550000,Owner Name,Boss,en,owner,,0`
- **products.csv** — `trade_name,pcp_number,type,rei_hours,phi_days,max_temp_c,rainfast_hours,default_rate,rate_units,notes`.
  Seed with the products actually in the spray shed. **Every REI/PHI/PCP value ships with
  `verified=0`**; a manager confirms each against the physical label (bot offers a one-tap
  verify flow), which flips `verified=1` and writes an `audit_log` row.

## 6. Retention & backup policy

- Nightly (21:30): `sqlite3 .backup` snapshot → `backups/hermes-YYYY-MM-DD.db`; keep 30 daily,
  12 monthly. Copy off-box (email the monthly to owner, or rclone to cloud storage).
- Nightly, alongside the DB: back up the **Baileys auth state** and agent config from `~/.hermes/`.
  Losing the auth state does not lose data, but it forces a QR re-pair on the owner's phone —
  restoring it makes disaster recovery unattended. Treat it as a **secret**: it is equivalent to a
  logged-in WhatsApp session for the bot's number. Encrypt it if it leaves the machine.
- Monthly (1st): compliance workbook `exports/compliance-YYYY-MM.xlsx` (spray records + audit
  rows) — emailed to managers and **never deleted** (BC requires ≥3 years; we keep forever).
- `messages_raw` and media pruning: none in Phase 1 (volume is tiny); revisit at 1 GB.
