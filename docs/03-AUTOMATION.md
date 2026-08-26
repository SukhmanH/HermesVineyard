# 03 — Daily Automation & Failure Handling

Scheduler: **Hermes Agent's built-in cron** ✅ (not APScheduler). Delivers to any connected
platform ✅, so Hermes posts straight to the crew group or a manager DM without us writing a sender.

## 0. ⚠ How Hermes Agent's cron actually works (verified v0.20.4)

Read this before docs/07 M6. Four facts change how the jobs must be built:

**1. The gateway ticks cron — not the CLI.** Jobs live in `~/.hermes/cron/jobs.json` ✅ and are
fired by the gateway's background ticker, which wakes every 60 s. **A `hermes chat` session does
not fire cron jobs.** If the gateway is not running, every job in §1 silently never happens. So:

```bash
sudo hermes gateway install --system     # boot-time service, Linux
hermes gateway status                    # is it actually up?
```

This is the failure mode that looks like nothing at all — no error, no message, just a morning with
no brief. It is why §7's heartbeat asserts *gateway* liveness rather than process liveness.

**2. Timezone is global, not per-job.** Resolution order is `HERMES_TIMEZONE` env →
`timezone:` in `config.yaml` → system local time ✅. Per-job timezones are an open upstream request
([#26549](https://github.com/NousResearch/hermes-agent/issues/26549)); we do not need them — set
`America/Vancouver` once, globally, and every trigger fires at local wall-clock time, DST included.
**Verify the Dell's system clock and TZ at install**; a machine in UTC fires the 06:00 brief at
23:00 the night before, and nothing will warn you.

**3. Schedules accept several forms** ✅ — cron expressions (`45 5 * * *`), intervals
(`every 30m`), one-shots (`2h`, ISO timestamps), and natural language ("every morning at 5:45").
Prefer cron expressions for the daily jobs: they are unambiguous and reviewable in `hermes cron list`.

**4. Delivery is targeted per job** ✅ via `--deliver` / `deliver:` — `whatsapp`, `origin`,
`local`, `telegram:<id>`, `all`, or a comma-separated list. Our jobs target the crew group JID or
manager DMs (docs/07 Appendix A `channels`). Targets are case-sensitive and the platform must be
configured, or delivery fails.

Useful extras: `--no-agent --script <file>` ✅ runs a plain script with **no LLM in the loop**
(stdout delivered verbatim, empty output = silent tick, non-zero exit = alert) — the right shape
for `heartbeat` and `nightly_export_backup` where no judgement is needed. ~~`context_from`~~ and
~~`continuity`~~ **do not exist — see §0.5**; the notepad and `weather_cache` replace them. And
note `allow_agent_scheduling` defaults to **false** ✅ — a cron-run session cannot create more
cron jobs unless we opt in.

**Cron wakes Hermes; it does not drive Hermes** (docs/01 §D8). A trigger is an *appointment to
think*, not a script to execute. At 12:00 the midday trigger does not mean "send an update" — it
means "look at the weather again and decide whether anyone needs to hear about it." Hermes may
send nothing, send the standard update, or send something the template has no field for because
today is unusual. Every one of those is a correct outcome, and the choice is logged
(`agent.decision`, docs/01 §3.1).

What stays computed rather than judged: the **facts** Hermes reasons over. `compute_spray_window()`
returns the verdict, `rei_active` returns the blocks, `query_logs()` returns who reported. Hermes
decides what those mean and what to do about them — it does not re-derive them, and it may not
soften a fail-safe NO into a YES (docs/01 §3).

## 0.5 ⚠ CORRECTIONS from running against the installed Hermes (2026-08-22)

§0 above was written from documentation. Four of its claims are wrong against the real CLI, and
one of them would have left every scheduled run flying blind.

| Claim in §0 | Reality |
|---|---|
| `context_from=[job_id]` chains one job's output into another | **Does not exist.** No such flag or field. Not needed either: the morning brief reads `weather_cache` through `get_situation`, which is our own durable store rather than a fragile inter-job pipe |
| `continuity: true` feeds a job its own previous output | **Does not exist.** Replaced by something better — **`hermes cron notepad <job_id> {get,set,delete,list}`**, a durable per-job key-value store that survives across runs. `listings_poll` keeps seen MLS numbers there |
| Jobs are created as `cron create <name> --schedule ... --prompt ...` | Schedule and prompt are **positional**: `hermes cron create <schedule> <prompt> --name X` |
| — | **`--workdir` is mandatory and was missing entirely.** Without it a cron job loads **no project context files at all**, so it never reads `HERMES.md` — the one place a scheduled session learns its authority, its obligations, and that its first call is `get_situation`. The help's "omit to preserve old behaviour" means "run blind" |

**Verified working**, by creating a real job, running it, and reading its output: with
`--workdir` pointing at the repo, a cron session loads `HERMES.md` **and** `SOUL.md`, and
`--skill <name>` attaches a full skill (cleaner than embedding `/skill` in the prompt).

Also discovered: the runtime injects its own cron instruction defining **`[SILENT]`** — replying
with exactly that suppresses delivery. Use it **together with** `skip_job`, never instead of it.
`skip_job` writes the reasoning to `audit_log` (accountability); `[SILENT]` stops the message
going out (etiquette). Doing only the second makes a deliberate hold indistinguishable from a
crash, which is precisely the distinction docs/07 M6 asked for.

Two more real flags worth knowing: **`--model` / `--provider`** pin a job to a specific model
(so a cheap model can run the nightly export while the crew conversation stays on the good one),
and **`--monitor-script` / `--monitor-url`** suppress a run entirely when a watched source has
not changed.

`hermes cron list` prints a standing warning while the gateway is down — a useful second signal
for §0's top risk.

## 1. Job schedule

> **These are created by `hermes/cron/setup-jobs.sh`**, which is the executable version of the
> table below and whose flags are **verified against the installed CLI** (§0.5). Every job's
> prompt is phrased as *"decide whether…"*, never *"send…"* — that wording is load-bearing, not
> stylistic (§D8). Re-check with `hermes cron create --help` after any upstream update.

Under **§D9 Hermes does the fetching itself** — there is no `weather.py` or `listings.py`. Where the
table below says "pull forecast" or "poll IMAP", Hermes does it with `execute_code`, then reasons
over the result. Only `compute_spray_window()` and the compliance writes are ours (docs/01 §D9).

| Local time | Cron | Job | Deliver | What it does |
|---|---|---|---|---|
| 04:30 | `30 4 * * *` | `grower_daily_report` | grower DM (en) | **The day's first weather fetch** — caches per-site forecasts + verdicts so every later ask reads `weather_cache`. Leads with spray recommendations (`spray_status` cover-days, `spray_options` rotation, PHI countdowns, next-window outlook), then the computed extras — `mildew_risk` pressure band, `water_balance` deficits, sulfur-burn hours, washoff check on yesterday's sprays, GDD pace — then weather, REIs, work by property, watch-list (frost, crew heat flag >30 °C, equipment gates, unverified-product nag), new listings/properties, grants + drought lines from the `grants_watch` notepad. Runs inside quiet hours by the grower's request — exempted via `autonomy.quiet_hours_exempt_jobs` |
| 05:45 | `45 5 * * *` | `weather_fetch` | `local` | Hermes fetches each site's forecast (ECCC → ladder §3), calls `compute_spray_window()` per site, caches to `weather_cache` — refreshes what 04:30 cached; reuse any cache still under `max_data_age_hours` |
| 06:00 | `0 6 * * *` | `morning_brief` | **group** (es) + manager DMs (en) | Per-site conditions + spray verdict, frost flag, active REI "NO ENTRAR" blocks. Reads `weather_cache` via `get_situation` (§0.5 — `context_from` does not exist) |
| 12:00 | `0 12 * * *` | `midday_recheck` | **group** if changed | Re-fetch; if the verdict flipped or the wind band moved >±5 km/h for remaining daylight, push a short update. Otherwise `skip_job` + `[SILENT]` (§0.5). Knows what the morning said from `weather_cache` and recent `agent.decision` rows |
| 17:00 | `0 17 * * *` | `eod_worker_nudge` | **1:1** | Workers with no log today get one gentle «¿Algo que reportar hoy?» (configurable, can be disabled) |
| 19:00 | `0 19 * * *` | `eod_manager_report` | manager DMs (+email) | Tasks by worker/block/hours, sprays + REI expiries, tomorrow's window, NEW listings, anomalies |
| 20:00 | `0 20 * * *` | `frost_watch` | **group** + managers | Only during frost windows (Mar 1–May 31, Sep 15–Nov 15): any site's overnight min ≤ 2 °C → immediate alert, both languages |
| 21:30 | `30 21 * * *` | `nightly_export_backup` | `local` | Regenerate `spray_log.xlsx`/`task_log.xlsx`; SQLite `.backup`; back up the WhatsApp session dir; git-commit the skills dir; rotate per docs/02 §6. **Candidate for `--no-agent --script`** |
| every 30 min | `every 30m` | `listings_poll` | `local` | Hermes reads the dedicated inbox over IMAP, judges what's a real listing, writes `listings`, dedupes on MLS# using its **cron notepad** (§0.5 — `continuity` does not exist) |
| Sun 18:00 | `0 18 * * 0` | `weekly_hours_export` | email | Hours-by-worker-by-day XLSX for the week → managers, laid out for entry into **Payworks** (SAWP payroll) |
| Mon 05:00 | `0 5 * * 1` | `grants_watch` | `local` | Weekly scan of the BC funding watchlist AND Okanagan drought/water-restriction notices (`/grants-watch`). State cached in the cron notepad; the 04:30 report surfaces only changes and near deadlines |
| Fri (with EOD) | — | weekly workbook | email | EOD email variant carries the full Excel workbook |
| Monthly, 1st | `0 7 1 * *` | compliance export | email | `compliance-YYYY-MM.xlsx`, emailed, retained forever. Include the month's skill diff (docs/01 §3.2) |
| every 15 min | `every 15m` | `heartbeat` | `local` | Ping healthchecks.io; **assert the WhatsApp gateway reports connected** (§7). Use `--no-agent --script` — no judgement needed, and it must work when the LLM is down |

The "What it does" column is the **baseline expectation, not a script.** Hermes is expected to meet
it and free to exceed it — adding a warning the template lacks, splitting a brief because one site
differs sharply, holding a nudge because the worker is on a day off. Falling *below* the baseline
(skipping a brief, suppressing an REI alert) requires a logged reason.

**Channel rule (docs/01 §D1):** safety and broadcast information goes to the **crew group** so it
reaches everyone at once, including workers who never opted in 1:1. Anything naming an individual's
work, mistakes, or corrections goes **1:1**.

## 1.1 Standing duties (no clock — Hermes watches for these continuously)

These have no cron entry. Hermes is responsible for noticing them across conversations, briefs, and
query results, raising them when they matter, and logging the judgement either way. The list is
**illustrative, not exhaustive** — a plausible operational concern not written here is still
Hermes's to raise.

- **Silent workers** — someone who normally reports has not for several days. Nudge, or tell a
  manager if it persists.
- **Repeat applications** — the same block sprayed with the same product inside a suspiciously
  short interval. Could be a duplicate log, could be a real over-application. Ask.
- **Label-limit risk** — an application reported near or above a product's `max_temp_c`, or a PHI
  that would collide with an expected harvest date.
- **Unverified products in use** — a product with `verified=0` showing up in real applications is a
  standing compliance gap; keep asking a manager to verify it against the label.
- **REI near-misses** — a task logged in a block that was under REI at the time. This is a safety
  incident, not a data problem. Tell the managers the same day.
- **Data drift** — blocks or workers appearing in messages that do not exist in `blocks`/`contacts`,
  which usually means the seed data is stale.
- **Listings worth interrupting for** — most go in the EOD digest, but something that clearly
  matches what the owner has been hunting for is worth a same-day message.
- **Its own health** — degraded weather sources, repeated tool errors, a provider that has been
  slow all morning. Hermes reports on itself; it does not wait to be asked.

## 1.2 ✅ Cron runs in a *fresh session with no chat context* — CONFIRMED

Verified against v0.20.4: each due job launches "a fresh `AIAgent` session" with isolated toolsets
and **no memory of previous runs** ✅. No conversation history, none of the day's context. This is
correct behaviour (a 06:00 brief should not inherit last night's argument about block 7) but it has
a hard consequence for everything in §1.1:

**A scheduled Hermes cannot notice anything it does not explicitly load.** "Miguel has been quiet
for three days" is invisible unless the job queries for it. So every trigger must begin by pulling
its own situational picture through tools — `query_logs`, `rei_active`, recent `agent.decision`
rows, the relevant `memory` entries — rather than relying on remembering. Persistent facts and
skills *do* load at session start ✅; the day's conversations do not.

Two affordances soften this (**corrected §0.5** — the `context_from` / `continuity` flags
described in earlier drafts do not exist): the job's **cron notepad** holds durable state across
runs, and `weather_cache` + `get_situation` carry forward anything another job produced. `session_search` (FTS5 over past sessions) ✅ is the escape hatch when a job
genuinely needs to look back at conversation — but it is a search, not a memory, so the job still
has to know to run it. That is exactly what `get_situation(scope)` is for.

Build implication (docs/07 M6): each job's first tool call is a `get_situation(scope)` that returns
the picture that job reasons over. If a standing duty is not represented in some job's situation
payload, **Hermes will never catch it** — that, not prompt wording, is the actual failure mode for
§1.1.

## 2. Standard job contract (applies to every scheduled job)

1. Wrapped in a top-level try/except — **a job may fail; it may never fail silently.**
2. On failure: retry ×3 with exponential backoff (30 s / 2 min / 10 min), then:
   - write `audit_log` row (`action='job.failed'`, detail = exception),
   - WhatsApp alert to `OWNER_WA`,
   - if the job produces a user-facing message (morning brief, EOD), send the **degraded
     version** (§3) rather than nothing.
3. On success: ping `HEALTHCHECKS_BASE_URL/<job>` (free healthchecks.io — it emails the owner if a
   ping goes missing, catching "process died overnight" without us polling anything).
4. Jobs are idempotent per (job, local-date): a crashed-then-restarted process at 06:10 re-runs
   `morning_brief` only if no `audit_log` success row exists for today. Idempotence is enforced by
   the `job_start` / `job_finish` MCP tools, not by the agent remembering whether it already ran.

## 3. Weather degrade ladder (never silently skip)

```
1. ECCC citypage XML for each site   (~24h hourly; official frost advisories)  ← free, any use
2. Open-Meteo                        (only if OPEN_METEO_API_KEY is set — commercial licence)
3. Last cached forecast < 24h old, marked   ⚠️ DATOS DE AYER / STALE
4. Nothing usable → send anyway:  "⚠️ Sin datos del clima hoy (falla técnica).
   No fumiguen sin consultar a su manager." + English equivalent + owner alert
```

The spray-window verdict from rungs 2–3 must say what it is based on; rungs 3–4 always verdict
**NO** for spraying (missing wind data = no spray call, fail-safe). The verdict is computed by
`compute_spray_window()` in `vineyard-mcp` — never by the model.

## 4. Messaging (Baileys — no windows, no templates)

The previous plan carried a whole subsystem for Meta's 24-hour service window and pre-approved
template fallbacks. **Baileys deletes all of it:** every message is free-form, every message is
free, and there is no template approval step. What replaces it is a small set of etiquette rules,
adopted from Nous's own bridge guidance ✅ (re-read 2026-08-20; still current) and treated as hard constraints because violating them
is what gets a number banned:

- **Never message a number that has not messaged Hermes first**, except contacts explicitly
  enrolled by a manager in `contacts` with a recorded `consent_ts_utc`. No cold outreach, ever.
- **No bulk sends.** Group broadcasts go to the crew group as one message, not N DMs. Where 1:1 is
  required (EOD nudges), stagger sends with a short randomized delay rather than firing 7 at once.
- **Keep it conversational.** Operational messages only — no marketing tone, no repeated identical
  sends, no message to a worker who has replied `ALTO/STOP` (except REI, frost, and emergency,
  which are safety and always delivered).
- **Rate limits, enforced in the send tool.** Because Hermes decides on its own initiative when to
  reach out (docs/01 §D8), "don't over-message" cannot be an instruction — an eager agent on an
  eventful day would sail past it. The tool caps unsolicited 1:1 messages per contact per day and
  refuses beyond it, returning a structured error Hermes can reason about ("hold it for the EOD
  report"). Safety messages — REI, frost, emergency — are exempt and uncapped.
- Send failures are audit-logged and retried per §2; a persistent failure to one contact falls back
  to email (managers) or a manager relay (workers). `hermes send` ✅ delivers a one-shot message
  without spinning up a gateway loop — the right tool for that fallback.

**Runtime knobs that back these rules** ✅ (verified v0.20.4 — set at M2):

```yaml
whatsapp:
  unauthorized_dm_behavior: ignore    # NOT the default ("pair"). A stranger messaging the bot
                                      # must not start a pairing flow — enrolment is a manager's job
  send_read_receipts: true            # workers can see Hermes received it
  reply_prefix: ""                    # no bot header; keep it conversational (docs/03 §4)
gateway:
  platforms:
    whatsapp:
      extra:
        text_batch_delay_seconds: 5.0 # a worker firing off three fragments gets ONE reply,
                                      # not three — this is the anti-spam rule as a setting
```

Group access is gated by `group_policy` (`open` | `allowlist` | `disabled`), `group_allow_from`
(group JIDs), and `require_mention` ✅. Set `group_policy: allowlist` with only the crew group's
JID, and `require_mention: false` so Hermes can broadcast and answer without being @-tagged.
**Caveat (docs/01 §D1):** group gating is per-*group*, not per-*sender* — anyone in the crew group
can invoke Hermes. Compliance interviews therefore stay 1:1, where the sender is checked against
`contacts`.

## 5. REI monitoring

- On spray commit: `commit_spray_log` computes `rei_expires_at_utc` and returns it; the agent
  immediately posts to the **crew group** («🚫 NO ENTRAR: Bloque B3 hasta jue 14:00») and to
  managers in English.
- Morning brief lists every block still under REI (`rei_active` view).
- When an REI expires during working hours (07:00–18:00): post the all-clear to the group
  («✅ Ya se puede entrar al Bloque B3»). Expiries outside working hours fold into the next
  morning brief.
- If the product row is `verified=0`, Hermes does **not** invent an REI: the tool refuses to return
  one, and the agent asks the applicator to read the label REI, records the answer, and flags the
  product for manager verification.

## 6. Emergency path (bypasses everything)

Inbound message whose intent = `emergency` (keyword fast-path or LLM classification): immediately
alert all managers + owner with worker name, phone, raw message and English translation;
acknowledge the worker in Spanish; audit-log. No batching, no quiet hours, no `ALTO/STOP`
suppression. The keyword list (docs/07 Appendix A `safety.emergency_keywords`) is checked **before**
any LLM call, so an emergency is relayed even if the provider is down.

## 7. Watchdog & process supervision

- **`sudo hermes gateway install --system`** ✅ installs the boot-time service. This is the process
  that both delivers WhatsApp messages *and* ticks cron (§0) — supervising anything else is
  supervising the wrong thing. The Dell boots straight into Ubuntu by default (GRUB, short
  timeout — docs/01 §D6), so a power blip recovers unattended.
- healthchecks.io heartbeat pinged by the 15-min tick — catches full-process death, DNS breakage,
  or clock drift within ~30 min, alerting the owner by email for $0. Run it as
  `--no-agent --script` so it does not depend on the LLM being reachable.
- **The watchdog paradox, and why healthchecks.io is not optional.** The heartbeat is itself a
  cron job, so if the ticker dies the heartbeat does not run and cannot report anything. It can
  never be the thing that tells you cron stopped. healthchecks.io is a dead-man's switch on
  someone else's computer: we ping while healthy, and the **absence** of a ping is the alarm.
  Never rewire the alerting to depend only on the local script.
- **⚠ `hermes gateway status` EXITS 0 EVEN WHEN THE GATEWAY IS DOWN** (verified 2026-08-22). The
  exit code is worthless; the text must be read. It prints `✗ Gateway is not running`. An earlier
  heartbeat grepped for the word "connected", which the command never prints — it would have
  reported failure every 15 minutes until someone muted it, and a muted watchdog is worse than
  none. Match the negative explicitly.
- **Better primary signal: `~/.hermes/cron/ticker_heartbeat`** — a unix epoch refreshed on every
  ticker wake (~60 s). Asserting it is fresh checks the *outcome* we care about, jobs firing,
  rather than the proxy of a process existing. Both failure branches are tested.
- **Gateway liveness is checked separately from process liveness.** Baileys can drop its session
  (protocol update, phone unlinked, number banned) while the Python process stays happily alive —
  the failure mode that looks healthy and delivers nothing. The heartbeat therefore asserts the
  gateway reports connected — `hermes gateway status` ✅ is the check — and on failure alerts the
  owner by **email** (the WhatsApp path is precisely what is broken) and audit-logs
  `gateway.disconnected`.
- Hermes Agent also nudges on repeated cron failures itself: `cron.failure_nudge_threshold: 3` ✅.
  Keep it on; it is a second, independent path to "something has been broken for a while."
- `hermes doctor --fix` ✅ and `hermes logs` ✅ are the first two things to run when something is
  wrong. `hermes dump` ✅ produces a support-ready summary.
- **Session state lives at `~/.hermes/platforms/whatsapp/session`** ✅ (`chmod 700` — it contains
  encryption keys; treat it as a secret and back it up, docs/02 §6). It **survives WhatsApp Web
  protocol updates** unless the device is manually unlinked ✅, so most breakage is fixed by
  `hermes update` and a service restart, *not* a re-pair. If it does need re-pairing:
  `hermes whatsapp` on the Dell, scan the QR from the bot's phone (docs/04 §8).
