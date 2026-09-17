# Vineyard system audit — consolidated findings
Date: 2026-09-07. Repo: /home/waris/hermes-vineyard @ 265 tests passing, working tree clean.

Every item below was reproduced by executing code against a copy of the database or the
live read-only tables. Nothing here is inferred from reading alone. Probe scripts:
`/tmp/vineyard-audit/`, `/tmp/matauditx/`, `/tmp/vaudit/`.

**None of these are covered by the existing 265 tests.**

---

## P0 — fix before the next spray

### 1. The gust gate is inert on 100% of live forecast data
`weather_math.py:80-81` — `if gust is not None and gust > cfg.gust_max_kmh`.
Null gust = no veto. Verified against the live DB this morning:

    oliver    | ECCC Osoyoos   20260907T120112Z | hours 24 | gust-null 24
    naramata  | ECCC Summerland 20260907T120149Z | hours 24 | gust-null 24
    penticton | ECCC Penticton  20260907T120203Z | hours 24 | gust-null 24

ECCC never populates `gust_kmh`. The gust limit has therefore never once fired in
production. Today's spray verdict of YES was produced with the drift guard switched off.
Fix: treat missing gust as unknown, not as calm — degrade the verdict or say so out loud.

### 2. Append-only compliance tables can be silently rewritten
`db.py:34-36` sets WAL / foreign_keys / busy_timeout but **not `recursive_triggers`**.
SQLite does not fire `BEFORE DELETE` triggers for the implicit delete inside
`INSERT OR REPLACE`, so the append-only guarantee is bypassable on `spray_log`,
`audit_log`, `fruit_samples`, `messages_raw`. Verified both ways:

    recursive_triggers=False: TAMPER SUCCEEDED -> ('TAMPERED', 999.0)
    recursive_triggers=True:  TAMPER BLOCKED   -> spray_log is append-only

Fix is one line in `db.py`: `PRAGMA recursive_triggers = ON`. Confirmed to close it.

### 3. Unparseable date/time silently yields `rei_expires_at_utc = NULL`
`compliance.py:590-600`, enabled by `_validate_spray` (283-286) regex-checking `HH:MM`
only and never validating `log_date`. `rei_active` reads NULL as *clear* rather than
*unknown*. The stated principle is "fail safe to NO"; NULL currently means YES.
A worker walks into a sprayed block.

### 4. Negative `label_rei` accepted — REI expires before the spray began
`compliance.py:351-353` assigns `rei_hours` with no validation, while `verify_product`
(957-958) correctly rejects the same value.

    label_rei=-48 -> COMMITTED, end 2026-09-06 10:00 local -> rei_expires_at_utc 2026-09-04

### 5. `draft_correction` is the largest hole
It copies a row and applies arbitrary changes without re-running resolution or
validation. Demonstrated: correcting record A can make an *unrelated* block's live REI
vanish, and mark a different record superseded in the legal register.

---

## P1 — wrong numbers presented to the grower as fact

### 6. ~~Water-balance run hours are ~4x too low~~ — WITHDRAWN, NOT A BUG
**Retracted 2026-09-07 on re-check.** The code is correct.
1 mm over 1 acre = 4,046.86 L; 10 mm = 40,469 L; at 8,000 L/h = **5.06 h**, and the tool
reported 5.1. `maturity.py:386-392` derives the constant correctly and computes
`lph_per_acre = emitter_lph × emitters_per_vine × vines_per_acre` — explicitly **per acre**.

My original sanity check compared that against "a realistic 2,000 L/h", which is not a
per-acre figure. 2 L/h emitters × 2 per vine × 2,000 vines/acre = 8,000 L/h per acre, which
is mid-range for Okanagan drip (normal range ~3,000–17,600). I compared incompatible units
and called correct code wrong.

Confirmed against today's live report: 15.7 mm → 63,500 L/acre, true value 63,536 L. Correct.

**Lesson for this audit: verify the units of the yardstick before trusting the discrepancy.**

### 7. Cross-season ripening rate leak → absurd harvest projections

    brix_per_day 0.001, rate_span_days 366 -> projected_date "2031-01-24"

The rate is computed against a sample from the *previous* season. Also:
- two samples on the same day silently kill the rate (`brix_per_day: null`)
- a future-dated typo (2027) gives `sample_age_days: -400`, `sample_stale: false`
- non-ISO `sampled_on` ("2026-9-5") is accepted, then string-sorted, so the "latest"
  sample is wrong (true latest 2026-10-01 @ 24.5 Bx was ignored)

### 8. Over-ripe fruit raises no flag
A target with only `target_brix_max` never computes a gap: fruit **3.5 Bx over the
contract max and rising 0.36/day** produced `brix_gap: null` and zero notes.

### 9. `irrigation_vs_ripening` blind to existing targets
Reported "no contract target on file for this block — purely a vine-health call"
for a block that **does** have a target and is 3.0 Bx below it.

### 10. Rotation/resistance tracking is wrong twice over
- `last_products` indexes the *unfiltered* rows list → reports products not in the run
  (got `['Home-made sulphur mix','Microthiol']`, true run `['Microthiol','Kumulus']`)
- FRAC runs are counted across *different target pests*, inflating "consecutive" to 3
  and flagging `concern: high` on unrelated applications

### 11. `spray_options` offers products with no registered pest for anything
"Generic Oil" (`target_pests` NULL) came back `usable: true` for powdery mildew — and
for grape phylloxera. Off-label recommendation.

### 12. `task_cadence` median is the upper element
`[2,10,30,40]` → reported 30, true median 20.

---

## P2 — operational / data integrity

13. **`silent_workers` uses a UTC cutoff against local dates.** Same question flips
    answer at the UTC rollover: midday run `silent=[]`, evening run `silent=['Ana']`.
14. **`job_start` dedupe is a LIKE against `detail_json`** and is TOCTOU-racy — two
    concurrent claims both returned `proceed: True`. The brief gets sent twice.
15. **Listings: `notified` is set to 1 on the interrupt path**, so urgent listings are
    *absent* from `get_situation`'s new-listings view — only digest ones show.
16. **Listings parser corrupts titles**: `'000 12.5 acres vineyard 1970 Sutherland Road…'`
    (price fragment eaten into title) and `db_write` stores that title into **both**
    `title` and `address`.
17. **`render()` KeyError on missing `why`**, and `build_report` raises
    `TypeError: '>' not supported between int and NoneType` when `new_price` is None.
18. **`seed/fruit_targets.csv` is a header with zero rows** — import reports
    "0 rows processed" and moves on. Every harvest target is therefore missing, which is
    why #9 fires. Blocks are seeded with codes CAS/H97/NAR/RUST/TUC/UB.
19. **No `subprocess` timeouts** in the notes path — verified a call blocking past 6s.
20. **`get_situation` issues 12 queries per call**, one weather SELECT per site.
21. **Backups: 6-day gap and the WAL is not captured** — a restore silently loses
    recent commits. `spray_log` and `task_log` are currently empty; block acreages are
    0.0 across the board.

---

## Recommended order

1. `PRAGMA recursive_triggers = ON` (#2) — one line, closes audit tampering.
2. Gust-null handling (#1) — currently affects every spray decision made.
3. REI validation: reject bad dates, reject negative REI, treat NULL as unknown (#3,#4).
4. Seed the real fruit targets (#18), which unblocks #9.
5. The rest in P1/P2 order.

*(#6 was withdrawn on re-check — see above. It was my unit error, not a defect.)*
