-- Vineyard compliance kernel — system of record.
-- Per docs/02. Compliance tables are append-only, enforced by TRIGGERS rather than convention:
-- the agent cannot talk its way past a RAISE(ABORT), and neither can a prompt-injected message.
--
-- All timestamps stored as UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ). Display converts to
-- America/Vancouver. Nothing in this file depends on Hermes Agent, Baileys, or Meta — if the
-- runtime is ever replaced, the compliance record and its exports survive unchanged.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- People: workers, managers, owner. One row per WhatsApp number.
CREATE TABLE contacts (
  id                 INTEGER PRIMARY KEY,
  wa_phone           TEXT NOT NULL UNIQUE,      -- E.164, e.g. +12505551234
  wa_lid             TEXT,                      -- WhatsApp device-linked id, e.g.
                                                -- '143976027939069@lid'. Some senders are
                                                -- identified this way instead of by phone -
                                                -- resolve_contact() checks both. Uniqueness is
                                                -- a partial index below, not a column
                                                -- constraint, so it does not conflict with the
                                                -- many contacts that have no lid yet (NULL).
  full_name          TEXT NOT NULL,
  short_name         TEXT NOT NULL,             -- how Hermes addresses them
  lang               TEXT NOT NULL DEFAULT 'es' CHECK (lang IN ('es','en','pa')),
  role               TEXT NOT NULL CHECK (role IN ('worker','manager','owner')),
  voice_replies      INTEGER NOT NULL DEFAULT 0,-- 1 = also send briefs/alerts as voice
  reports_in         TEXT NOT NULL DEFAULT 'auto'
                     CHECK (reports_in IN ('auto','es','en','pa')),
                                                -- language this person REPORTS in. Distinct from
                                                -- `lang` (what they READ): the spray applicator
                                                -- reads Gurmukhi but types spray reports in
                                                -- English (docs/01 §D11). 'auto' = same as lang.
  active             INTEGER NOT NULL DEFAULT 1,
  consent_ts_utc     TEXT,                      -- when they opted in; no consent = no messages
  created_at_utc     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX idx_contacts_lid ON contacts (wa_lid) WHERE wa_lid IS NOT NULL;

-- Vineyard blocks/fields registry.
CREATE TABLE blocks (
  id        INTEGER PRIMARY KEY,
  code      TEXT NOT NULL UNIQUE,               -- what workers say: 'B3', 'bloque 3' -> 'B3'
  name      TEXT NOT NULL,
  site      TEXT NOT NULL CHECK (site IN ('penticton','naramata','oliver')),
  acres     REAL NOT NULL,
  variety   TEXT,
  row_count INTEGER,
  lat       REAL, lon REAL,                     -- falls back to site coords
  -- Irrigation attributes. Absent is fine and simply narrows what can be advised: without an
  -- emitter rate Hermes reports a water DEFICIT in mm and never an absolute volume to apply,
  -- because litres depend on soil, rooting depth and emitter spacing it does not have.
  soil_type       TEXT,
  irrigation_type TEXT,                        -- drip | sprinkler | none
  emitter_lph     REAL,                        -- litres/hour per emitter
  emitters_per_vine REAL,
  vines_per_acre  INTEGER,
  notes     TEXT,
  active    INTEGER NOT NULL DEFAULT 1
);

-- Pesticide/product registry. REI/PHI are UNVERIFIED until a human confirms them against the
-- physical label. Hermes must not assert an REI from an unverified row (docs/01 §3.4).
CREATE TABLE products (
  id             INTEGER PRIMARY KEY,
  trade_name     TEXT NOT NULL UNIQUE,
  pcp_number     TEXT,                          -- PCP registration no. from label
  type           TEXT,                          -- fungicide / insecticide / herbicide / other
  rei_hours      INTEGER,
  phi_days       INTEGER,
  max_temp_c     REAL,                          -- phytotoxicity ceiling (sulfur ~30)
  rainfast_hours REAL,
  default_rate   TEXT, rate_units TEXT,
  -- ── Advisory fields (docs/01 §D12). These make recommendations GROUNDED rather than
  -- invented: Hermes may only propose products that exist in this table, at their label rate.
  frac_group     TEXT,                          -- resistance group (FRAC/IRAC/HRAC), e.g. 'M2'.
                                                -- Drives rotation advice: repeating a group is
                                                -- how resistance is bred.
  target_pests   TEXT,                          -- comma list, e.g. 'powdery mildew,botrytis'
  reapply_days   INTEGER,                       -- label reapplication interval, protective window
  verified       INTEGER NOT NULL DEFAULT 0,    -- 1 only after label check
  verified_by    TEXT, verified_at_utc TEXT,
  notes          TEXT
);

-- ── COMPLIANCE TABLE: append-only. One row per confirmed application. ──
CREATE TABLE spray_log (
  id                    INTEGER PRIMARY KEY,
  log_date              TEXT NOT NULL,          -- local date of application YYYY-MM-DD
  start_time            TEXT NOT NULL,          -- local HH:MM
  end_time              TEXT,
  block_id              INTEGER NOT NULL REFERENCES blocks(id),
  acres_treated         REAL NOT NULL,
  product_id            INTEGER REFERENCES products(id),
  product_name_raw      TEXT NOT NULL,          -- exactly what the worker said
  pcp_number            TEXT,                   -- copied from product at commit (label value)
  rate_value            REAL, rate_units TEXT,
  total_amount          REAL, total_units TEXT,
  target_pest           TEXT,
  method                TEXT,                   -- airblast sprayer, backpack, ...
  applicator_contact_id INTEGER NOT NULL REFERENCES contacts(id),
  applicator_name       TEXT NOT NULL,          -- denormalized: the record stands alone
  wind_kmh              REAL, wind_dir TEXT,    -- weather AT application
  temp_c                REAL, rh_pct REAL, sky TEXT,
  weather_source        TEXT,                   -- 'eccc' | 'open-meteo' | 'worker-reported'
  rei_hours             INTEGER,
  rei_expires_at_utc    TEXT,                   -- drives NO-ENTRY warnings
  phi_days              INTEGER,
  notes                 TEXT,
  raw_message           TEXT NOT NULL,          -- original message(s), verbatim (audit gold)
  confirmed_by_reply    TEXT,                   -- the worker's own words confirming the card.
                                                -- This is their signature on a legal record.
  rate_flag             TEXT,                   -- e.g. 'above_label_rate:20.0 vs 6' - recorded,
                                                -- not silently dropped, when a rate looks wrong
  source_msg_id         TEXT,
  created_at_utc        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by            TEXT NOT NULL DEFAULT 'hermes',
  corrects_log_id       INTEGER REFERENCES spray_log(id)  -- non-null => supersedes that row
);

CREATE TRIGGER trg_spray_no_update BEFORE UPDATE ON spray_log
BEGIN SELECT RAISE(ABORT, 'spray_log is append-only; insert a correction row'); END;
CREATE TRIGGER trg_spray_no_delete BEFORE DELETE ON spray_log
BEGIN SELECT RAISE(ABORT, 'spray_log is append-only'); END;

CREATE INDEX idx_spray_date  ON spray_log (log_date);
CREATE INDEX idx_spray_block ON spray_log (block_id, log_date);
CREATE INDEX idx_spray_appl  ON spray_log (applicator_contact_id, log_date);
CREATE INDEX idx_spray_rei   ON spray_log (rei_expires_at_utc);

-- General task log (pruning, canopy, irrigation, mowing...). Same append-only rules.
CREATE TABLE task_log (
  id              INTEGER PRIMARY KEY,
  log_date        TEXT NOT NULL,
  task_type       TEXT NOT NULL,                -- poda|deshoje|desbrote|riego|corte_pasto|
                                                -- alambre|cosecha|otro
  block_id        INTEGER REFERENCES blocks(id),
  hours_total     REAL,                         -- CREW-hours: 3 people x 4h = 12, not 4
  quantity        REAL, quantity_unit TEXT,     -- e.g. 14, 'hileras'
  start_time      TEXT, end_time TEXT,
  notes           TEXT,
  raw_message     TEXT NOT NULL,
  confirmed_by_reply TEXT,
  source_msg_id   TEXT,
  created_at_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by      TEXT NOT NULL DEFAULT 'hermes',
  corrects_log_id INTEGER REFERENCES task_log(id)
);

CREATE TRIGGER trg_task_no_update BEFORE UPDATE ON task_log
BEGIN SELECT RAISE(ABORT, 'task_log is append-only; insert a correction row'); END;
CREATE TRIGGER trg_task_no_delete BEFORE DELETE ON task_log
BEGIN SELECT RAISE(ABORT, 'task_log is append-only'); END;

CREATE INDEX idx_task_date  ON task_log (log_date);
CREATE INDEX idx_task_block ON task_log (block_id, log_date);

CREATE TABLE task_workers (
  task_log_id INTEGER NOT NULL REFERENCES task_log(id),
  contact_id  INTEGER NOT NULL REFERENCES contacts(id),
  hours REAL CHECK (hours IS NULL OR (hours > 0 AND hours <= 24)),
  PRIMARY KEY (task_log_id, contact_id)
);

CREATE TRIGGER trg_task_workers_no_update BEFORE UPDATE ON task_workers
BEGIN SELECT RAISE(ABORT, 'task_workers is append-only; insert a task correction'); END;
CREATE TRIGGER trg_task_workers_no_delete BEFORE DELETE ON task_workers
BEGIN SELECT RAISE(ABORT, 'task_workers is append-only'); END;

-- Every inbound/outbound message, verbatim. Our own durable copy, independent of Hermes Agent's
-- memory and of WhatsApp history.
CREATE TABLE messages_raw (
  id            INTEGER PRIMARY KEY,
  direction     TEXT NOT NULL CHECK (direction IN ('in','out')),
  wa_phone      TEXT NOT NULL,
  wa_message_id TEXT UNIQUE,                    -- dedupe key on replay
  chat_jid      TEXT,
  is_group      INTEGER NOT NULL DEFAULT 0,
  msg_type      TEXT NOT NULL,                  -- text|audio|image|document|interactive
  body          TEXT,
  media_id      INTEGER REFERENCES media(id),
  ts_utc        TEXT NOT NULL
);
CREATE TRIGGER trg_msgs_no_update BEFORE UPDATE ON messages_raw
BEGIN SELECT RAISE(ABORT, 'messages_raw is append-only'); END;
CREATE TRIGGER trg_msgs_no_delete BEFORE DELETE ON messages_raw
BEGIN SELECT RAISE(ABORT, 'messages_raw is append-only'); END;

CREATE INDEX idx_msgs_phone ON messages_raw (wa_phone, ts_utc);

CREATE TABLE media (
  id             INTEGER PRIMARY KEY,
  wa_media_id    TEXT NOT NULL,
  local_path     TEXT NOT NULL,
  mime           TEXT, sha256 TEXT,
  transcript     TEXT,                          -- voice notes: ASR text, kept for audit.
  transcript_src TEXT,                          -- which ASR produced it — matters for Punjabi,
                                                -- where the gateway transcript is re-done
                                                -- (docs/01 §D11)
  linked_table   TEXT, linked_id INTEGER,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Drafts in progress. Hermes owns the CONVERSATION; this table owns the PENDING RECORD and the
-- commit gate. commit_* refuses any call whose token does not match an unconsumed draft in
-- state 'awaiting_confirm'. This is what makes "nothing commits without confirmation"
-- structural rather than a prompt instruction the model could skip (docs/01 §3.1).
CREATE TABLE drafts (
  confirm_token   TEXT PRIMARY KEY,             -- random, single-use
  wa_phone        TEXT NOT NULL,
  intent          TEXT NOT NULL CHECK (intent IN ('spray_report','task_report','correction')),
  target_table    TEXT CHECK (target_table IN ('spray_log','task_log')),
  draft_json      TEXT NOT NULL,
  missing_fields  TEXT,                         -- JSON array; empty => ready to show the card
  corrects_log_id INTEGER,
  state           TEXT NOT NULL DEFAULT 'collecting'
                  CHECK (state IN ('collecting','ready','awaiting_confirm','committed','expired')),
  -- 'ready'           = all fields present, card NOT yet shown to the worker
  -- 'awaiting_confirm'= card was rendered and sent; we are waiting on their reply
  -- Splitting these is what makes obligation 1 real. When draft_* could set awaiting_confirm
  -- by itself, the agent could draft and commit in one breath and no human ever agreed.
  presented_at_utc TEXT,           -- when the confirmation card was shown
  worker_reply     TEXT,           -- their affirmative words, verbatim - the signature evidence
  created_at_utc  TEXT NOT NULL,
  updated_at_utc  TEXT NOT NULL
);
CREATE INDEX idx_drafts_phone ON drafts (wa_phone, state);

CREATE TABLE listings (
  id             INTEGER PRIMARY KEY,
  dedupe_key     TEXT NOT NULL UNIQUE,          -- MLS# if present, else sha1(address|price)
  mls_number     TEXT,
  source         TEXT NOT NULL,                 -- 'mls-email' | 'zealty'
  title          TEXT, price REAL, acres REAL,
  address        TEXT, area TEXT, url TEXT,
  first_seen_utc TEXT NOT NULL,
  raw_email_uid  TEXT,
  notified       INTEGER NOT NULL DEFAULT 0
);

-- Expected phenology / harvest per block, so PHI conflicts and timing advice have something to
-- reason against. Owner-maintained; absent is fine and simply narrows what Hermes can say.
CREATE TABLE block_season (
  id                INTEGER PRIMARY KEY,
  block_id          INTEGER NOT NULL REFERENCES blocks(id),
  season_year       INTEGER NOT NULL,
  budbreak_date     TEXT,                       -- local YYYY-MM-DD, drives GDD accumulation
  bloom_date        TEXT,
  veraison_date     TEXT,
  expected_harvest  TEXT,                       -- checked against product PHI before advising
  notes             TEXT,
  UNIQUE (block_id, season_year)
);

-- ── Fruit maturity: what the winery wants, and where the fruit actually is ──
-- Contract targets per block per season. Wineries spec a Brix window, and usually TA and pH
-- alongside it; sugar alone is not ripeness.
CREATE TABLE fruit_targets (
  id                  INTEGER PRIMARY KEY,
  block_id            INTEGER NOT NULL REFERENCES blocks(id),
  season_year         INTEGER NOT NULL,
  winery              TEXT,
  target_brix_min     REAL, target_brix_max REAL,
  target_ta_min       REAL, target_ta_max REAL,     -- titratable acidity, g/L
  target_ph_min       REAL, target_ph_max REAL,
  harvest_window_from TEXT, harvest_window_to TEXT, -- local YYYY-MM-DD
  contract_notes      TEXT,
  UNIQUE (block_id, season_year, winery)
);

-- Measured samples. APPEND-ONLY: these drive harvest calls and contract compliance, and a
-- retro-edited ripening curve is a curve nobody can trust. Corrections supersede, as elsewhere.
CREATE TABLE fruit_samples (
  id                  INTEGER PRIMARY KEY,
  block_id            INTEGER NOT NULL REFERENCES blocks(id),
  sampled_on          TEXT NOT NULL,                -- local YYYY-MM-DD
  brix                REAL,
  ta_g_l              REAL,
  ph                  REAL,
  berry_weight_g      REAL,
  sample_size         INTEGER,                      -- berries in the sample; small = noisy
  sampled_by_contact_id INTEGER REFERENCES contacts(id),
  method              TEXT,                         -- refractometer, lab, ...
  notes               TEXT,
  raw_message         TEXT,
  created_at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  corrects_sample_id  INTEGER REFERENCES fruit_samples(id)
);
CREATE TRIGGER trg_sample_no_update BEFORE UPDATE ON fruit_samples
BEGIN SELECT RAISE(ABORT, 'fruit_samples is append-only; insert a correction row'); END;
CREATE TRIGGER trg_sample_no_delete BEFORE DELETE ON fruit_samples
BEGIN SELECT RAISE(ABORT, 'fruit_samples is append-only'); END;
CREATE INDEX idx_sample_block ON fruit_samples (block_id, sampled_on);

CREATE VIEW fruit_samples_current AS
  SELECT * FROM fruit_samples f
  WHERE NOT EXISTS (SELECT 1 FROM fruit_samples c WHERE c.corrects_sample_id = f.id);

CREATE TABLE weather_cache (
  id             INTEGER PRIMARY KEY,
  site           TEXT NOT NULL,
  source         TEXT NOT NULL,                 -- 'eccc' | 'open-meteo' | 'cache-stale'
  fetched_at_utc TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  verdict_json   TEXT                           -- compute_spray_window() output at fetch time
);
CREATE INDEX idx_weather_site ON weather_cache (site, fetched_at_utc);

-- Weather history: one measured day per site. Feeds season-over-season GDD comparisons and
-- mildew-model validation. Upsert by (site, obs_date): weather actuals are correctable
-- instrument data, not compliance records - the latest measurement wins.
CREATE TABLE daily_obs (
  id INTEGER PRIMARY KEY,
  site TEXT NOT NULL,
  obs_date TEXT NOT NULL,
  tmax_c REAL,
  tmin_c REAL,
  precip_mm REAL,
  source TEXT NOT NULL,
  fetched_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (site, obs_date)
);
CREATE INDEX idx_daily_obs_site ON daily_obs (site, obs_date);

-- Append-only audit trail for everything not itself append-only, AND for every autonomous
-- decision Hermes makes (docs/01 §3.1). Hermes leads, so this table is how its leadership
-- stays reviewable.
CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY,
  at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  actor       TEXT NOT NULL,                    -- 'hermes' | wa_phone | 'admin-cli'
  action      TEXT NOT NULL,                    -- 'agent.decision' | 'product.verified'
                                                -- | 'job.started' | 'job.finished'
                                                -- | 'job.failed' | 'job.skipped'
  entity      TEXT, entity_id INTEGER,
  detail_json TEXT                              -- agent.decision: {observed, reasoning}
);
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE INDEX idx_audit_action ON audit_log (action, at_utc);

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
  SELECT s.id, s.block_id, b.code AS block_code, b.name AS block_name, b.site,
         s.product_name_raw, s.rei_expires_at_utc
  FROM spray_log_current s JOIN blocks b ON b.id = s.block_id
  WHERE s.rei_expires_at_utc IS NULL
     OR s.rei_expires_at_utc > strftime('%Y-%m-%dT%H:%M:%SZ','now');
