# 01 — Architecture

Originally planned 2026-08-20 (custom FastAPI service). **Re-architected 2026-08-20 onto
[Hermes Agent](https://hermes-agent.nousresearch.com)** after the owner identified it as the
intended runtime.

**Verified 2026-08-20 against Hermes Agent v0.20.4** (official docs + repo). Facts previously
marked ⚠ are now either confirmed (✅) or corrected inline; see docs/07 §"Verified capabilities"
for the full audit. Re-check against the **installed** version at build time — upstream moves fast.

## 1. System overview

**Hermes Agent** (Nous Research, MIT, Python 3.11+) is the runtime. It owns the WhatsApp
connection, LLM provider routing, cron scheduling, conversational memory, and the skill/MCP tool
loop. It also ships ~40 built-in tools including `terminal`, `execute_code`, `read_file`, `patch`,
`web_search`, `vision_analyze`, `text_to_speech`, and `delegate_task` — which is why we build far
less than the original plan assumed (§D9).

We contribute four things:

1. **Identity & context** (§D10) — `SOUL.md` (→ `~/.hermes/SOUL.md`, the primary system-prompt
   slot) and `HERMES.md` (repo root, highest-precedence project context file) ✅. These are what
   make D8's authority and D9's execution mandate real *at runtime* rather than only in this
   document — and they are the only part of the plan a **scheduled** session ever reads.
2. **`vineyard-mcp`** — a local MCP server (stdio) exposing typed tools over the **compliance
   kernel only**: drafts, commits, corrections, REI, the spray-window verdict, and the decision
   log. Weather, listings, exports and reports are *not* here — Hermes does those itself with
   `execute_code` (§D9).
3. **Skills** — procedural instructions telling the agent how to run the spray-log interview, the
   correction flow, the morning brief, and the EOD report. Live in the repo at `.hermes/skills/`
   (project-local, git-versioned, activated by `hermes skills trust`) ✅, with `/dia` and
   `/cumplimiento` bundles in `.hermes/skill-bundles/` ✅ that load a whole stance in one token.
4. **Config** — `~/.hermes/config.yaml` (model, providers, gateway, `mcp_servers`, skills) +
   `~/.hermes/.env` (secrets). `hermes config set` routes secrets to `.env` automatically ✅.

```
┌──────────── Ubuntu 24.04, dedicated partition on the Dell (no inbound ports) ───────────┐
│                                                                                         │
│  Hermes Agent  (systemd: `hermes gateway install --system`, Restart=always)             │
│    │            ⚠ the GATEWAY process is what ticks cron — see docs/03 §0               │
│    │                                                                                    │
│    ├─ gateway: WhatsApp (Baileys, QR-paired, dedicated number) ──── outbound only ──────┼──▶ WhatsApp
│    │     crew (es) 1:1 · Punjabi (pa) voice-in only · group = es+pa · mgrs (en) 1:1     │
│    │                                                                                    │
│    ├─ model/providers: 9router via Tailscale (OpenAI-compatible)  ──────────────────────┼──▶ LLM
│    │                                                                                    │
│    ├─ cron (~/.hermes/cron/jobs.json): 05:45 weather · 06:00 briefs · 12:00 recheck     │
│    │        17:00 nudge · 19:00 EOD · 20:00 frost · 21:30 export+backup · /30min listings│
│    │                                                                                    │
│    ├─ BUILT-IN TOOLS — this is how Hermes does most of the work itself (§D9)            │
│    │     execute_code / terminal ──────────────────────────────────────────────────────┼──▶ ECCC XML
│    │            │                                                                       │──▶ Gmail IMAP
│    │            └─▶ writes XLSX, runs backups, ad-hoc analysis ────────────────────────┼──▶ SMTP
│    │     vision_analyze · text_to_speech (Edge TTS, free) · delegate_task · memory      │
│    │                                                                                    │
│    ├─ identity: SOUL.md + HERMES.md — loaded EVERY session, incl. cron (§D10)           │
│    ├─ skills/ (repo .hermes/skills/ + bundles, git-versioned, trusted once)             │
│    │     12 skills · spray-log · punjabi-intake · standing-duties · exports…            │
│    │                                                                                    │
│    └─ mcp_servers: vineyard-mcp (stdio, local Python) — THE COMPLIANCE KERNEL ONLY      │
│            └─ draft/commit/correct · rei_active · spray verdict · query_logs            │
│                       └──────▶ SQLite (WAL, append-only triggers) ◀── system of record  │
│                                                                                          │
│  Agent memory (~/.hermes/) = conversational context only. NEVER the compliance record.   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**The load-bearing separation:** Hermes decides *what to do and what to say*, and now also does
most of the *doing* itself; `vineyard-mcp` is *the record of what is true*. Hermes runs the
operation — it schedules, judges, escalates, delegates, fetches, computes, and improvises (§D8,
§D9). The MCP layer is not its supervisor and not its hands: it is the filing cabinet, the one
instrument that must not lie (the spray verdict), and the four obligations Hermes cannot sign away
(§3). Anything an auditor could ask about lives in SQLite behind a validated tool, never in agent
memory and never in a free-text note.

## 2. Decision records

### D0 — Runtime: **Hermes Agent, not a bespoke service**

The previous plan built `wa_client.py`, `llm.py`, `jobs.py`, `app.py` (FastAPI) and a session
state machine by hand — roughly 60% of the original M0–M8 effort. Hermes Agent supplies all of it:
20+ messaging gateways ✅, provider routing ✅, built-in cron with cross-platform delivery ✅,
persistent memory ✅, ~40 built-in tools ✅, and a native MCP client ✅ (stdio + HTTP, per-server
tool filtering, `/reload-mcp`).

| | Bespoke FastAPI service | **Hermes Agent + MCP** |
|---|---|---|
| WhatsApp transport | write + maintain webhook, signature validation, media download | provided (gateway) |
| LLM client, retries, JSON repair | write | provided (provider layer) |
| Scheduler | APScheduler wiring | provided (built-in cron) |
| Conversation state machine | hand-rolled FSM in `sessions` table | provided (agent loop + memory) |
| Public HTTPS endpoint | required (domain, TLS, tunnel) | **not required** |
| Voice notes, vision | Phase 1.5 work | **fully provided** ✅ (transcription, Edge TTS, `vision_analyze`) |
| Weather / listings / exports | our modules | **Hermes's own** ✅ via `execute_code` (§D9) |
| Compliance writes | ours | **ours** (`vineyard-mcp`) |
| Upgrade path / community | none | Skills Hub, agentskills.io-compatible |

Cost of the trade: we inherit an upstream dependency and its release cadence, and we accept that
the agent loop is less deterministic than a hand-written FSM. §3 explains how the MCP layer
contains that non-determinism.

✅ **Chosen.** Rejected alternative — keep the bespoke build — only makes sense if Hermes Agent's
WhatsApp gateway proves unreliable in M1; the compliance core (docs/02) is deliberately
runtime-agnostic so that fallback stays open.

### D1 — WhatsApp: **Hermes Agent's Baileys bridge, dedicated number**

| Option | Cost | Group support | Verification | Risk | Verdict |
|---|---|---|---|---|---|
| **Baileys bridge (Hermes Agent `hermes whatsapp`)** ✅ | **$0** | **Yes — confirmed** ✅ `group_policy` / `group_allow_from` / `require_mention` | none | ToS violation → possible ban; Web-protocol breakage | ✅ **chosen** |
| Meta Cloud API (`hermes whatsapp-cloud`) | ~$0.0034/utility msg NA, $0.008 MX ⚠ | **DM-only in Hermes Agent v1** ✅ — upstream explicitly recommends Baileys if you need groups | business verification, template approval | Low | Degraded migration path (see below) |
| Twilio / 360dialog BSPs | Meta fees + platform (~€49/mo tiers) | Same limits | Same | Low | Rejected: flat fee > our entire bill |

**Verification result strengthens this decision.** Group support was the one finding that could
have forced a redesign (docs/07 M2 called it "scope-changing if absent"). It is present: the
adapter gates group traffic on group JID via `group_policy: open|allowlist|disabled` and
`group_allow_from`, with `require_mention` controlling whether Hermes answers unprompted chatter.

It also **downgrades the fallback**: Hermes Agent's Cloud API adapter handles direct messages only
in v1, so migrating to official WhatsApp costs us the crew group, not just money. Set
`channels.broadcast_to_group: false` and safety broadcasts become 1:1 fan-out. Worth knowing before
a ban, not after.

**Known gap, ours to handle:** group gating is by *group*, not by *sender* — anyone in an allowed
group can invoke Hermes ([upstream issue #41371](https://github.com/NousResearch/hermes-agent/issues/41371)).
For a crew group of known workers this is acceptable; it means the group must stay the crew's, and
compliance interviews stay 1:1 where sender identity is checked against `contacts`.

Nous's own guidance ✅, adopted verbatim as operating rules: **use a dedicated number, never a
personal or the main business line**; keep usage conversational; **do not automate outbound
messaging to people who have not messaged first**; keep the paired phone on the network; expect
periodic breakage when WhatsApp updates its Web protocol.

**Consequence — the group is back.** The previous plan's central UX compromise (bot cannot join the
crew's existing group, so everything is 1:1) was a limitation of the *official API*, not of the
problem. Baileys removes it. New design:

- **Group** — morning brief, REI "NO ENTRAR" warnings, all-clears, frost alerts. Safety
  information reaches everyone at once, including workers who have not opted in individually.
- **1:1** — spray/task logging interviews, corrections, follow-up questions, EOD nudges. Keeps a
  worker's mistakes and corrections private, and keeps the group free of interview noise.

That hybrid is strictly better than either pure model, and it is only possible because of D1.

**Risk accepted deliberately:** a ban kills the bot's number, not the business's, and not the
data — SQLite is untouched. Recovery is a new SIM and a re-pair (docs/04 §9). The bot's number is
never the main line. If bans recur, D1's migration path to the Cloud API is a config change plus
Meta verification, and docs/05 §5 retains the template wording needed for it.

### D2 — Storage: **SQLite (WAL) + automated Excel/CSV exports** — unchanged, and now load-bearing

| Option | Compliance integrity | Manager ease | Cost | Verdict |
|---|---|---|---|---|
| **Hermes Agent memory (`~/.hermes/`)** | ✗ conversational store with **automatic** compression — `compression.threshold: 0.50` compacts context at 50% of the window by default ✅, and `memory_char_limit: 2200` caps persistent facts to ~800 tokens ✅. No schema, no triggers, no audit chain | ✗ | $0 | **Rejected as system of record** |
| Google Sheets / Excel-as-database | ✗ anyone can edit/delete a spray row; weak audit | ✓✓ | $0 | Rejected as source of truth |
| **SQLite + scheduled exports** | ✓✓ append-only enforced by triggers; single-file backup | ✓ (real .xlsx nightly/weekly) | $0 | ✅ **chosen** |
| Postgres | ✓✓ | ✓ | $0–15 | Overkill for 1 process / 10 users |

**This is the decision the Hermes Agent migration must not erode.** BC's IPM Regulation requires
pesticide application records kept ≥3 years, complete and accurate. An LLM's memory is a summary
that degrades under compression — it is a fine place for "Juan usually sprays block 3" and a
disqualifying place for "8 kg/ha of sulfur was applied to B3 at 06:00 on 2026-05-14." Every
compliance write therefore goes through a `vineyard-mcp` tool with schema validation, and the
agent is instructed (skill + system prompt) that it may never assert a logged fact it did not
read back from a tool call.

Managers asked for Excel — they get Excel, as *output*: nightly `spray_log.xlsx` / `task_log.xlsx`
into `exports/`, emailed weekly (Fri) and on the 1st (monthly compliance workbook), plus an
on-demand `EXPORT` command. The database stays append-only (docs/02).

### D3 — Weather: **ECCC primary, Open-Meteo optional**

Reversed from the original plan, which had Open-Meteo primary and a US$29/mo line item.

- **ECCC (Environment Canada)** — free for any use including commercial (Open Government
  Licence), authoritative for Canada, carries official frost advisories/warnings. Citypage XML is
  clunkier and hourly coverage is ~24 h. ✅ **primary**, because "free for commercial use" is a
  hard requirement and the 24 h horizon covers the only question we actually ask ("can we spray
  today, and is it freezing tonight?").
- **Open-Meteo** ⚠ — better data (3-day hourly, GEM/HRDPS models, one clean JSON call per site),
  but the free tier is **non-commercial only**; business use requires the US$29/mo Standard plan.
  Retained as an optional upgrade and as fallback rung 2. Not used on the free stack — a vineyard
  management business is commercial use, and the free tier is not a loophole.
- OpenWeatherMap rejected: adds nothing over the pair above; card required; pricing churn.

Degrade ladder (never silently skip): ECCC → Open-Meteo (if key set) → last-good cache marked
**STALE** → apology to all + owner alert. Spray verdict fails safe to **NO**. See docs/03 §3.

### D4 — Listings source: **email-ingest, no scraping** — unchanged

| Option | Reliability | Legality | Cost | Verdict |
|---|---|---|---|---|
| Scrape Realtor.ca | ✗ bot-protection arms race | ✗ CREA ToS | $0 + constant repair | Rejected |
| CREA DDF API | ✓✓ | ✓ but realtor-member access only | via realtor | Indirect route below |
| **Realtor MLS auto-search email** | ✓✓ freshest data, standard practice | ✓✓ | $0 | ✅ **chosen (source 1)** |
| **Zealty.ca saved-search alerts** | ✓ | ✓ (their own feature) | $0 | ✅ **chosen (source 2)** |
| Niche ag sites (FarmMarketer, BC Farm & Ranch) | ~ few listings | ~ | $0 | Phase 2 |

A dedicated Gmail inbox is the stable interface. `vineyard-mcp` polls IMAP every 30 min, the agent
parses alert emails into structured listings, dedupes on MLS#, and folds anything new into the EOD
report. **Owner action item:** ask your realtor to set up an MLS auto-email search
(vineyard/ag/acreage, South & Central Okanagan) to the Hermes inbox.

### D5 — Manager report channel: **WhatsApp DM primary, email backup** — unchanged

WhatsApp because managers already live there and it is where REI alerts must land instantly. Email
because compliance exports need attachments and a permanent paper trail. Dashboard **cut from
scope**; Excel is their dashboard. Revisit in Phase 3 only if asked.

### D6 — Hosting: **Ubuntu Server 24.04 on a dedicated partition of the owner's Dell i5**

The original US$6/mo Toronto VPS existed to terminate Meta's webhook. **Baileys connects outbound,
so there is no webhook** — no public IP, no domain, no TLS cert, no Cloudflare Tunnel, no open
firewall port. The hosting requirement collapses to "a machine with outbound internet that stays
on."

| Option | Isolation from existing data | Resource cost | Availability risk | Verdict |
|---|---|---|---|---|
| VirtualBox VM on the Dell's Windows install | ✓✓ trivially reversible (delete one file) | Runs a full Windows host 24/7 just to babysit a hypervisor | Windows Update can force a reboot of the *host*, taking the guest down with it, unattended | Rejected — the actual cost isn't VM speed (this workload is one lightweight Python process; overhead is irrelevant), it's keeping a second OS alive around the clock for no benefit once the Dell is dedicated |
| **Dual-boot: Ubuntu Server on its own partition** | ✓ separate filesystem, Windows partition untouched | Runs on bare metal, nothing else to keep alive | Native — no host to reboot out from under it | ✅ **chosen** |
| Wipe the Dell, Ubuntu only | ✓✓✓ | Same as above | Same as above | Rejected — owner has files on the existing Windows install worth keeping |

Chosen: shrink the existing Windows partition (owner has ~1TB free, ample room), install Ubuntu
Server 24.04 into the freed space, GRUB dual-boots the two. **Accepted tradeoff:** the two OSes are
mutually exclusive at any moment — if the owner boots into Windows on this machine, Hermes is
offline until it's rebooted back into Ubuntu. This is a non-issue once the Dell is a dedicated
appliance (the intent here), and GRUB defaults to Ubuntu with a short timeout precisely so an
absent-minded reboot doesn't strand the machine in Windows. If the Dell is ever needed for casual
Windows use again, revisit — that's the one scenario where the VM's "run both at once" property
would have been worth its overhead.

Rejected: Oracle Cloud Always Free (signup rejected repeatedly), GCP e2-micro free tier (requires
a refundable CA$20 prepayment, and no free Canadian region), the owner's personal PC (should not
carry business ops).

Operational cost of this choice: the Dell must stay powered and awake, and a hardware failure is
the owner's to fix. Mitigated by systemd `Restart=always`, healthchecks.io watchdog, and nightly
off-box backups (docs/02 §6). **Migration to a VPS or Oracle ARM instance later is: install Hermes
Agent, copy `hermes.db` + `~/.hermes/` + `.env`, re-pair WhatsApp.** No code changes — the dual-boot
detail is pure infrastructure and nothing above the OS knows or cares that it isn't a VM or a VPS.

### D7 — LLM: **9router via Tailscale, as a Hermes Agent custom provider**

Jobs: intent routing + field extraction from colloquial Spanish, es↔en translation (vineyard
glossary), listings-email parsing; Phase 1.5 adds voice-note transcription and label-photo
reading. Volume ≈ 50–150 small calls/day.

Hermes Agent routes to any provider ✅ — Nous Portal (OAuth), OpenRouter, OpenAI, Anthropic, local
Ollama/vLLM/llama.cpp, or a custom OpenAI-compatible base URL. We use the owner's existing
**9router gateway** (`http://172.16.33.5:20128/v1`, reachable from the Dell via Tailscale) → $0.

Real config shape ✅ (the earlier sketch was wrong — it is `model:` + `providers:`, not `provider:`):

```yaml
model:
  provider: "ninerouter"
  model: "<pinned-model-id>"       # PIN it — see below
providers:
  ninerouter:
    type: "openai"                 # OpenAI-compatible
    base_url: "http://172.16.33.5:20128/v1"
    api_key: "${LLM_API_KEY}"
```

Set it with `hermes model` (the provider wizard) rather than hand-editing; it runs the endpoint
prompts and routes the key to `.env` ✅.

Pin a specific reliable model rather than a `free`/auto combo: extraction from unpunctuated
voice-note Spanish is the hardest thing in this system, and silently swapping to a weak model
degrades compliance data quality invisibly. Fallbacks if 9router is unreachable: local Ollama on
the Dell, or Nous Portal. Keyword fast-path commands (docs/05 §6) work with **no** LLM at all, so
a provider outage never drops a safety message.

### D8 — **Hermes leads. The stack serves it.**

Owner directive, 2026-08-20: *"I want Hermes to be the leader — to conduct everything, to be the
boss of all these processes."* This is the governing design principle, and it is stronger than a
preference: where a choice exists between hard-coding a behaviour and letting Hermes decide, **the
default is Hermes decides.**

Hermes is the **operations manager**. `vineyard-mcp` is its filing cabinet, its instruments, and
its outbox — not its supervisor. Concretely, Hermes owns:

| Domain | What Hermes decides, unprompted |
|---|---|
| **Conversation** | When to ask, what to ask, how to phrase it, when to stop asking and just accept a voice note. Bundling, tone, register per worker |
| **Scheduling** | Cron is a *heartbeat*, not a script (docs/03 §1). Hermes decides whether a midday recheck is worth sending, whether to nudge a specific worker, whether today's brief needs a warning the template doesn't have |
| **Reporting** | What belongs in the EOD report. The template is a floor, not a ceiling — if something matters and no field exists for it, Hermes says it anyway |
| **Anomaly detection** | Noticing that a worker has gone quiet for three days, that a block has been sprayed twice in a week, that a product is being used past its label temperature, that a listing matches what the owner has been hunting for |
| **Delegation** | Spawning isolated subagents ✅ (`delegate_task`) for parallel work — parsing a listings backlog, generating a month's exports — without blocking the crew conversation |
| **Execution** | Doing the work itself (§D9) — fetching forecasts, reading the listings inbox, building workbooks, running ad-hoc analysis — rather than waiting for a tool we thought to write |
| **Learning** | Distilling its own skills from completed work — the core Hermes Agent loop, see §3.2. A procedure Hermes invents, refines, and reuses is the point of the system, not a side effect |
| **Relationships** | Remembering that Juan reports by voice and Miguel by text, that one worker needs a nudge and another never does, and adapting |
| **Escalation** | Deciding when something is a manager's call rather than its own, and making that call itself |

Hermes Agent supports skills (procedural markdown in `~/.hermes/skills/`, agentskills.io-compatible),
MCP servers (`mcp_servers` in `config.yaml`, stdio + HTTP, auto discovery, per-server filtering,
`/reload-mcp`), built-in cron, persistent memory, subagents, and skill auto-generation ✅ — the
feature set assumed above, all confirmed at v0.20.4.

**Tool design follows from this.** Give Hermes *broad, composable* tools, not narrow one-per-report
functions. `query_logs(filters)` beats five fixed report builders, because the first lets Hermes
answer a question nobody anticipated and the second only answers the five we thought of. Skills
carry procedure and judgement; the MCP server carries facts, math, and writes.

**The cost of this choice, stated plainly:** more autonomy means more variance. Two EOD reports for
similar days will not be byte-identical, behaviour is harder to unit-test, and Hermes will
occasionally do something surprising. That is accepted deliberately — an assistant that only ever
does the five things in the spec is a cron job with extra steps. The mitigation is not restriction,
it is **accountability**: every autonomous decision Hermes makes is written to `audit_log` with its
reasoning (§3), so "why did it do that?" is always answerable after the fact.

### D9 — **Hermes does the work itself. We build the record, not the hands.**

Owner directive, 2026-08-20, sharpening D8: *"I literally want Hermes to do everything."* D8 gave
Hermes the **decisions**. D9 gives it the **execution**, and it is a direct consequence of what
verification found in the runtime.

The original plan assumed Hermes could only act through tools we wrote, so it specced
`weather.py`, `listings.py`, `exports.py`, `reports.py`, `jobs.py`. That assumption was wrong.
Hermes Agent ships `execute_code` (run Python, with tool-call access) and `terminal` (run
commands) ✅. Python has `httpx`, `imapclient`, `openpyxl`. **Hermes already has hands.** A tool we
write to "fetch the weather" is not granting a capability — it is taking a capability Hermes has
and narrowing it to the one call we thought of.

| Job | Old plan | **D9** |
|---|---|---|
| Weather | `weather.py` parses ECCC XML | Hermes fetches and reads ECCC itself via `execute_code` |
| Listings | `listings.py` polls IMAP, agent parses | Hermes opens IMAP itself, reads, judges, dedupes |
| Exports | `exports.py` builds workbooks | Hermes writes the XLSX itself with `openpyxl` |
| Reports | `reports.py` composes EOD | Already Hermes's (D8) — now end to end |
| Backups | `scripts/backup.sh` | Hermes runs it, or a `--no-agent --script` cron job ✅ |
| Ad-hoc questions | five fixed report builders | `execute_code` + `query_logs`, unbounded |

**What stays in `vineyard-mcp`, and exactly why.** Not "the things we don't trust Hermes with" —
the things that must be true regardless of which model is running, on a bad day, mid-outage, or
under a prompt-injected message:

- **The compliance write path** — `draft_*` / `commit_*` / correction. Because §3's four
  obligations are enforced here in Python, and because BC law wants an append-only record.
- **`compute_spray_window()`** — because it must fail safe to NO on degraded data (docs/03 §3),
  and "fails safe when the reasoning layer is impaired" is not a property a reasoning layer can
  provide for itself.
- **`rei_active`, `query_logs`, `get_situation`, `log_decision`** — cheap, composable reads over
  the record. Hermes *could* write the SQL through `execute_code`; these exist because they are
  the reads it makes constantly and a stable shape beats a re-derived query every morning.

Everything else Hermes does itself. **The test for a new tool is no longer "is this useful?" but
"would Hermes be unable to do this, or unsafe doing it, without us?"** If neither, it is not a
tool — it is a line in a skill telling Hermes how the owner likes it done.

**Cost of this choice.** Hermes fetching ECCC itself means a malformed XML response is handled by
judgement rather than by a parser we tested — it might get it right in a way we did not anticipate,
or wrong in a way we did not anticipate. Mitigations: the spray verdict it feeds is still computed
and still fails safe; every run writes `agent.decision`; and `execute_code` runs against real data
daily where a wrong answer surfaces in a brief someone reads. We accept more variance in *how the
facts are gathered* in exchange for an assistant that can answer a question nobody pre-built.

**Not deleted, deferred to Hermes:** the *knowledge* in those modules is still ours to supply —
which ECCC site codes map to Penticton/Oliver/Naramata, which senders count as listings, what a
compliance workbook must contain. That knowledge moves from Python into **skills** and
`settings.yaml`, where Hermes reads it and can improve on it (§3.2).

### D10 — **Hermes's leadership is installed, not merely described**

D8 said Hermes leads and D9 said Hermes executes. Both were, until now, *prose in a plan* — and a
plan is not a thing the runtime reads. Verification of the identity and context layer closed that
gap: Hermes Agent loads two files on every session, including every scheduled one, and neither was
being used.

| File | Loaded from | What it does |
|---|---|---|
| **`SOUL.md`** ✅ | `~/.hermes/SOUL.md` **only** — never the working directory | Occupies the **primary slot in the system prompt**. Durable identity: role, tone, register, how it holds itself |
| **`HERMES.md`** ✅ | repo root, auto-discovered | Project context file, **highest precedence** (beats `AGENTS.md`, `CLAUDE.md`, `.cursorrules`; first match wins). The standing operational brief |

This is the difference between telling a build agent "Hermes should behave like an operations
manager" and the *runtime* opening every session with "I am the operations manager." Both files
ship in this repo; `hermes/install/bootstrap.sh` copies `SOUL.md` into the Hermes home, and
`HERMES.md` is picked up in place.

**Why this matters more than it looks.** Cron sessions start with **no chat context** (§docs/03
§1.2). Skills load, memory loads, and these two files load — and that is the entire inheritance a
06:00 brief gets. If the authority granted in D8 lives only in `docs/01`, a scheduled Hermes has
never read it. Putting it in `HERMES.md` is what makes autonomy survive the fresh-session boundary.

Division of labour between the four layers, which is easy to get wrong:

| Layer | Holds | Cap |
|---|---|---|
| `SOUL.md` | *Who* — identity, voice, standards | System-prompt slot |
| `HERMES.md` | *What is true here* — the operation, authority, obligations, channel rules | `context_file_max_chars` (default scales with model; set to 40 000) |
| Skills | *How* — procedure, loaded on demand by progressive disclosure | ~3k tokens for the whole index |
| Memory | *Small durable facts* — Juan reports by voice | **2 200 chars** `MEMORY.md`, **1 375** `USER.md` |

**Correction to §D2's figure:** agent memory is not "~800 tokens" in the abstract — it is two
files, `~/.hermes/memories/MEMORY.md` (2 200 chars) and `USER.md` (1 375 chars), injected as a
**frozen snapshot at session start**, so a fact written at 10:00 is not visible to the 12:00 job.
That freezing is a second, independent reason compliance facts cannot live there (§D2), and it is
why `get_situation` exists.

✅ **Chosen.** Cost: two more files to keep coherent with the docs, and a real risk of drift
between `HERMES.md` and `docs/01`. Mitigation: `HERMES.md` states *operating rules and authority*
and deliberately does **not** restate rationale — the "why" stays here, in the decision records,
and `HERMES.md` links to nothing it cannot act on.

### D12 — **Hermes recommends work, grounded in the record rather than invented agronomy**

Owner request, 2026-08-22: recommend tasks and sprays, and give managers options to choose from.

This is worth having and it is also the most dangerous thing in the system to get wrong. A bad
spray recommendation is crop damage, a residue violation, bred resistance, or a worker exposed
for nothing. So the design question is not *whether* Hermes may advise — it is **what a
recommendation is allowed to be made of.**

**The rule: recommendations are assembled from this vineyard's own record, plus the shed.**

| ❌ Invented | ✅ Grounded |
|---|---|
| "Spray Pristine at 400 g/ha for mildew pressure" | "B3's last mildew cover was 16 days ago; the label interval on what you used is 10. Thursday 06:00–09:00 is the only sprayable window this week. The shed has Kumulus DF (M2) and Quintec (13); B3 has had M2 twice running, so rotating is the resistance-safe option. Your call." |

The first names a product you may not own, at a rate nobody verified, for pressure Hermes cannot
see. The second is four checkable facts and a decision left with someone who can walk the block.

**What makes this safe is structural, not prompt wording:**

- **`spray_options` is the shed.** It returns only rows from `products`. There is no tool that
  returns "the right product", because no such fact exists in this system — so there is nothing
  for Hermes to read one out of.
- **Label rates only**, and unverified products come back flagged unusable with their REI
  withheld. Obligation 4 reaches into the advisory path unchanged.
- **Every recommendation writes `agent.recommendation`** with its evidence. At season end the
  owner can read back what was advised, what was done, and what happened — and the advice that
  was *wrong* is the most useful thing in that log.
- **Hermes never acts on its own recommendation.** Advice is a proposal; nothing commits without
  a human, exactly as before.

**The computed facts it reasons over** (deterministic, same discipline as `compute_spray_window`
— arithmetic a language model must not re-derive differently each morning):

| Tool | Answers |
|---|---|
| `spray_status` | Days since cover per block and pest, against the label's own reapply interval; consecutive same-FRAC-group runs |
| `spray_options` | What in the shed is registered for this pest, and what disqualifies each |
| `task_cadence` | Days since each task per block, against the median **across your own blocks** |
| `compute_gdd` | Growing degree days, base 10 °C, with gaps counted rather than hidden |

Schema additions: `products.frac_group` / `target_pests` / `reapply_days`, and `block_season`
for phenology and expected harvest (so PHI conflicts are checkable). Procedure lives in the
`advisory` skill.

**Two honest limits kept, because removing them would be a lie:** Hermes has not seen the canopy,
so it may report that conditions favoured mildew and that cover lapsed eleven days ago, but never
that there *is* mildew in B3. And where a call genuinely needs eyes on the vines, the right answer
is "someone should walk that block" — which earns more trust than a confident guess and is the
answer an inspector would want to find in the log.

✅ **Chosen.** Cost: three schema columns, one table, four read tools, and a standing obligation
to log advice so it can be judged. The alternative — a system that holds every record and refuses
to draw any conclusion from them — wastes the one advantage it has.

### D13 — **Fruit maturity against winery contracts, and irrigation, with the cross-check between them**

Owner request, 2026-08-22: wineries specify Brix and sugar targets; recommend against those, and
advise on irrigation.

These arrive as one decision rather than two because **post-veraison irrigation moves water into
the berry — it dilutes sugar and pushes ripening back.** A block behind its contract Brix target
with the harvest window closing is a block where watering works *against* the delivery spec. That
tension is invisible in either dataset alone, and it is the single most useful thing this layer
produces.

**Contract targets** (`fruit_targets`) hold what the winery wants per block per season: a Brix
window, TA and pH ranges, and the harvest window. **Samples** (`fruit_samples`) hold what was
measured — and are **append-only**, like the compliance tables, because a ripening curve that can
be retro-edited is one nobody can trust when a delivery is disputed.

**What is computed, in the same discipline as `compute_spray_window`:**

| Tool | Answers |
|---|---|
| `maturity_status` | Current Brix/TA/pH vs contract, **°Bx per day**, projected days to target, sample staleness |
| `compute_et0` | Reference evapotranspiration, Hargreaves-Samani |
| `water_balance` | Rain in, crop use out, days since irrigation, deficit in **mm** |
| `irrigation_vs_ripening` | The cross-check: states the tension, does not resolve it |

**The number that matters is the rate, not the level.** "We're at 21.4" is a position; "21.4,
gaining 0.2 a day, roughly eight days out" is a plan. So the design pushes hard on when a
projection is *not* trustworthy: a single sample yields no rate at all, flat or falling Brix
produces no projection rather than an infinite one, and anything over a week old is flagged stale
because ripening moves fast and harvest calls get made on these numbers.

**Guardrails, structural as elsewhere:**

- **Implausible readings are refused, not stored** (Brix outside 0–40, pH outside 2–5). One
  fat-fingered number poisons the rate and every projection off it.
- **Irrigation returns a deficit in millimetres, never a dose.** Litres depend on soil, rooting
  depth and emitter spacing. Where a block records its system a run-time estimate follows; where
  it does not, the answer says why not. A confident volume with no basis is exactly the invented
  agronomy §D12 refuses.
- **ET₀ is labelled an approximation** — FAO-56's temperature-only fallback, appropriate because
  ECCC gives no daily radiation or humidity. It over-predicts in humid air, under-predicts in
  wind, and the caveat travels with the number.
- **Kc and the deficit fraction live in settings**, not in code: how hard you run deficit after
  veraison is a quality decision the winemaker has an opinion about, not a fact.

**It also closes a loop in §D12:** a projected harvest date makes **PHI conflicts checkable**. A
product whose pre-harvest interval outruns the picking date is not an option, however well it
otherwise fits.

**Limits kept, because they are real:** Hermes has not tasted the fruit — Brix, TA and pH are not
phenolic ripeness, and a winemaker weighs seed colour and tannin above these numbers. It has not
seen the vines — it can report a water deficit but not wilting or shoot-tip growth. And a block
deliberately hung long for a reserve lot looks identical in the data to one that is behind
schedule, so it asks rather than assuming.

✅ **Chosen.** Cost: two tables, five block columns, five tools, and an irrigation settings block
the owner must actually tune. Procedure lives in the `fruit-and-water` skill.

## 3. Hermes's authority — and the four things nobody gets to override

Per D8, Hermes leads. Its authority is broad and deliberately open-ended: if a situation is not in
this plan, Hermes handles it and logs what it did. There is no whitelist of permitted actions.

Four exceptions. They are not limits on Hermes's judgement — they are the obligations Hermes is
**accountable for**, enforced in Python so that a bad model day, a prompt-injected message, or a
degraded provider cannot break them. A human vineyard manager operates under exactly the same
four: they also cannot legally alter a spray record after the fact, or guess a re-entry interval.

1. **A compliance record commits only with the worker's confirmation.** `commit_spray_log` requires
   a `confirm_token` from a prior `draft_spray_log`, whose draft is `awaiting_confirm` and whose
   worker replied «SÍ». Hermes decides everything about that conversation — when to show the card,
   how to word it, whether to re-draft — but the «SÍ» is the *worker's* signature on a legal record,
   and it is not Hermes's to supply. The tool rejects any call without it.
2. **BC-required fields are validated server-side.** Block resolution, product lookup, rate/unit
   sanity, required-field presence — checked in Python, returned as structured errors naming the
   field. Hermes turns those into the next Spanish question however it sees fit.
3. **The worker's own words are kept verbatim.** Every row carries `raw_message`. This protects
   Hermes as much as it protects the record: when an extraction is questioned months later, the
   original is there, and the correction chain (docs/02 §3) supersedes without deleting.
4. **An unverified REI is never asserted.** If `products.verified = 0`, tools refuse to return a
   re-entry interval and Hermes asks the applicator to read the label. A guessed REI sends someone
   into a sprayed block early — the one failure here that injures a person rather than a record.
   Structurally prevented, not discouraged.

Adjacent to these, two availability rules: the **spray-window verdict** is computed in Python and
fails safe to NO on degraded data (docs/03 §3), and **emergency keywords are matched before any LLM
call** (docs/03 §6) — so a provider outage cannot swallow a «EMERGENCIA». Neither constrains what
Hermes does when it *is* running; both exist for when it is not.

### 3.0 What the first real agent run broke, and how it was closed

**2026-08-21.** A live model drove the kernel end to end for the first time. The append-only
triggers and the DST-correct REI expiry held. **Four of the protections did not**, and the
pattern is worth stating plainly because it will recur: *every one of them was a rule the kernel
believed it was enforcing, but was actually only checking a proxy for.*

| # | What was enforced | What was actually required | Fix |
|---|---|---|---|
| 1 | The draft is **ready** | A human **agreed** | `draft_*` now yields state `ready`; a separate `present_confirmation` moves it to `awaiting_confirm`; `commit_*` demands the worker's reply **verbatim** and stores it in `confirmed_by_reply` |
| 4 | `verify_product` was **called** | Someone **read the label** | `pcp_number` and `rei_hours` are now required arguments, and placeholders (`PCP-XXXXX`, `TBD`, `?`) are rejected. If they cannot state both, they did not read it |
| — | The rate is **positive** | The rate is **plausible** | 20 kg/ha committed against a 6 kg/ha label rate, unremarked. Rates >1.5× label now require explicit `rate_confirmed`, and the discrepancy is recorded in `rate_flag` rather than erased |
| — | Weather was **offered** | Weather is **on the record** | `wind_kmh`/`temp_c` are BC-required and were committing as NULL while the agent reported them confidently in chat. Now required fields |

Two things this teaches, beyond the individual bugs:

- **A gate that checks a proxy is not a gate.** "The draft is complete" felt equivalent to "the
  worker confirmed", and it is not. When adding any future obligation, state the human act it
  protects and check *that*, not its shadow.
- **Put the evidence on the record.** `confirmed_by_reply` is the important half of fix 1. It does
  not prevent an agent from fabricating a confirmation — nothing in software can — but it turns an
  invisible gap into a discoverable falsification the owner can audit.

The agent also reported facts in chat that were not in the record it wrote (it named the applicator
as "Sukhman" while the row said "Owner Name", and described weather the row did not carry). That
is §D2's rule — *never assert a logged fact you did not read back from a tool* — failing in
practice, and it is why the EOD report and every summary should quote committed values.

### 3.1 Accountability: the decision log

Because Hermes acts on its own initiative, every autonomous decision writes an `audit_log` row —
`action='agent.decision'` — carrying what it decided, what it observed, and why. Not just tool
calls: the *choices*. "Skipped the midday recheck — verdict unchanged and wind within 3 km/h."
"Nudged Miguel but not Juan — Juan logged at 14:20." "Flagged B7 to managers — second sulfur
application in six days."

This is what makes broad autonomy safe to grant. The owner can always reconstruct what Hermes did
and why, the EOD report can surface anything unusual, and a wrong pattern is visible and
correctable within a day rather than discovered at audit. **Autonomy is bounded by transparency,
not by permission.**

### 3.2 The learning loop — and which skills are gated

Self-improvement is Hermes Agent's central mechanism, not an add-on ✅. After a non-trivial task it
distills a reusable **skill** via `skill_manage` (create / patch / edit / delete / write_file /
remove_file) ✅ — `SKILL.md` files with YAML frontmatter in `~/.hermes/skills/`, loaded by
progressive disclosure (`skills_list()` metadata ≈3k tokens → `skill_view(name)` → reference files
on demand) ✅ so a large skill library costs little until used. Three triggers: a multi-step
workflow worth repeating, an error whose working path it found, and **a correction from a person**.
Memory is three-layer: session context, persistent facts, procedural skills.

The loop is operationalized as a skill in this repo — `.hermes/skills/self-improvement/` — because
"capture what you learn" is itself a procedure, and leaving it implicit is how it quietly never
happens. It states the three triggers, the routing rule below, and the monthly review.

**The routing rule, which is the part most often got wrong:**

| Store | Holds | Never |
|---|---|---|
| **Skill** | Procedure — how to run the correction interview, how to shape a frost message | — |
| **Memory** (2 200 chars `MEMORY.md` / 1 375 `USER.md`) | Small durable facts — Juan reports by voice, Miguel is off Fridays | **A compliance fact.** Capped, compressed, and frozen at session start (§D10) |
| **SQLite** | The record — every spray, task, correction, decision, message | — |

The test: *if this were silently dropped in six months, would someone be hurt or a record be
wrong?* If yes, it belongs in the database.

Three runtime features worth using deliberately here:

- **`/learn`** ✅ turns a source into a skill without anyone authoring it — `/learn <url>`,
  `/learn <directory>`, or `/learn <procedure described in a sentence>`. For large sources it
  builds a knowledge-base skill (lean index + `references/` loaded on demand). This is the fastest
  path to teaching Hermes the BC IPM regulation, a product label PDF, or "how we do harvest."
  `hermes/install/bootstrap.sh` ends by prompting for exactly these three.
- **`/journey`** ✅ — a unified timeline of memory *and* skills over time, with editing and
  pruning (plus a memory graph on desktop). This is the **owner's monthly review surface**, and it
  matters because an unpruned wrong memory is worse than no memory: it is a confident wrong answer
  with no obvious provenance. Pairs with `git log --stat .hermes/skills/` for the same month.
- **Project-local skills** ✅ — a git repo's `.hermes/skills/` is discovered automatically and
  activated with `hermes skills trust`. **This project's skills live in the repo**, not only in
  `~/.hermes/`, which is what makes them reviewable, diffable, and portable (below).

One thing the runtime does *not* provide, so it should not be designed around: **`/goal` is
session-scoped.** It sets a standing objective that a judge model re-checks after each turn,
feeding continuations until it is met or `max_turns` (default 20) runs out. Useful for "clear
every open draft before you stop." It is **not** a background watcher and does not survive into a
scheduled run — which is why §1.1's standing duties depend on `get_situation`, not on `/goal`.

For this project that means the second season should cost less and ask fewer questions than the
first — the exploration is short-circuited by procedures Hermes wrote for *this* vineyard. It also
means **correcting Hermes is how you program it.** A manager saying "don't nudge Miguel on
Fridays, he's off" is a durable change, not a one-time instruction. Tell the crew and the managers
this explicitly (docs/04 §6); it is the highest-leverage thing they can do.

**What Hermes does not get to rewrite unsupervised.** The learning loop is exactly as valuable as
it is dangerous when pointed at a compliance flow: a skill that "improves" by dropping a
confirmation step or skipping a PPE question is a quieter failure than a crash, because it looks
like the system working. So skills split into two tiers:

| Tier | Examples | Policy |
|---|---|---|
| **Open** | conversational register, nudge timing, report phrasing, listings triage, translation habits, anything Hermes invents for a situation nobody anticipated | Hermes writes and refines freely. This is most of them, and it is where the compounding value is |
| **Gated** | `spray-log`, `task-log`, `correction`, `standing-duties`, `onboarding` | Edits stage for human review before taking effect |

**Correction from verification: `skills.write_approval` is global, not per-skill** ✅. There is no
per-skill gate — it is one boolean covering every skill write. The two-tier design above is
therefore a *review policy we operate*, not a setting the runtime enforces per file. Resolution:
**set `write_approval: true` globally.** Approving an open-tier skill is a few seconds at
`/skills pending` → `/skills diff <id>` → `/skills approve <id>` ✅; silently losing the gate on
`spray-log` is a compliance failure. Pay the friction.

Also enable **`skills.guard_agent_created: true`** ✅ — scans agent-written skills for dangerous
patterns. Cheap, and D9 gives Hermes `terminal` and `execute_code`, so a self-written skill has
real reach.

Note the four hard obligations (§3) sit **below** all of this: they are Python, not prose, so no
skill edit — approved or not — can remove the confirmation gate or let an unverified REI through.
The gate protects the *quality* of the compliance interview; the tools protect its *integrity*.

**Skills are version-controlled in git** (docs/07 M6) — in this repo at `.hermes/skills/`, with
`~/.hermes/skills/` synced from it. The diff is the honest answer to "what did Hermes teach itself
this month," it makes a bad self-edit revertable in one command, and it turns a season of
accumulated procedure into something portable — backup-able, reviewable, and transferable if the
runtime is ever replaced. `hermes backup` ✅ archives config + skills + sessions as a zip alongside.

### D11 — **Punjabi is P1 and two-way, on a free self-hosted stack**

Owner correction, 2026-08-21: the spray applicator and several crew members are Punjabi-speaking.
This reverses the plan's assumption that Punjabi was a **Phase 2 manager** language — "fill
`pa.yaml`, nothing else changes." It is needed **now**, and it is needed in **both directions**:
Hermes must listen to spoken Punjabi and speak it back.

**The literacy profile, which drives every choice below:**

| | Punjabi workers |
|---|---|
| Speak Punjabi | ✅ working language — voice is how they report |
| **Read** Gurmukhi | ✅ — so text replies work |
| **Write** Punjabi | ❌ — never ask them to type Punjabi |
| Read English | ❌ — English is not a fallback, it is a dead end |

**Finding 1 — free ASR is rough on Punjabi.** General Whisper benchmarks at
[~54.7 WER (Large) and ~86.8 (Small)](https://aclanthology.org/2025.chipsal-1.20/) versus ~5% for
Spanish, and an [agricultural ASR benchmark](https://arxiv.org/pdf/2602.03868) finds the gap
concentrates in "crop designations, agrochemical names, and measurement specifications" — product,
rate, quantity. Pin `large-v3`; the small model is not usable.

**Finding 2 — Edge TTS has no `pa-IN` voice at all.** Hindi, Gujarati, Tamil, Telugu and Urdu ship;
Punjabi does not. Free spoken Punjabi therefore needs a self-hosted model.

**Finding 2b — verified by building it, 2026-08-22.** Every free Punjabi voice was checked
against the actual artefact, not the documentation:

| Option | Outcome |
|---|---|
| Edge TTS | No `pa-IN` voice at all |
| Piper | Voice list holds Hindi, Urdu, Bengali, Marathi, Nepali, Telugu, Malayalam — **no Punjabi**. Rules out the fastest CPU option |
| `indic-parler-tts` | Apache-2.0, far more popular, but only *unofficial* Punjabi |
| **AI4Bharat IndicF5** | **MIT, official Punjabi.** ✅ chosen 2026-08-22 — replaced 2026-08-23, see the amendment below |

⚠ **IndicF5's HuggingFace repo is GATED** (`gated=auto`). It is MIT-licensed, but downloading it
needs an account, one-time accepted terms, and a read token. Approval is automatic — a click, not
a review — but it is a human step no script can do, and the 401 it produces otherwise is cryptic.
`tools/punjabi-tts/speak.py` detects that specific failure and prints the three steps.

It lives in **its own venv**, not Hermes's: torch is ~2.5 GB and `hermes update` replaces the
Hermes venv wholesale, so isolation is what stops an upgrade silently removing Punjabi speech.
Hermes shells out to it via `terminal`. Output is cached by (text, reference voice) hash, because
templated broadcasts are byte-identical every time.

**Finding 3 — and this is the one that decides it — `facebook/mms-tts-pan` is CC-BY-NC 4.0.**
Non-commercial. A vineyard management business is commercial use, and **§D3 already established
that a non-commercial free tier is not a loophole** when it rejected Open-Meteo on identical
grounds. Disqualified. [AI4Bharat **IndicF5**](https://huggingface.co/ai4bharat/IndicF5) is
**MIT**, supports Punjabi, ~0.4B params, and runs locally. ✅ **chosen** (2026-08-22; see the
amendment below).

> **⚠ Amendment, 2026-08-23 — IndicF5 replaced by Google Cloud Text-to-Speech**
> (`pa-IN-Chirp3-HD-Puck`). One day in production was enough to falsify two assumptions:
>
> 1. **Latency.** The "runs in ~2 s" figure measured a warm interactive session. Production pays
>    a fresh process every call: **47–79 s per novel phrase**, measured through the live plugin
>    path and recorded honestly in `tools/punjabi-tts/STATUS.md`. A worker stops asking before
>    that comes back.
> 2. **Quality.** The owner judged the voice unusable for daily crew communication.
>
> The fix considered in-house — a resident TTS worker holding the model in memory — is real work
> that treats the symptom, not the quality complaint. Google Cloud TTS renders in ~1–2 s over the
> network, offers 38 `pa-IN` voices, and prices Chirp3-HD at $30/1M chars **after 1M free per
> month**, which this project's traffic will not approach.
>
> **The §D3 argument does NOT flip with it**, and it is worth saying why: mms-tts-pan stays
> disqualified because CC-BY-NC *forbids* commercial use at any price — a legal term, not a cost.
> Google Cloud TTS permits commercial use and charges for volume; it is the same category as the
> LLM gateway, not the same category as Open-Meteo's free tier. What is surrendered is the
> unconditional self-hosted "$0 forever" property: the bill is expected to be $0, but it is now a
> free *tier* with usage to watch, not a guarantee.

**Resolution:**

| Path | Mechanism | Cost |
|---|---|---|
| Punjabi **in** (voice) | Gateway faster-whisper, `large-v3` pinned | $0 |
| Punjabi **out** (text) | Gurmukhi from `templates/pa.yaml` | $0 |
| Punjabi **out** (voice) | Google Cloud TTS Chirp3-HD (`tools/punjabi-tts/`, own venv). **Working, verified 2026-08-23** — fresh render ~1-3 s, cache hit ~0 s | free tier: 1M chars/mo; projected bill **$0** |
| **Spray compliance** | **The applicator types his spray reports in English** | $0 |

**The last row is the load-bearing safety decision, not a convenience.** By the applicator's own
choice, the one flow that ends in a legal record involves **no transcription and no translation** —
he types English, BC wants the record in English, and what he wrote is what is logged. The
compliance path therefore does not depend on Punjabi ASR at all.

That is what makes Finding 1 tolerable. Rough transcription is confined to **task logs**,
questions, and ordinary conversation — not legally binding, so an error is an annoyance rather
than a hazard. And §3.1's confirmation gate still closes the loop: the card is **Gurmukhi text the
worker reads**, so a mistranscribed «8» for «6» is seen and corrected before anything commits.

**Consequent design change:** the Punjabi voice interview is **one field per message with numbers
read back**, not the bundled two-question Spanish flow. Short utterances transcribe far better.
More turns, deliberately.

**Documented upgrade, deliberately not required:** if correction turns per report climb, or workers
start routing around Hermes to a manager, a Punjabi-capable ASR API (Sarvam Saaras, ElevenLabs
Scribe) called from `execute_code` costs ~$3–10/mo and is a one-key change. Watch for the signal
rather than pre-buying.

✅ **Chosen (amended 2026-08-23).** `pa.yaml` moves from a P2 stub to a P1 deliverable; the
Punjabi vineyard glossary must be built **with the applicator**, not from a dictionary — what
matters is the words he uses for the products in your shed. The voice needs no reference
recording any more: Google Cloud TTS voices are pre-built, and swapping one is a one-line edit
to `VOICE` in `tools/punjabi-tts/speak.py`.

### D14 — **The voice reply is a plugin, because a shell hook silently cannot do it**

Built 2026-08-23. Hermes already answers Punjabi speakers in Gurmukhi, so speaking it back is a
thin layer: take the outgoing text, synthesize it with the D11 voice, and append a
`MEDIA:` tag the gateway turns into a native audio message. The text still goes out — the audio
rides alongside.

**Why it is not an instruction.** Telling Hermes to shell out to the TTS tool was tried twice — in
a skill and in `HERMES.md` — and fired zero times. The model has to *decide* to consult those, and
a two-word Punjabi question gives it nothing to trigger on. §3.0's lesson generalizes: for
behaviour that must happen every time, install it in the runtime rather than describing it.

**Why it is not a shell hook.** `transform_llm_output` accepts shell hooks, and the obvious build
is a `.cmd` that rewrites the response. It cannot work, and — the expensive part — it fails
*silently*. Two independent blockers in Hermes 0.20.4, both read in the source:

  * `agent/shell_hooks.py:_parse_response` returns `{"context": …}` or `None` for any
    non-blocking event. A hook's `{"response_text": …}` is parsed, found uninteresting, dropped.
  * `agent/turn_finalizer.py` applies a result only when `isinstance(result, str)`, but the
    shell-hook bridge is typed `Optional[Dict[str, Any]]` and can never return a bare string.

Nothing errors. The hook is spawned on every reply, does its work, and its output is discarded.
`hermes hooks doctor` reported **all four checks green** throughout — it verifies the script emits
valid JSON, not that the JSON is ever applied. A live Punjabi reply (406 chars, 243 of them
Gurmukhi — comfortably inside every threshold) produced no audio and no log line anywhere.

Two smaller traps on the same path, recorded so they are not rediscovered:

  * `_serialize_payload` nests everything outside a fixed key set under `extra`, so a shell hook
    receives `payload["extra"]["response_text"]`, not `payload["response_text"]`.
  * `chcp 65001` in a `.cmd` wrapper makes the script return **zero bytes** when stdout is a pipe.
    Hermes treats empty output as "no change" and sends the plain text — another silent path.
    Python's own `sys.stdout.reconfigure(encoding="utf-8")` is the fix; `chcp` is not needed.

✅ **Chosen: a user plugin** (`~/.hermes/plugins/punjabi-voice/`) registering `transform_llm_output`
and returning a string. Logic lives in the repo at `hermes/voice/punjabi_voice.py` so it stays
version-controlled and tested (`tests/test_punjabi_voice.py`, 10 tests); the plugin is a shim.
Verified applied end-to-end on a real turn, which is the only evidence that counts here — every
intermediate check had been green while the feature did nothing.

**Deliberately conservative.** Speaks only when the text actually contains Gurmukhi (never guess a
language), is ≤600 chars (a long report is better read), and synthesizes inside the timeout. Every
failure path returns the text unchanged: a missing voice note is a small loss, a dropped reply is a
worker left waiting. Renders are content-addressed and keyed on the voice (speak.py's contents —
that is where the `VOICE` constant lives), so a repeated broadcast is instant while a novel
sentence costs ~1-3 s over the network. The 47–79 s IndicF5 era is gone; see
`tools/punjabi-tts/STATUS.md`.

**Note for the Dell/Ubuntu move:** plugins are opt-in — `hermes plugins enable punjabi-voice` is a
required step, and its absence looks exactly like the feature being broken.

## 4. Language layer — three languages, all in production

Every contact row has `lang` (`es`, `en`, `pa`) — the schema already permitted all three (docs/02
§2). All user-facing strings live in `templates/{lang}.yaml` (docs/07 §0 layout); cross-language
relay goes through one translate step with the vineyard glossary.

| Lang | Who | In | Out |
|---|---|---|---|
| `es` | SAWP crew | Voice or text | Text + Edge TTS voice replies |
| `pa` | Punjabi workers incl. **the applicator** | Voice only | Gurmukhi text only (§D11) |
| `en` | Managers, owner | Text | Text + email |

Punjabi **managers** remain a P2 item, and are now trivial: `pa.yaml` will already exist.

## 5. Monthly cost estimate (USD)

| Item | Est. |
|---|---|
| Hosting (dedicated partition on owner's existing Dell) | **$0** |
| Hermes Agent (MIT, self-hosted) | **$0** |
| WhatsApp via Baileys (no Meta fees, no templates) | **$0** |
| Weather: ECCC (free commercial licence) | **$0** |
| LLM via 9router gateway | **$0** |
| Gmail (IMAP/SMTP), healthchecks.io free tier | **$0** |
| Domain / TLS — **not needed**, no inbound endpoint | **$0** |
| Punjabi ASR (faster-whisper `large-v3`, local) — §D11 | **$0** |
| Punjabi TTS: Google Cloud Chirp3-HD, free under 1M chars/mo (then $30/1M) — §D11 | **$0 expected** |
| **Total** | **$0/mo expected** |

§D11 adds two-way Punjabi. Transcription is local; the Punjabi voice moved to Google Cloud TTS on
2026-08-23 (amendment above) — free under 1M characters/month at this project's scale, but a
monitored usage line rather than a structural guarantee. The one paid escape hatch (~$3–10/mo for
a better Punjabi ASR) is documented and deliberately not taken until the local path proves too
rough.

One-time: prepaid SIM for the bot's dedicated WhatsApp number (~CA$10–25). Electricity for the
Dell is the only true recurring cost. Optional upgrades if ever wanted: Open-Meteo Standard
(US$29/mo), a VPS (US$6/mo), Nous Portal subscription.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Bot number banned (Baileys/ToS)** | Dedicated prepaid number, never the business line. Conversational usage only; no unsolicited outbound to non-enrolled numbers. Data is in SQLite and unaffected. Recovery: new SIM + re-pair (~30 min). Escalation: migrate to Cloud API (D1) |
| **Baileys breaks on a WhatsApp Web protocol update** ✅ documented upstream | Expected periodically. Watchdog detects it (no heartbeat) → owner alerted → `hermes update` usually restores it. Session state at `~/.hermes/platforms/whatsapp/session` ✅ survives protocol updates unless manually unlinked, so most breakage is *not* a re-pair. Interim: managers relay by phone. Pin a known-good version before harvest |
| **Gateway not running → every cron job silently never fires** ✅ | The single most likely way this system dies quietly. Cron is ticked by the **gateway** process, not by a CLI session (docs/03 §0). Install it as a system service (`sudo hermes gateway install --system`), and the 15-min heartbeat asserts gateway liveness, not just process liveness (docs/03 §7) |
| **Agent skips confirmation or invents a field** | Structural, not prompt-based: confirmation-token gate, server-side validation, `raw_message` verbatim (§3) |
| **Agent memory drifts from the database** | Memory is never authoritative. Reports query the DB via tools; the agent may not assert a logged fact it did not read back from a tool call |
| **Hermes does something surprising** (the accepted cost of D8) | Not prevented — bounded by transparency. Every autonomous choice writes `agent.decision` with its reasoning (§3.1) and surfaces in the EOD 🧭 line, so a wrong pattern is visible within a day and correctable by editing a skill. Contrast with the four hard gates (§3), which *are* prevented |
| **Over-messaging** — an eager agent nudging people too often | Rate limits enforced in the send tool, not by instruction (docs/03 §4); `ALTO/STOP` honoured for everything except safety; managers see the message count in the EOD 🧭 line |
| **Skill drift** — a self-written skill quietly degrades a compliance flow (drops a PPE question, shortens the confirmation) | Two-tier policy (§3.2): compliance skills gated behind `write_approval`, all skills git-versioned with nightly commits and a monthly review summary. Below both, the §3 obligations are Python — no skill edit can remove them. This is the failure mode that looks like success, so it gets belt *and* braces |
| Weather source down at 05:45 | Degrade ladder, STALE flag, fail-safe NO verdict, never silent (docs/03 §3) |
| LLM mis-parses a spray report | Nothing commits without the worker confirming a Spanish summary card; raw message stored verbatim |
| 9router unreachable (Tailscale/VPN) | Fallback provider in config; keyword commands work with no LLM at all |
| Worker adoption | 1-page Spanish SOP, voice notes accepted, ≤2 follow-ups per report, training week with a manager champion |
| **Dell dies / disk loss** | Nightly `.backup` + copy off-box (email/rclone), 30 daily + 12 monthly retained; restore runbook docs/04 §9. Migration to cloud is a documented 1-hour path (D6) |
| Dell asleep, or boots into Windows | Sleep/hibernate disabled in BIOS; GRUB defaults to Ubuntu with a short timeout so an absent-minded reboot doesn't strand it in Windows; healthchecks.io catches a missed job within ~30 min either way |
| REI data wrong | `products.verified` flag; tools refuse to state REI from unverified rows and ask instead (§3.4) |
| Upstream (Nous) changes or abandons Hermes Agent | MIT-licensed and self-hosted — the installed version keeps working. Compliance core is runtime-agnostic; D0's bespoke fallback stays viable |

## 7. Hermes Agent capabilities we're using (~40 built-in tools ✅)

Verified 2026-08-20 against v0.20.4. Tool names below are the **real** ones. Under D9 this table is
no longer "nice extras" — `terminal` and `execute_code` are the load-bearing entries, because they
are what let Hermes do weather, listings, exports and backups without us writing modules.

### 7.1 Adopted in the core build — free, no extra keys

| Capability | Tool | Vineyard use |
|---|---|---|
| **Run code** | `execute_code` ✅ | **D9's engine.** Fetch ECCC XML, poll IMAP, build XLSX, run seasonal analysis nobody pre-built. Python with tool-call access |
| **Run commands** | `terminal` ✅ (+ `process` for background) | Backups, git commits of the skills dir, `sqlite3` maintenance, anything shell |
| **Read/write files** | `read_file`, `patch` ✅ | Hermes edits its own config, seed CSVs, templates, and skills |
| **Voice-note transcription** | built into the gateway ✅ — faster-whisper, Groq, or OpenAI | Inbound WhatsApp `.ogg` voice notes are auto-transcribed and injected as text. **faster-whisper runs locally = $0 and no key.** Crews talk faster than they type, in the sun, with gloves on |
| **Voice replies (TTS)** | `text_to_speech` — **Edge TTS is free, no API key** ✅ (9 other providers available, all paid) | **The accessibility win.** Hermes *speaks* the morning brief and REI warnings in Spanish. Literacy varies on a SAWP crew; a spoken «NO ENTRAR al bloque 3» reaches people a text message does not. Output is MP3; `[[audio_as_voice]]` ✅ promotes it to a native voice bubble |
| **Vision** | `vision_analyze` ✅ (auxiliary provider configurable) | Product-label photos → trade name + PCP number, **and pest/disease photos** — a worker photographs powdery mildew and gets an answer plus a manager flag |
| **Delegation** | `delegate_task` ✅ — subagents with isolated context and terminal | Parse a listings backlog or build a month of exports without blocking the crew conversation (§D8) |
| **History search** | `session_search` ✅ — FTS5 over past sessions | "What did Juan say about B3 last month?" Complements the compliance DB: the DB holds committed records, this holds the conversation around them |
| **Scheduling** | `cronjob` ✅ — create/list/update/pause/resume/run/remove | docs/03 §1 |
| **Memory** | `memory` ✅ — persistent facts, capped ~800 tokens | Per-worker habits and manager preferences (never compliance facts — §D2) |
| **Task lists** | `todo` ✅ — session-scoped | Multi-step interviews and follow-up chains |
| **Ask a human** | `clarify` ✅ | Structured "I need a manager's call on this" |

### 7.2 Paid or deferred

| Capability | Status |
|---|---|
| **Web search / extract** (`web_search`, `web_extract`) | **Tool Gateway tools** ✅ — bundled with a paid Nous Portal subscription, or a third-party key. The only thing here that breaks the $0 stack. Note D9 makes this *less* necessary: fetching a **known** URL (ECCC, a PMRA label page) needs only `execute_code` + httpx, which is free. `web_search` is for when we don't know the URL. Revisit in P2 |
| **Browser automation** (`browser_navigate`, `browser_snapshot`, `browser_vision`) | Tool Gateway / local Chrome via CDP ✅. Could query PMRA or Zealty directly, but D4 chose email ingest for legality and durability. P2 at earliest |
| **Home Assistant** (`ha_*`) | **The most interesting long-term option.** A vineyard runs frost fans, sprinklers, irrigation. Hermes already computes frost risk (docs/03 §1) — with HA it could *act* at 3 AM instead of messaging a sleeping manager. Deferred because actuating physical equipment needs its own safety design, interlocks, and a manual override story. **P3, owner sign-off only** |
| **Other messaging platforms** (20+ ✅ — Telegram, Discord, Slack, Signal, Email) | Managers who prefer Signal or Telegram: one config line, no code. `hermes send` ✅ delivers one-shot messages without a gateway loop — a clean path for the manager email/SMS backup. Offer once WhatsApp is stable |
| **Hermes as an MCP server** (`hermes mcp` ✅) | Exposes Hermes to other tools; makes a P3 dashboard cheap (§D5 cut it from scope) |
| **Image generation** (`image_generate`, FAL.ai) | Paid; no vineyard use worth the money |
| **Bot Mode** ✅ — multiple named bots with own roles/models/memory, deliberating in group chats | Genuinely interesting later: a "compliance" bot and a "field" bot with different models. Adds coordination failure modes for no P1 benefit. P2+ |

### 7.3 Still not covered by anything built-in

**Longitudinal recommendations.** "We used 40% more sulfur than last season." "B7 consistently runs
1.5× hours per acre." "Your best spray windows are at 6 AM but the crew starts at 8." Skill learning
is *procedural* memory — it makes Hermes better at running the process, not at analyzing the
business.

D9 narrows this gap but does not close it. `execute_code` gives Hermes everything it needs to
*answer* such a question when asked, and `cronjob` gives it a way to ask itself on a schedule ✅.
What is genuinely missing is **stored baselines** — a place to write "normal for B7" so a
comparison means something — and the judgement of which comparisons are worth reporting unprompted.
That is a schema addition plus a standing duty, not a capability gap. Scoped as P2 (§8), and
honestly useful only from season two when there is a season to compare against.

## 8. Roadmap

- **P0** — plan + scaffold ✅ (Fable, 2026-08-20); re-architected onto Hermes Agent (2026-08-20)
- **P1** — core build, milestones M0–M8 (Opus, docs/07). **Now includes what used to be P1.5:**
  voice-note transcription, voice replies in Spanish, and vision (labels + pest/disease photos) —
  all built into the runtime (§7.1), so they cost configuration rather than development
- **P2** — **longitudinal recommendations** (§7.3 — the biggest remaining gap); Punjabi *manager*
  layer; PHI/harvest-interval guard; payroll-ready hours export polish; listings price-change
  tracking; product inventory decrement; web search for label/pest lookup if a key is worth buying
- **P3 (only if asked)** — **Home Assistant frost actuation** (§7.2 — needs its own safety design
  and owner sign-off); read-only web dashboard (`hermes mcp` ✅ exposes Hermes itself, making one nearly
  free); additional manager platforms (Signal/Telegram)
