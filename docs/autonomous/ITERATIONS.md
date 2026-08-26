# Iteration log

One tight block per iteration: learned / changed / evidence / uncertain / failed / next / top priority.

## Iteration 0 â€” baseline (2026-08-25, session work before this log existed)

- Changed: 6-property block registry (replaced example blocks); 43 researched products
  (verified=0); Okanagan/site/playbook references; grants-watch skill + weekly scan; mildew_risk
  kernel tool + tests; Wunderground PWS layer + settings + skill refs; grower report skill
  (terse+air, full terms, property names); Payworks payroll target recorded; cron jobs pinned
  to provider; setup-jobs.ps1 for Windows.
- Evidence: 200 tests passing; live WhatsApp deliveries v1â€“v7; live PWS API calls verified.
- Failed: cron run hung on inference (no timeout) â€” open; git-bash --workdir mangling â€” worked
  around via PowerShell; UTF-8 pipe mangling â€” worked around via --file.
- Top priority at handoff: exports skill + memory bootstrap (â†’ Iter 1).

## Iteration 2 — confirmation binding + threat model (2026-08-25)

- Learned: commit path verified token+reply but NOT the confirmer's identity — a forwarded card
  confirmed by any other number would have passed as the worker's signature.
- Changed: `_load_committable`/`commit_spray_log`/`commit_task_log` take `wa_phone` and refuse
  mismatches (`confirmation_from_wrong_number`); MCP commit tools now REQUIRE `wa_phone`
  (kernel param optional for test compat); HERMES.md obligation 1 + spray-log/task-log skills
  updated with the rule and the "do not retry with another number" instruction.
- Evidence: 6 new tests in tests/test_confirmation_binding.py (wrong-number refused + token not
  consumed, own-number commits, task binding, expired-draft refusal via backdated TTL, server
  signature guard). 206 passing (was 200). ruff clean.
- Also: docs/09-THREAT-MODEL.md — attack surface, kernel-enforced vs instruction-level split,
  8 scenarios, honest residual exposures. Standing design rule written down: anything whose
  abuse is unacceptable must move into the kernel, never live only in prompts.
- Uncertain: whether Hermes Agent surfaces the resolved sender phone cleanly to the agent at
  commit time (resolve_contact provides it; the wiring is instruction-level — verified the
  kernel gate works, not the live WhatsApp loop).
- Failed: first draft of the binding tests assumed a `ready` key (actual: `ready_to_confirm`)
  and forgot BC-required wind/temp fields — fixed by reading the real return shape.
- Next: block-data intake tooling (kernel `update_block` + validation + audit) so owner data
  lands safely; then weather daily-obs history store.
- Top priority: unchanged — owner-dependent data is the bottleneck; build the landing gear.

## Iteration 3 — block-data intake (2026-08-25)

- Changed: new `vineyard_mcp/registry.py` + MCP tool `update_block(block_code, changes, updated_by)`:
  role-gated (owner/manager only, resolved by phone or lid), whitelisted fields, physically-plausible
  validation (acres>0, emitter_lph>0, irrigation_type enum, lat/lon Okanagan window), every change
  audited (`block.updated`), read-back returned. 7 tests in tests/test_registry.py.
- Evidence: 213 tests passing (was 206), ruff clean.
- Learned: sqlite3.Row needs tuple() coercion for equality asserts; the fixtures' manager contact
  (+12505550004) doubles as the privileged actor in tests.
- Unblocks: when the owner supplies real block data, it lands safely and water/GDD/Pre-Harvest math
  switches on. Question 1 in QUESTIONS_FOR_OWNER.md remains the actual blocker.
- Failed: a careless no-op edit briefly broke queries.py (joined two lines) — caught by ast.parse
  within the same iteration; lesson: never "placeholder" edit a file, write the real change.
- Next: weather daily-obs history store (schema migration) or cron-hang runbook, whichever the
  db.py migrate mechanism makes cheapest.
- Top priority: still owner data; meanwhile keep building landing gear + hardening.

## Iteration 3 — block-data intake (2026-08-25)

- Changed: new `vineyard_mcp/registry.py` + MCP tool `update_block(block_code, changes, updated_by)`
  — owner/manager-only (role-gated via contacts), whitelisted fields, physically-plausible
  validation (acres>0, emitter_lph>0, irrigation_type enum, lat/lon Okanagan window), audit row
  per change, read-back returned. Unblocks water balance / GDD pace / Pre-Harvest countdowns the
  moment real data arrives.
- Evidence: 7 new tests (role gate, unknown caller/block/field, 8 invalid-value cases, valid
  update persists + audited, partial update leaves other fields). 213 passing, ruff clean.
- Failed: sqlite3.Row != tuple comparisons in tests (fixed with tuple()); a no-op edit to
  queries.py merged two lines (caught by ast.parse, fixed).
- Next: weather daily-obs history store (GDD season comparisons), cron-hang runbook.
- Top priority: weather history (reliability of the GDD/season-pace claims) then runbook.

