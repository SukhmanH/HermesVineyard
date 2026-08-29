# Autonomous work — prioritized backlog

Impact-ranked. Prune completed items. Each item: what + why it matters + what it needs.

## P0 — highest impact, owner-independent

- [x] **`exports` skill missing but referenced by 3 cron jobs** — created 2026-08-25 (Iter 1).
- [ ] **Prompt-injection threat model + tests** — WhatsApp inbound is an untrusted input path
      straight into an agent with kernel write access. Threat model doc + tests for the gates
      that must hold (resolve_contact, confirm-token, ALTO/STOP, template-only output).
- [ ] **CI gate** — repo has no remote yet (FACT, checked 2026-08-25); add GitHub Actions
      workflow (ruff + pytest) so it's ready the day it's pushed.
- [ ] **Block-data intake flow** — kernel tool for owner/manager to update block acres/variety/
      irrigation metadata with validation + audit. Unblocks water balance, GDD pace, Pre-Harvest
      countdowns. Build now so owner data lands ready (data itself needs owner: see QUESTIONS).
- [ ] **Weather daily-obs history store** — weather_cache keeps latest per site only in
      practice; GDD season comparisons and mildew-model validation need a `daily_obs` table +
      a small fetch step in the weather ladder. Schema change → use schema_version migrate path.

## P1 — reliability / rigor

- [ ] **Cron-hang runbook + timeout config** — one production incident: inference call hung
      20+ min, no client timeout. Research Hermes Agent timeout/retry knobs (source at
      %LOCALAPPDATA%\hermes\hermes-agent), configure, write runbook, add healthchecks.io step
      (needs owner URL — QUESTIONS).
- [ ] **Label-verification UX** — verify_product exists but the physical procedure (read PCP +
      REI off container → who → audit) isn't a guided flow. Tighten skill + tests.
- [ ] **Kernel correctness audit** — line-audit spray_status/resolve_block/drafts TTL/timezone
      edges (fixed -7 offset in build_exports.py is a latent DST bug: TZ is hardcoded PDT).
- [ ] **E2E message-flow test** — inbound → resolve → draft → present → confirm → commit as a
      single integration test against a temp DB.

## P2

- [ ] Punjabi/Spanish voice paths tested live (needs runtime + voices).
- [ ] Windows-vs-Ubuntu deployment parity doc (docs assume Ubuntu Dell; reality is Windows).
- [ ] Payworks CSV/import format research (if Payworks supports file import, match it exactly).
- [ ] README refresh for new contributors.

## Done

- [x] exports skill (Iter 1, 2026-08-25)

## Block-data intake (added 2026-08-25, Iter 3)
- [ ] Kernel `update_block(code, fields, updated_by, role)` � manager/owner-only, validated
      (acres>0, irrigation_type enum, emitter_lph>0, vines_per_acre>0), audited to audit_log,
      returns the read-back (set_fruit_target pattern). Unblocks water/GDD/Pre-Harvest math.

## Done (2026-08-25, iterations 1-5)
- [x] exports skill; CI workflow; prompt-injection threat model (docs/09) + confirmation
      binding (kernel + MCP + tests); block-data intake (registry.update_block + MCP + tests);
      weather history store (daily_obs migration + record/gdd tools + tests, live DB migrated);
      cron-hang runbook (docs/10); autonomous memory files.

## Done (2026-08-25, iteration 6)
- [x] Listings inbox LIVE (Gmail IMAP + allowlist incl. realtor.ca + typed filter)
- [x] Heartbeat ported to Python (WSL-bash path bug) + verified green
- [x] healthchecks.io dead-mans switch wired and ping verified
- [ ] Owner: Zealty/REALTOR.ca saved searches with email alerts ON (signing in is not enough)
