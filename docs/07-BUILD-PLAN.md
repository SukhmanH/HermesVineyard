# 07 — Build Plan (for the implementing agent, Opus 5)

You are building the **compliance kernel** for a Hermes Agent deployment, and wiring the runtime
around it. You are not building "Hermes" — Hermes is the Nous Research agent, already written.
Read docs/01–05 first; they are the spec, and read `HERMES.md`, `SOUL.md` and `.hermes/skills/`
too, because those are the behaviour spec and they already exist (§0).

This file is your task list. Work milestone by milestone; each has acceptance criteria — do not
move on until they pass.

Re-architected 2026-08-20 onto [Hermes Agent](https://hermes-agent.nousresearch.com), then
**narrowed again 2026-08-20 by docs/01 §D9** after verification against v0.20.4 showed Hermes has
`execute_code` and `terminal`.

**You are not writing a WhatsApp client, an LLM client, a scheduler, or a web server** — Hermes
Agent provides all four. **Nor are you writing weather, listings, export, or report modules** —
Hermes does those itself (§D9). You are writing a **compliance kernel**, a set of **skills**, and
the **configuration** that binds them. That is a much smaller build than the original M0–M8.

## 0. Global conventions

- Python 3.11+, type hints everywhere, `ruff` clean.

**The control plane already exists in this repo — do not rebuild it.** Identity, context, skills,
config, triggers, and the install path were written alongside the plan (§D10). Read them first;
they are the spec for how Hermes behaves, and several answer questions this document only gestures
at.

  ```
  SOUL.md                 ✔ EXISTS — identity. bootstrap.sh copies it to ~/.hermes/SOUL.md
  HERMES.md               ✔ EXISTS — project context file, auto-loaded EVERY session (§D10)
  .hermes/skills/         ✔ EXISTS — 12 skills: standing-duties self-improvement spray-log
                            task-log correction weather-fetch morning-brief eod-report
                            listings-triage exports onboarding punjabi-intake
  .hermes/skill-bundles/  ✔ EXISTS — dia.yaml (daily ops) · cumplimiento.yaml (compliance)
  hermes/config.yaml.example  ✔ EXISTS — full runtime config, annotated (see Appendix D)
  hermes/env.example          ✔ EXISTS — secrets only
  hermes/cron/setup-jobs.sh   ✔ EXISTS — all 11 triggers via CLI (confirm flags at M6)
  hermes/install/bootstrap.sh ✔ EXISTS — wires repo into an install, ends with /learn prompts
  hermes/install/heartbeat.sh ✔ EXISTS — asserts GATEWAY connected, no LLM in the loop
  ```

- Still to create — this is your actual build:
  ```
  vineyard_mcp/       __init__.py server.py config.py db.py compliance.py weather_math.py
                        ← compliance kernel ONLY. No weather fetching, no IMAP, no XLSX,
                          no report composition, no job runner. Those are Hermes's (§D9).
                          weather_math.py holds compute_spray_window() and nothing else.
  templates/          es.yaml en.yaml pa.yaml      ← copy strings from docs/05
                        ← pa.yaml is a P1 DELIVERABLE, not a stub (§D11). Gurmukhi script.
                          Build the product/pest glossary WITH the applicator, not from a
                          dictionary. No voice clip needed: speech is Google Cloud TTS
                          (docs/01 §D11 amendment) — credentials are the setup step instead.
  schema.sql          ← verbatim from docs/02 §2
  seed/               blocks.csv contacts.csv products.csv   ← columns per docs/02 §5
  config/settings.yaml                                    ← §Appendix A
  requirements.txt  requirements-agent.txt                ← §Appendix C
  scripts/dual-boot-setup.md
  tests/
  ```
- **Skills are the spec for agent behaviour, and they are already written.** When M4/M5/M7 below
  say "write the X skill", the skill exists — your job there is to make its tool calls real and
  to correct the skill where the implementation proves it wrong. Skill edits are staged for
  approval (`write_approval: true`), including yours.
- **Before adding any tool, apply the D9 test:** *would Hermes be unable to do this, or unsafe
  doing it, without us?* If neither, it is not a tool — it is a line in a skill. Weather fetching
  fails this test (Hermes can do it). `commit_spray_log` passes (unsafe without the gate).
  `compute_spray_window` passes (must fail safe when the model is impaired).
- Time: store UTC ISO-8601; schedule & display `America/Vancouver`.
- Error policy = docs/03 §2 job contract. No bare `except: pass` anywhere. Every send/receive
  writes `messages_raw`; every state change of note writes `audit_log`.
- Language: every outbound string comes from `templates/{contact.lang}.yaml`. No hardcoded
  user-facing text in Python or in skill prose.
- **Division of labour (docs/01 §D8 + §D9) — Hermes leads, and Hermes executes.** Build a tool only
  for a *guarded write* (what got committed, under §3's obligations) or a *calculation that must
  hold when the model is impaired* (`compute_spray_window`'s fail-safe). **Gathering a fact is not
  a reason to build a tool** — Hermes fetches, reads, parses, and computes for itself (§D9).
  Judgement was always Hermes's: what is worth sending, who needs to know, how to phrase it, what
  to do about something nobody anticipated. Only four behaviours are hard-enforced against Hermes —
  docs/01 §3 — and you may not add a fifth without a decision record.
- **Build broad, composable tools, not narrow ones.** `query_logs(filters)` beats five fixed report
  builders; `send_message(channel, text)` beats one function per message type. A narrow tool
  answers only the question you thought of. Every narrow tool you add is a decision you took away
  from Hermes — justify it or generalize it.
- MCP tools return **structured data and structured errors**, never prose.
  `{"error": "missing_field", "field": "rate_or_total"}` — Hermes makes that the next question.
  Tools never write user-facing sentences; templates and Hermes do that.
- **Every autonomous decision is logged.** Any tool that lets Hermes choose (send/don't send,
  nudge/skip, escalate) accepts a `reason` argument and writes `audit_log` with
  `action='agent.decision'` (docs/01 §3.1). A decision tool without a reason parameter is a bug.

## M0 — Bootstrap (no Hermes Agent yet)

> **M0 ✅ BUILT 2026-08-21**

Create the layout above; `config.py` loads `.env` + `settings.yaml` into typed settings; `db.py`
opens SQLite (WAL, foreign_keys ON), applies `schema.sql` if fresh. CLI:
`python -m vineyard_mcp init-db`, `import-seed <dir>`, `doctor`.

**Accept:** fresh clone → init-db → import-seed of example CSVs succeeds; `UPDATE` on `spray_log`
raises the trigger error and `DELETE` does too (prove append-only works); `doctor` reports DB path,
schema version, row counts, and exits non-zero if anything is missing.

## M1 — MCP server skeleton + Hermes Agent wiring

> **M1 ✅ BUILT 2026-08-21 — 22 tools registered, server verified over stdio**

**This milestone can be done on Windows today** — there is a native installer (§Verified §1), so it
does not block on the Dell or on Ubuntu.

- Install Hermes Agent:
  ```powershell
  iex (irm https://hermes-agent.nousresearch.com/install.ps1)   # Windows: bundles uv, Python
  ```                                                            # 3.11, Node, ripgrep, ffmpeg, Git Bash
  ```bash
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash    # Linux/macOS/WSL2
  ```
- `hermes model` — add 9router as a custom OpenAI-compatible provider (docs/01 §D7) and **pin a
  specific model**. `hermes doctor` must pass before going further.
- `server.py` exposes a stdio MCP server ✅ with a trivial tool (`ping`, `get_contacts`).
- Register in `~/.hermes/config.yaml` ✅ — note tools are exposed to the agent as
  `mcp_vineyard_<tool_name>`:
  ```yaml
  mcp_servers:
    vineyard:
      command: "python"
      args: ["-m", "vineyard_mcp.server"]
      timeout: 30
      tools:
        prompts: false
        resources: false
  ```
- Trim the tool surface with `hermes tools` ✅ and `agent.disabled_toolsets` ✅ — drop
  `image_gen`, `spotify`, `discord`, `homeassistant`, `browser`. Keep `terminal`, `code_execution`,
  `file`, `vision`, `tts`, `memory`, `session_search`, `cronjob`, `delegation`, `todo`, `messaging`,
  and `mcp-vineyard`. A smaller surface measurably improves routing accuracy — and under §D9
  `terminal`/`code_execution` are **not** optional.

**Accept:** `hermes doctor` clean; in a `hermes chat` session, "list your vineyard tools" enumerates
ours; calling `get_contacts` returns seeded rows; killing the MCP process surfaces a clean error
rather than a hang; `/reload-mcp` ✅ picks up a newly added tool without restarting the agent.

## M2 — WhatsApp gateway (group + 1:1)

- Pair via `hermes whatsapp` (Baileys, QR) ✅ on a dedicated test number — **never a personal
  number**, per docs/01 §D1. Session state lands in `~/.hermes/platforms/whatsapp/session` ✅;
  `chmod 700` it and add it to the backup set.
- **Group support is CONFIRMED** ✅ — this was flagged scope-changing and it is resolved. Configure:
  ```yaml
  whatsapp:
    unauthorized_dm_behavior: ignore     # override the "pair" default — enrolment is a manager's job
    send_read_receipts: true
    reply_prefix: ""
  ```
  plus `group_policy: allowlist`, `group_allow_from: [<crew group JID>]`, `require_mention: false`
  ✅. Capture the crew group's JID at pairing time and write it to `settings.yaml`
  `channels.crew_group_jid`. **Known gap:** group gating is per-group, not per-sender
  ([#41371](https://github.com/NousResearch/hermes-agent/issues/41371)) — so keep compliance
  interviews 1:1, where the sender is matched to `contacts`.
- Run the gateway as a service — `sudo hermes gateway install --system` ✅ on the Dell, `hermes
  gateway run` in dev. **Cron does not tick without it** (docs/03 §0).
- `log_message` tool: persist every inbound and outbound message to `messages_raw` (docs/02),
  including `chat_jid` and `is_group`, deduped on `wa_message_id`.
- Implement the keyword fast-path (docs/05 §6) so `CLIMA/AYUDA/HOLA/ALTO/EXPORT/CORREGIR` and the
  emergency keywords resolve **before** any LLM call.
- Implement the etiquette constraints of docs/03 §4 as code, not guidance: refuse to send to a
  contact with no `consent_ts_utc` unless a manager enrolled them; stagger 1:1 fan-out; suppress
  non-safety messages for `ALTO/STOP` contacts.
- **Voice in** ✅ — inbound `.ogg` voice notes are auto-transcribed (faster-whisper / Groq /
  OpenAI). **Choose faster-whisper for Spanish: local, free, no key**, and pin `large-v3` — the
  small model is materially worse. Persist the transcript to `media.transcript`: the transcript,
  not the audio, is what the extraction saw, so it is the audit-relevant artefact. Spot-check
  accuracy on real Mexican-Spanish vineyard vocabulary before relying on it — this is the input to
  compliance records, and «azufre» misheard is a wrong record.
- **Voice in, PUNJABI — §D11.** faster-whisper is rough on Punjabi (~55% WER, errors on numbers,
  product names and units). **Pin `large-v3`; the small model is ~87% and unusable.** This is
  acceptable only because the applicator types SPRAY reports in English — the legally binding path
  never touches Punjabi ASR. Punjabi voice carries task logs and conversation, where an error
  costs a correction turn. Interview one field at a time with numbers read back
  (`.hermes/skills/punjabi-intake/`). **Acceptance is a real recording**, not a benchmark: have a
  Punjabi worker record five task reports and measure the correction turns.
  Optional upgrade, deliberately not required: Sarvam/ElevenLabs via `execute_code` (~$3–10/mo)
  if correction turns climb or workers start routing around Hermes to a manager.
- **Voice out** ✅ — configure `text_to_speech` with **Edge TTS** (free, no key; the nine other
  providers are all paid) and a Spanish voice. **Edge TTS has no `pa-IN` voice** — verified against
  the full voice list. Spoken Punjabi is therefore synthesized by `tools/punjabi-tts/speak.py` —
  **Google Cloud TTS, voice `pa-IN-Chirp3-HD-Puck`** (replaced self-hosted IndicF5 on 2026-08-23:
  47–79 s per novel render and poor quality made it unusable; see docs/01 §D11 amendment). Free
  under 1M chars/month; needs one-time `gcloud auth application-default login`.
  **Do not use `facebook/mms-tts-pan` — CC-BY-NC 4.0, non-commercial**, disqualified on the same
  grounds §D3 rejected Open-Meteo's free tier. Cache synthesized audio by message hash so templated REI
  warnings are not re-generated every time (the tool does this itself); output is WAV, and
  `[[audio_as_voice]]` ✅ promotes it to a native WhatsApp voice bubble — use it, a voice bubble is
  what a worker expects. Send the morning brief and REI warnings as voice **in addition to** text,
  never instead of it. Per-contact via `contacts.voice_replies`; ask each worker during onboarding.
- **Vision** ✅ — `vision_analyze` for two flows: product-label photos → trade name + PCP number
  (feeds the `verified` flow), and pest/disease photos → identification + manager flag. Configure
  `auxiliary.vision` to a model the 9router endpoint serves. Hermes must state its confidence and
  **never let a photo alone set a `verified=1` REI** (docs/01 §3.4).

**Accept:** inbound "hola" from a test phone lands in `messages_raw` and gets the Spanish greeting;
a group message is received with `is_group=1`; a skill posts to the group; duplicate delivery of
the same message id processes once; `ALTO` suppresses the EOD nudge but not an REI alert; a send to
a non-consented number is refused and audit-logged.

## M3 — Compliance tools (`compliance.py`) — the core

> **M3 ✅ BUILT 2026-08-21 — 68 tests green, all four obligations asserted**

This milestone is the reason the project exists. Everything here is deterministic Python.

- `draft_spray_log(wa_phone, extraction) -> {confirm_token, draft, missing_fields}`:
  merge extraction into any open draft; resolve block codes fuzzily ("el 3", "bloque tres" → B3);
  match products; auto-fill applicator from sender, acreage from block, weather from
  `weather_cache` at (block site, start_time); REI/PHI from product **only if `verified=1`**, else
  add `label_rei` to `missing_fields` (docs/05 §2). Required for spray: product, block, rate OR
  total, start/end.
- `commit_spray_log(confirm_token)`: single INSERT, computes `rei_expires_at_utc`, returns the
  committed row **and** the REI broadcast payload. **Refuses** any token that is unknown, expired,
  already consumed, or whose draft is not `awaiting_confirm` (docs/01 §3.1).
- `draft_task_log` / `commit_task_log`: analogous (block, hours, workers).
- `draft_correction(log_id, changes)`: pre-fills from the old row, per docs/02 §3.
- `find_recent_logs(wa_phone, limit)`: for the correction flow.
- Drafts older than 24 h expire; a skill sends the polite Spanish note.
- Emergency detection and manager relay per docs/03 §6.

**Accept:** ≥15 pytest cases with no LLM in the loop — commit without a token fails; commit with a
consumed token fails; commit with `missing_fields` non-empty fails; an unverified product never
yields an REI; a correction produces a superseding row and leaves the original byte-identical; the
`UPDATE` trigger blocks a direct write attempt; `rei_expires_at_utc` is correct across a DST
boundary.

## M4 — Spray-log skill (`skills/spray-log/SKILL.md`)

The procedure the agent follows, in prose, calling M3's tools:

1. Extract what the worker said into the tool's expected shape. Colloquial Mexican Spanish, often
   voice-note transcripts with no punctuation, frequent misspellings ("asufre"). **Never invent a
   value** — omit it and let the tool report it missing. Date defaults to today only if the message
   uses past tense of today ("hice", "terminé") with no other date cue.
2. Call `draft_spray_log`. Ask the returned `missing_fields` as **bundled** questions (≤2 messages
   typical), using the wording in docs/05 §2.
3. When `missing_fields` is empty, render the confirmation card verbatim from the template. Wait.
4. On «SÍ» → `commit_spray_log(confirm_token)` → send the ack, then post the REI warning to the
   group. On anything else → treat as a correction to the draft, re-draft, re-confirm.

Also write `task-log`, `correction`, and `onboarding` skills the same way. Include the vineyard
glossary (azufre=sulfur · oídio/cenicilla=powdery mildew · poda=pruning · deshoje=leaf removal ·
desbrote=shoot thinning · riego=irrigation · hilera=row · racimo=cluster · cuadrilla=crew ·
brotes=shoots · caldo=spray mix · mochila=backpack sprayer) in the translation skill.

This is the one flow where procedure is tight, because it ends in a legal record. Even here Hermes
keeps latitude over *wording, bundling, order, and register* — accepting a rambling voice note
whole, skipping a question it can already infer from context, adapting to a worker who answers in
fragments. What it does not get latitude over is the four obligations in docs/01 §3.

**Accept:** scripted end-to-end against a live agent session: "hice el spray de azufre en bloque 3"
→ ≤2 follow-ups → confirm → correct `spray_log` row, REI posted to group, `raw_message` preserved
verbatim. Run the M3 fixture set through the agent and diff the **committed row values** against the
tool-level expectations — divergence there is a skill bug, not a tolerance. Divergence in *phrasing*
between runs is expected and fine; do not write tests that pin the Spanish wording.

## M5 — Weather: one function + one skill (`weather_math.py` + `weather-fetch` skill)

> **M5 ✅ BUILT 2026-08-21 — `compute_spray_window()` with 19 fail-safe tests green, site codes resolved, and the full ECCC path verified end to end against live data.**
>
> Live testing caught a real bug the fixture tests could not: ECCC publishes **UTC**, and the daylight filter was applied to UTC hours - producing a confident "05:00-09:00" spray window that was really 22:00-02:00 Pacific, on a day with 25 km/h daytime wind. `compute_spray_window` now takes `tz` and converts before any hour-of-day reasoning. **Fixture data shares your assumptions; live data does not.**

**§D9 splits this milestone in two.** Hermes fetches; we compute the verdict.

**Ours — `weather_math.py`, the only Python here:**

`compute_spray_window(hourly, cfg, product=None) -> verdict` per settings §spray_window: contiguous
runs within day bounds where wind ∈ [min,max], gusts ≤ max, temp ∈ [min,max] (product `max_temp_c`
overrides the ceiling), precip-prob ≤ max through run + rainfast hours. Longest run ≥
`min_window_hours` → YES + hours; else NO + dominant reason (for the «motivo» string). Accepts
`source` and `age_hours`; **returns NO whenever data is stale or wind is missing** — fail-safe is a
property of this function, not of the prompt (docs/01 §3, §D9).

This is deliberately a *pure function over already-fetched hours*. It does not know what ECCC is.
That is what lets Hermes feed it data from any rung of the ladder — or a rung nobody wrote.

**Hermes's — the `weather-fetch` skill.** Written as procedure, not code. It tells Hermes:

- The three sites and their ECCC citypage XML URLs (resolved from the MSC site list at build time
  and stored in `settings.yaml` — **this is the knowledge we supply**, docs/01 §D9).
- The degrade ladder (docs/03 §3): ECCC → Open-Meteo *only if* `OPEN_METEO_API_KEY` is set
  (commercial licence — docs/01 §D3) → last cache <24 h marked STALE → the apology message.
- To fetch with `execute_code`, normalize to the shape `compute_spray_window` expects, call it per
  site, and write both the raw payload and the verdict to `weather_cache`.
- That it may **not** soften the returned verdict, and must name the source and any caveat.

**Accept:** unit tests on `compute_spray_window` with fixture hour-lists — known windy/hot/rainy
days produce expected verdicts; stale/missing-wind inputs yield NO regardless of how good the rest
of the data looks. Then, live: Hermes fetches all three sites unaided and caches them; blocking
ECCC at the network level produces a STALE-marked cache entry and a fail-safe NO, not a crash and
not an invented forecast.

## M6 — Scheduled triggers + agent autonomy (Hermes Agent cron)

**Read docs/03 §0 first** — verification changed how this milestone works. There is no `jobs.py`:
jobs live in `~/.hermes/cron/jobs.json` ✅, created with `hermes cron create` / the `cronjob` tool,
and are ticked **by the gateway**, not by a CLI session. The single largest operational risk in the
project is a gateway that is not running, so M6 is not done until
`sudo hermes gateway install --system` ✅ survives a reboot.

Set the timezone **globally** — `HERMES_TIMEZONE` / `timezone:` in config ✅ — because per-job
timezones do not exist upstream. Verify the Dell's clock and TZ; a box in UTC fires the 06:00 brief
at 23:00 the previous night and nothing warns you.

Idempotence stays ours: `job_start(job, local_date)` and `job_finish(...)` MCP tools own it, never
the agent's memory and never the runtime. Retries / audit / owner alert / healthcheck ping per the
docs/03 §2 contract are implemented in those tools plus the skill, not in a Python decorator around
a job function — there are no job functions any more.

Use the runtime's chaining rather than reinventing it: `context_from: [weather_fetch]` ✅ feeds the
06:00 brief its forecast, `continuity: true` ✅ gives `midday_recheck` and `listings_poll` their own
previous output. `heartbeat` and `nightly_export_backup` should use `--no-agent --script` ✅ — no
judgement is required and they must keep working when the LLM provider is down.

**A trigger hands Hermes a situation, not a script** (docs/03 §1). The tool returns the facts —
forecast, verdict, active REIs, who reported today — and Hermes decides what, whether, and to whom
to send. Build `skip_job(job, reason)` alongside `job_finish` so "decided not to send" is a
first-class, logged outcome rather than a silent no-op indistinguishable from a crash.

Also in this milestone, the machinery that makes autonomy real:

- **`log_decision(action, observed, reasoning)`** — the `agent.decision` audit path (docs/01 §3.1).
  Wire it into every discretionary tool as a required `reason` argument.
- **`query_logs(filters)`** — the broad read tool Hermes composes for anomaly detection, reports,
  and questions nobody anticipated. Filters over date, worker, block, product, task type.
- **`get_situation(scope)`** — **load-bearing, see docs/03 §1.2.** Cron runs start in a fresh
  session with no chat context ✅ (confirmed v0.20.4), so each trigger's first call assembles the picture it reasons
  over: active REIs, today's logs, silent workers, recent `agent.decision` rows, open drafts,
  degraded sources. A standing duty absent from every situation payload is a standing duty Hermes
  can never catch — this tool, not prompt wording, is what makes docs/03 §1.1 real.
- **Standing-duties skill** (`skills/standing-duties/SKILL.md`) — docs/03 §1.1. Written as
  *responsibilities with examples*, explicitly non-exhaustive, not a checklist to execute. Hermes
  consults it on every trigger and after significant conversations.
- **Subagent delegation** ✅ (`delegate_task`) — give Hermes a worked example: parse a listings
  backlog without blocking the crew conversation.
- **The learning loop** (docs/01 §3.2) — Hermes Agent's central mechanism; configure it, don't
  merely verify it:
  - `skill_manage` (create/patch/edit/delete/write_file/remove_file) ✅ — confirm distilled skills
    persist and reload on a later similar task.
  - **Project-local skills** ✅: this repo's `.hermes/skills/` is auto-discovered when Hermes runs
    inside it; run `hermes skills trust` once. `skills.external_dirs` ✅ is the alternative if
    Hermes will run outside the repo — pick one and document it.
  - **`skills.write_approval: true`** ✅ — **correction: this is GLOBAL, not per-skill.** There is
    no per-skill gate. Set it globally and accept the friction on open-tier skills; losing the gate
    on `spray-log` is a compliance failure and saving four seconds is not worth it (docs/01 §3.2).
    Review path is `/skills pending` → `/skills diff <id>` → `/skills approve <id>` ✅.
  - **`skills.guard_agent_created: true`** ✅ — scans agent-written skills for dangerous patterns.
    Under §D9 Hermes has `terminal`; turn this on.
  - **Version skills in git**, auto-committed nightly. The diff answers "what did Hermes teach
    itself this month" and makes a bad self-edit a one-command revert. `hermes backup` ✅ archives
    config + skills + sessions as a zip for the off-box copy.
  - Give the owner a review path: a monthly summary of new/changed skills in the monthly email, and
    a documented `git revert` runbook (docs/04 §7).
  - Consider **`/learn`** ✅ for onboarding knowledge — `/learn` against the BC IPM regulation page
    or a product label PDF produces a knowledge-base skill without anyone authoring it.

**Accept:** time-frozen tests fire each trigger; failure injection produces an owner alert plus an
`audit_log` row; re-running `morning_brief` the same day is a no-op; a degraded data source still
yields the degraded message rather than silence; a deliberate skip writes `agent.decision` with a
reason and is distinguishable from a failure in the audit log; a seeded anomaly (worker silent 4
days, block sprayed twice in 5 days, task logged inside an active REI) is surfaced by Hermes
without a dedicated tool existing for that specific check.

## M7 — Listings, reports & exports — **skills, not modules**

**No Python in this milestone.** Under §D9 all three are Hermes's, done with `execute_code`. What
you write is the knowledge and the standard, as three skills:

- **`listings-triage`** — read UNSEEN mail over IMAP from `LISTINGS_ALLOWED_SENDERS`, strip HTML,
  extract `{mls_number, title, price, acres, address, area, url}`, dedupe on `dedupe_key`, apply
  the area/acres filter from settings §listings, write to `listings`. Then the part that was never
  code anyway: decide whether anything here is worth interrupting the owner for today, or belongs
  in the EOD digest (docs/03 §1.1). Runs with `continuity: true` so it knows what it already saw.
- **`eod-report`** — compose per docs/05 §4 from `query_logs` + `rei_active` + new listings +
  anomalies; email backup over SMTP per settings §reporting. The template is a floor, not a ceiling
  (docs/01 §D8).
- **`exports`** — build workbooks with `openpyxl` via `execute_code`: nightly spray/task, weekly
  hours-by-worker, monthly compliance workbook **including SUPERSEDED flags and an audit sheet**
  (docs/02 §3/§6). The `EXPORT` command returns the workbook as a WhatsApp document — bare absolute
  paths in a skill response auto-deliver as media ✅; use `[[as_document]]` ✅ so Excel files
  arrive as real downloadable attachments rather than recompressed previews.

The compliance workbook's *contents* are a legal requirement, so the skill states the required
sheets and columns explicitly and the M3 fixture set is what proves them. Everything about *how*
the file gets built is Hermes's business.

**Accept:** fixture emails dropped in the test inbox (a Zealty alert, an MLS auto-email, an
irrelevant newsletter) → 2 listings inserted, newsletter ignored, re-poll inserts nothing. EOD for a
seeded day names every committed log, every active REI, and every seeded anomaly — assert on
**facts present**, not on wording (docs/01 §D8 makes phrasing variable by design; a golden-file text
test would be a bug). Monthly workbook opens in Excel with the required sheets, superseded rows
flagged, and an audit sheet.

## M8 — Ops & install

- `scripts/dual-boot-setup.md`: shrink the Windows partition (Windows Disk Management — built-in,
  safe, no third-party tool needed), install Ubuntu Server 24.04 into the freed space, GRUB dual-
  boots the two with Ubuntu as the default and a short timeout, sleep/hibernate disabled in BIOS.
  **The Windows partition and its files are never touched by the resize or the installer.**
- `scripts/install.sh`: Hermes Agent install (`curl … install.sh | bash`), **both** dependency sets
  from Appendix C, `vineyard-mcp` install, `hermes gateway install --system` ✅ (this is the
  systemd unit — do not hand-roll one), Tailscale join, seed import, `timezone` set to
  `America/Vancouver` ✅ **and the system clock verified**, healthchecks registration,
  `hermes skills trust` for the repo's `.hermes/skills/`. **No Caddy, no reverse proxy, no ufw
  inbound rules, no TLS — there is no inbound endpoint** (docs/01 §D6).
- **Backups are a cron job, not a script we maintain** (§D9): nightly SQLite `.backup`, a copy of
  `~/.hermes/platforms/whatsapp/session` ✅ (secret — `chmod 700`), `hermes backup` ✅ for
  config+skills+sessions, a git commit of the skills dir, and rotation per docs/02 §6. Hermes runs
  it; keep a `--no-agent --script` fallback so backups survive an LLM outage.
- `scripts/heartbeat.sh`: 15-min `--no-agent --script` job asserting **gateway connected**
  (`hermes gateway status` ✅), not merely process alive (docs/03 §7) — alert by **email** on
  gateway failure, since WhatsApp is what's broken. Must not require the LLM.
- Update docs/04 with any real deviations. Final end-to-end smoke test per docs/04 §5.

**Accept:** fresh partition → installer → QR pair → live round trip from a real phone; reboot the
Dell and confirm it boots straight into Ubuntu (no manual GRUB selection needed) and the service and
WhatsApp session come back unattended; **`hermes gateway status` reports connected after the reboot
and a cron job actually fires on schedule** — the reboot test is worthless without it (docs/03 §0);
kill the gateway and confirm the email alert fires; set the clock to UTC deliberately and confirm
the timezone check in the installer catches it.

## Phase 1.5 — folded into the core build

Voice-note transcription, Spanish voice replies, and vision were the original Phase 1.5. All three
are built into the runtime (docs/01 §7.1), so they are **configuration in M2**, not development
later. What remains genuinely next:

- **Longitudinal recommendations** (docs/01 §7.3) — seasonal baselines, scheduled comparison, and a
  delivery surface. `execute_code` ✅ already gives Hermes the means to answer such questions when
  asked; this milestone is about it asking *itself*, on a schedule, and telling managers what it
  found. Useful from season two.
- **Enable what the crew actually asks for.** Ship the core, watch a month of real use, then pick
  from docs/01 §7.2 (web search for label lookup, extra manager platforms, dashboard) based on what
  people request rather than what looks good on a roadmap.

## Verified capabilities (checked 2026-08-20 against Hermes Agent v0.20.4)

Every ⚠ from the original plan, resolved. **Re-check against the installed version** — upstream
moves fast — but these are no longer open questions, and three of them changed the build.

| # | Question | Result |
|---|---|---|
| 1 | **MCP integration** | ✅ `mcp_servers` in `~/.hermes/config.yaml`; **stdio and HTTP** both supported; auto-discovery at startup; tools registered as `mcp_<server>_<tool>`; per-server `tools.include`/`tools.exclude` with glob patterns; `/reload-mcp` works. Also OAuth, mTLS, parallel tool execution |
| 2 | **Cron** | ✅ but **three surprises** — see docs/03 §0. (a) Jobs live in `~/.hermes/cron/jobs.json` and are ticked **by the gateway, not the CLI**; (b) timezone is **global only** (`HERMES_TIMEZONE` → config → system), per-job TZ is an open upstream request; (c) delivery **is** targetable per job via `--deliver whatsapp` / `telegram:<id>` / `all`. Bonus: `--no-agent --script`, `context_from`, `continuity` |
| 3 | **WhatsApp groups** | ✅ **CONFIRMED — the scope risk is closed.** `group_policy: open\|allowlist\|disabled`, `group_allow_from` (group JIDs), `require_mention`. Session at `~/.hermes/platforms/whatsapp/session`, survives protocol updates unless unlinked. Voice notes auto-transcribed; TTS out as MP3. **Gap:** group gating is per-group, not per-sender ([#41371](https://github.com/NousResearch/hermes-agent/issues/41371)) |
| 3b | **Cloud API fallback** | ⚠ **Weaker than assumed.** `hermes whatsapp-cloud` is **DM-only in v1**; upstream recommends Baileys for groups. Migrating away from Baileys costs us the crew group, not just money (docs/01 §D1) |
| 4 | **Skills** | ✅ `~/.hermes/skills/` + `skills.external_dirs`. ⚠ **CORRECTION (2026-08-21, tested against a real install): `hermes skills trust` DOES NOT EXIST** in v0.20.4 — the subcommand list has no `trust`, and project-local `.hermes/skills/` is not auto-discovered. **Use `skills.external_dirs`**, which loads them identically (they appear as source/trust `local`, enabled). All 12 project skills verified loading this way. SKILL.md with YAML frontmatter, agentskills.io-compatible. Progressive disclosure: `skills_list()` → `skill_view(name)` → reference files. Invoked by `/skill-name`, stackable up to 5, bundles in `~/.hermes/skill-bundles/`. Plus `/learn` to build a skill from a URL, directory, or a described procedure |
| 4a | **`write_approval`** | ⚠ **CORRECTION — it is GLOBAL, not per-skill.** The two-tier design in docs/01 §3.2 is a review policy we operate, not a runtime feature. Resolution: enable it globally, plus `guard_agent_created: true` |
| 4b | **Autonomy** | ✅ Both real. `delegate_task` spawns isolated subagents with their own context and terminal; `skill_manage` creates/patches/edits/deletes skills and they persist. D8 stands as written |
| 5 | **Provider config** | ✅ Custom OpenAI-compatible endpoints supported — but the **schema differs from our sketch**: it is `model:` + a `providers:` map, not `provider:`. Env substitution via `${VAR}`. Credential pools with `round_robin`/`least_used` if we ever hold multiple keys. Use `hermes model` rather than hand-editing |
| 6 | **Memory isolation** | ✅ Better than hoped. `memory.memory_enabled`, `memory.write_approval`, and `agent.disabled_toolsets` all exist, and cron jobs already run context-free. Confirms §D2: memory is capped (~800 tokens) and **auto-compressed** at 50% of context — exactly why it cannot hold compliance facts |
| 7 | **9router** | ⏳ Owner-side. Reachability via Tailscale from the Dell; pin a reliable model (no `free`/auto combos for production Spanish extraction) |
| 8 | **ECCC** | ✅ **RESOLVED 2026-08-21, verified against live data.** Penticton `s0000772` (2 km). **Naramata and Oliver have NO station of their own** - substituted Summerland `s0000351` (6 km, across the lake) and Osoyoos `s0000397` (18 km, hotter pocket); owner to confirm against observed conditions. URL scheme **changed**: `dd.weather.gc.ca/today/citypage_weather/BC/<HH>/<TIMESTAMP>_MSC_CitypageWeather_<SITE>_en.xml` - hour-partitioned, timestamped, must list the directory. 24 hourly forecasts, **all carrying wind**, plus temp, `lop` (precip %), condition and warnings. Full mapping in `.hermes/skills/weather-fetch/references/eccc.md` |
| 9 | **BCMA** | ⏳ Pesticide application record form fields vs docs/02 §4 mapping — still to confirm against the current form |
| 10 | **Ban-risk guidance** | ✅ Upstream still says: dedicated number, no bulk/spam, no unsolicited outbound to people who haven't messaged first, keep the phone on the network. docs/03 §4 matches |

**Corrections found by building against a real install (2026-08-21):**

| # | Claim in the docs | What is actually true |
|---|---|---|
| A | `hermes skills trust` activates project-local skills | **No such subcommand.** Use `skills.external_dirs`. Verified: all 12 skills load, marked `local`/`enabled` |
| B | Hermes home is `~/.hermes/` | On Windows it is **`%LOCALAPPDATA%\hermes`** (`$HERMES_HOME`). Always resolve `$HERMES_HOME` rather than assuming `~/.hermes` — `bootstrap.sh` does |
| C | — | The stock `SOUL.md` shipped by the installer is a generic-assistant prompt. Replacing it is safe and is what makes §D10 real; back it up anyway |

**Three findings that changed the build:**
1. `execute_code` + `terminal` are real → **docs/01 §D9**, deleting `weather.py`, `listings.py`,
   `exports.py`, `reports.py`, `jobs.py`.
2. Cron is ticked by the gateway → the top operational risk, and the reason §7's heartbeat asserts
   gateway liveness rather than process liveness.
3. `write_approval` is global → the tiered-skill design is policy, not enforcement.

**Also new since the plan was written:** a **native Windows installer** (`install.ps1`, bundling uv,
Python 3.11, Node, ripgrep, ffmpeg, Git Bash). M0–M7 can therefore be built and tested on the
owner's existing Windows machine, and Ubuntu is needed only for M8 production hosting.

## Human action items (owner)

**The build does not block on any of these until the milestone shown.** Verification confirmed a
native Windows installer and that terminal chat exercises the whole system, so M0–M4 can be built
and tested on the owner's existing Windows machine with none of this in place (docs/04 §0).

| Needed by | Item |
|---|---|
| M1 | 9router reachable via Tailscale, or a fallback provider chosen |
| M3 | Real seed CSVs — blocks, contacts, products — and **label-verify each product's REI/PHI/PCP** (an unverified product yields no REI, docs/01 §3.4) |
| M2 (WhatsApp) | Dedicated prepaid SIM + WhatsApp registration; bot added to the crew group **as a participant**; capture the group JID |
| M5 | ECCC citypage site codes for the three sites |
| M7 | Gmail + app password; Zealty saved search; realtor MLS auto-email |
| M8 | The Dell freed, sleep/hibernate disabled in BIOS, **clock and timezone correct**; healthchecks.io account |

---

## Appendix A — `config/settings.yaml` (create verbatim, then tune with owner)
```yaml
sites:                       # ADJUST lat/lon to real vineyard centroids before go-live
  - {key: penticton, label: Penticton, lat: 49.499, lon: -119.594, eccc_citypage: TODO}
  - {key: naramata,  label: Naramata,  lat: 49.596, lon: -119.587, eccc_citypage: TODO}
  - {key: oliver,    label: Oliver,    lat: 49.183, lon: -119.552, eccc_citypage: TODO}
spray_window:
  wind_min_kmh: 3        # dead calm = inversion drift risk, not safe
  wind_max_kmh: 15
  gust_max_kmh: 25
  temp_min_c: 8
  temp_max_c: 28         # product max_temp_c overrides (sulfur ≈ 30 phytotoxicity)
  rain_prob_max_pct: 30
  rain_free_hours_after: 4
  min_window_hours: 2
  day_start_hour: 5
  day_end_hour: 21
frost:
  threshold_c: 2.0
  watch_windows: [{from: "03-01", to: "05-31"}, {from: "09-15", to: "11-15"}]
schedule:
  weather_fetch: "05:45"
  morning_brief: "06:00"
  midday_recheck: "12:00"
  eod_worker_nudge: "17:00"      # null disables
  eod_manager_report: "19:00"
  frost_watch: "20:00"
  nightly_export_backup: "21:30"
  listings_poll_minutes: 30
  weekly_hours_export: "SUN 18:00"
  heartbeat_minutes: 15
channels:
  crew_group_jid: TODO           # filled at M2 after pairing; broadcasts go here
  broadcast_to_group: true       # false ⇒ 1:1 fan-out (Cloud API migration path)
languages: {worker_default: es, manager_default: en, supported: [es, en, pa]}  # pa is P1 (§D11)
reporting:
  manager_channel_primary: whatsapp
  manager_channel_backup: email
  attach_excel_on: [FRI]
listings:
  areas_of_interest: [Penticton, Naramata, Oliver, Osoyoos, Okanagan Falls, Summerland, Kaleden]
  min_acres: 2
  keywords: [vineyard, winery, orchard, acreage, agricultural, ALR, farm]
safety:
  emergency_keywords: [emergencia, accidente, ayuda urgente, "911"]
autonomy:                        # docs/01 §D8 — Hermes leads; these are the few hard edges
  max_unsolicited_dm_per_contact_per_day: 3   # safety messages exempt (docs/03 §4)
  quiet_hours: {from: "21:00", to: "05:30"}   # non-safety only; Hermes holds for the morning
  may_message_managers_anytime: true
  escalate_to_owner_after_failed_nudges: 3
  log_every_decision: true       # agent.decision rows — do not disable, docs/01 §3.1
```

## Appendix B — `config/.env.example` (create verbatim)
```
TZ=America/Vancouver
DB_PATH=./data/hermes.db
MEDIA_DIR=./data/media
EXPORT_DIR=./exports
BACKUP_DIR=./backups
# Owner / alerting
OWNER_WA=+1250XXXXXXX
# LLM — routed by Hermes Agent; 9router via Tailscale (docs/01 §D7)
LLM_BASE_URL=http://172.16.33.5:20128/v1
LLM_API_KEY=                # value of NINEROUTER_API_KEY
LLM_MODEL=                  # PIN a specific model; do not use a `free`/auto combo
LLM_MODEL_TRANSLATE=        # empty = LLM_MODEL
# Weather — ECCC is primary and needs no key
OPEN_METEO_API_KEY=         # set ONLY with a commercial licence; enables fallback rung 2
# Listings inbox
IMAP_HOST=imap.gmail.com
IMAP_USER=
IMAP_PASS=
LISTINGS_ALLOWED_SENDERS=noreply@zealty.ca,*@matrix.crea.ca
# Outbound email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
MANAGER_EMAILS=
# Ops
HEALTHCHECKS_BASE_URL=
```
No `WA_*` variables: Baileys authenticates by QR pairing, and its session state lives in
`~/.hermes/` (back it up, treat it as a secret — docs/02 §6).

## Appendix C — dependencies (pin exact versions at M0)

**Two environments, and getting this wrong is a subtle §D9 failure.**

`requirements.txt` — what `vineyard_mcp` itself needs (the compliance kernel is small now):
```
mcp · pyyaml · python-dotenv · pydantic>=2 · tzdata            dev: pytest · ruff
```

**`requirements-agent.txt` — what Hermes needs available to `execute_code`:**
```
httpx · openpyxl · imapclient · beautifulsoup4 · lxml
```
These are **not** vineyard-mcp's dependencies any more — they are the libraries Hermes reaches for
when it fetches ECCC, reads the listings inbox, or builds a workbook. They must be installed in
the interpreter Hermes's code execution actually uses, which is *not* necessarily the MCP server's
venv. `scripts/install.sh` must install both, and M1's acceptance should include Hermes running
`import httpx, openpyxl, imapclient` successfully via `execute_code` — a five-second check that
catches an otherwise baffling M5/M7.

If `terminal.backend` is ever set to `docker` ✅, they belong in the image (or in
`terminal.docker_image`), not on the host.

Dropped vs the original plan: `fastapi`, `uvicorn`, `apscheduler` — Hermes Agent owns the server
and the scheduler. Hermes Agent itself is installed by its own installer, not via these files.

## Appendix D — `~/.hermes/config.yaml` ✅ (real schema, v0.20.4)

> **The authoritative copy is `hermes/config.yaml.example` in this repo** — annotated, and what
> `bootstrap.sh` actually installs. It is reproduced below for reading convenience; **if the two
> ever disagree, the file wins** and this appendix should be deleted rather than reconciled.
> Duplicated config in two places is how a subtly wrong `timezone` survives review.
>
> Since this appendix was written, the file also carries: `context_file_max_chars` (§D10),
> `terminal.backend`, `compression`, `auxiliary.vision`, and the note that
> `cron.allow_agent_scheduling` stays **false** — Hermes leads operations, but it does not need to
> rewrite its own clock.

The earlier sketch was wrong in three places (provider block, cron block, skills gating). This is
the corrected shape. Still confirm against the installed version at M1.

```yaml
timezone: "America/Vancouver"     # GLOBAL — no per-job timezone exists (docs/03 §0)

model:                            # docs/01 §D7 — 9router via Tailscale
  provider: "ninerouter"
  model: "<PINNED-MODEL-ID>"      # never a `free`/auto combo — silent model swaps
                                  # degrade Spanish extraction invisibly
providers:
  ninerouter:
    type: "openai"                # OpenAI-compatible
    base_url: "${LLM_BASE_URL}"
    api_key: "${LLM_API_KEY}"

whatsapp:
  unauthorized_dm_behavior: ignore  # NOT the "pair" default — enrolment is a manager's job
  send_read_receipts: true
  reply_prefix: ""                  # no bot header; stay conversational (docs/03 §4)

gateway:
  platforms:
    whatsapp:
      extra:
        text_batch_delay_seconds: 5.0   # three fragments → one reply
  # group_policy: allowlist / group_allow_from: [<crew JID>] / require_mention: false
  # ⚠ confirm exact nesting at M2 — keys verified, placement not

mcp_servers:
  vineyard:
    command: "python"
    args: ["-m", "vineyard_mcp.server"]
    cwd: "/opt/hermes-vineyard"
    timeout: 30
    tools: {prompts: false, resources: false}

skills:
  write_approval: true            # ⚠ GLOBAL, not per-skill (docs/01 §3.2) — accept the friction
  guard_agent_created: true       # scan agent-written skills; §D9 gives Hermes `terminal`
  # project-local .hermes/skills/ is auto-discovered in-repo; `hermes skills trust` once

memory:
  memory_enabled: true
  write_approval: false           # open tier; compliance facts never live here (§D2)

cron:                             # NOTE: jobs live in ~/.hermes/cron/jobs.json, NOT here.
  model: "<PINNED-MODEL-ID>"      # this block is only defaults for unpinned jobs
  preflight: true
  model_drift_guard: true         # prevent silent provider switches mid-season
  failure_nudge_threshold: 3

agent:
  disabled_toolsets: ["image_gen", "spotify", "discord", "homeassistant", "browser"]
  # keep: terminal, code_execution, file, vision, tts, memory, session_search,
  #       cronjob, delegation, todo, messaging, mcp-vineyard    ← §D9 needs the first two

auxiliary:
  vision: {provider: "auto", model: ""}    # label + pest photos (M2)
```

`hermes config set` routes API keys to `~/.hermes/.env` and everything else to `config.yaml` ✅ —
prefer it, and `hermes model` for providers, over hand-editing. `hermes config check` ✅ reports
missing options; `hermes doctor --fix` ✅ before blaming anything else.