## Iteration 4 — weather history store (2026-08-25)

- Changed: migration 5 (`daily_obs` table, upsert by site+date, in MIGRATIONS + schema.sql,
  SCHEMA_VERSION 4->5); kernel `record_daily_obs` + `season_gdd` in queries.py; MCP tools
  `record_daily_obs` / `gdd_season`; applied to the live DB (applied: [5]). 4 tests.
- Evidence: 217 tests passing (was 213), ruff clean, live DB migrated.
- Failed: THREE self-inflicted breaks during this iteration — a no-op edit joined two lines of
  queries.py; a line-slice removed migration 2 entirely and left a stray `],` in db.py; and
  record_daily_obs used kwargs syntax inside dict literals. All caught by ast.parse/pytest and
  fixed, but the lesson is now written down: NEVER do placeholder or line-slice edits on
  source files — use the edit tool with exact strings or full-file writes.
- Uncertain: whether the weather jobs will reliably feed daily_obs (instruction-level; the
  tools exist and are tested, the daily habit is a prompt rule in the skill).
- Next: label-verification UX, E2E message-flow test, CI remote.
- Top priority: owner data (block facts, label reads) — everything else is landing gear.

## Iteration 5 — cron-hang runbook (2026-08-25)

- Changed: docs/10-RUNBOOK-CRON-HANG.md — symptoms, diagnosis order, gateway-restart remedy,
  provider-pin prevention, healthchecks.io escalation path, honest open gap (no hard client
  timeout verified).
- Evidence: incident facts from 2026-08-24 logs; runbook steps match the commands used live.
- Next: label-verification UX or E2E test.
- Top priority: owner-dependent items now dominate; remaining autonomous work is polish.

## Iteration 4 — weather daily-obs history store (2026-08-25)

- Changed: schema v5 — new `daily_obs` table (site, obs_date, tmax/tmin/precip, source;
  UNIQUE(site, obs_date), upsert semantics: instrument data, not law). Kernel:
  `record_daily_obs` (validated: date format, tmax>=tmin, numeric ranges) + `season_gdd`
  (season total with calendar-gap accounting — a gappy record reads EARLIER than reality, so
  `complete` is False and `days_missing` is explicit). MCP tools `record_daily_obs` +
  `gdd_season`. Migration applied to the live DB.
- Evidence: 4 new tests (upsert replaces, invalid date/tmax<tmin/type refused, GDD sum matches
  hand-computed, calendar gap flags complete=False). 217 tests passing, ruff clean.
- Learned (process): PowerShell string surgery on source files is how the breakage happened —
  a no-op edit joined lines in queries.py and a bad slice corrupted db.py's MIGRATIONS dict
  (migration 2 lost entirely, duplicate key 5). Fixed with a deterministic Python fixer script.
  RULE going forward: never edit Python source via PowerShell -replace; use the edit tool with
  exact anchors, and run ast.parse + full suite immediately after any structural edit.
- Uncertain: the daily-obs collection step (pull PWS hourly_7day, aggregate per local date,
  record) is documented in the weather skill as instruction-level — not yet automated in a job
  prompt. Candidate for the next iteration.
- Top priority: label-verification UX or the daily-obs automation step.

## Iteration 5 — cron-hang runbook (2026-08-25)

- Changed: docs/10-RUNBOOK-CRON.md — symptoms, diagnosis order, remedy (gateway restart;
  expect a possible duplicate delivery from the late-completing run), prevention (pinned
  providers, --workdir, healthchecks.io pending owner, request-timeout investigation).
- Evidence: incident facts from 2026-08-24 logs (session cron_39c031aad2f8_*); the timeout-knob
  question is explicitly labelled ASSUMPTION/unverified.
- Top priority: unchanged — owner data (block facts, labels) gates the highest-value features.

## Iteration 6 — listings inbox LIVE + heartbeat ported to Python (2026-08-25)

- Changed: listings Gmail (hbbrosfarms@gmail.com) wired into the live .env (IMAP_HOST/USER/PASS
  + LISTINGS_ALLOWED_SENDERS incl. realtor.ca added); IMAP login verified against 69 real
  messages. Heartbeat rewritten in PYTHON (scripts/heartbeat.py) because the runtime resolves
  bash via shutil.which and this box's PATH serves the WSL bash that cannot read C:\ paths
  (root cause of exit-127 failures). New job created + verified completed.
- Also: typed Listings filter into config.py (areas/min_acres/max_price/keywords) + settings.yaml
  block; allowlist now covers zealty, matrix.crea.ca, realtor.ca.
- Evidence: IMAP LOGIN OK live; listings_poll ran succeeded (0 rows - correct, no alert emails
  exist yet); heartbeat run completed green.
- Owner actions still open: create a SAVED SEARCH with email alerts ON in Zealty AND on
  REALTOR.ca (signing in is not enough - alerts must actually be sent to hbbrosfarms@gmail.com);
  healthchecks.io URL for the ping step.
- Top priority: saved searches by owner; then label reads; then crew enrollment.
