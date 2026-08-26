# Vineyard operations on Hermes Agent

A working deployment of **[Hermes Agent](https://hermes-agent.nousresearch.com)** (Nous Research,
MIT) that runs the day-to-day operations of a 70-acre vineyard management business in the Okanagan
Valley, BC — Penticton, Naramata, Oliver.

Hermes talks to the crew over WhatsApp in **Spanish and Punjabi**, keeps BC-compliant spray
records, sends trilingual weather and spray-window briefs, watches for new vineyard listings,
reports to English-speaking managers — and writes down what it learns so next season costs less
than this one.

Punjabi is live in **both directions** and it is Phase 1, not a later phase: workers speak Punjabi
voice notes, and Hermes replies in Gurmukhi text and can speak Punjabi aloud through Google Cloud
TTS (`pa-IN-Chirp3-HD-Puck`; free under 1M chars/month). The spray applicator types his **spray
reports in English** by choice — which is what keeps the one legally binding flow free of any
transcription or translation (docs/01 §D11).

## There is one Hermes

**Hermes is the Nous Research agent.** This repo is not a second product with an unfortunate name
collision — it is the **configuration, identity, skills, and compliance kernel** that turn a stock
Hermes Agent install into this vineyard's operations manager.

Nothing here reimplements anything Hermes already does. There is no WhatsApp client, no LLM
client, no scheduler, no web server, and no weather, listings, export, or report module. Hermes
has `execute_code` and `terminal`; it fetches the forecast itself, reads the listings inbox
itself, and writes the Excel itself.

What this repo actually contains:

| Path | What it is |
|---|---|
| `SOUL.md` | Hermes's identity here — operations manager, not assistant. Deploys to `~/.hermes/SOUL.md` |
| `HERMES.md` | The standing brief. Auto-loaded as the project context file in **every** session, including scheduled ones |
| `.hermes/skills/` | 14 project-local skills, git-versioned, loaded via `skills.external_dirs` |
| `.hermes/skill-bundles/` | `/dia` (daily ops) and `/cumplimiento` (compliance) stances |
| `hermes/config.yaml.example` | The runtime config: model, gateway, skills gating, memory, MCP, cron defaults |
| `hermes/cron/setup-jobs.sh` | The scheduled triggers, created through the CLI |
| `hermes/install/` | `bootstrap.sh` wires the repo into an install; `heartbeat.sh` asserts gateway liveness |
| `vineyard_mcp/` | The compliance kernel + advisory maths — the only code we write |
| `templates/` | Every user-facing string, in `es` / `en` / `pa` |
| `tools/punjabi-tts/` | Punjabi speech (Google Cloud TTS, `pa-IN-Chirp3-HD-Puck`). Isolated venv so `hermes update` cannot break it |
| `evals/` | Scores a model on whether it refuses to do the wrong thing when refusing is inconvenient |
| `docs/` | The spec: architecture and decisions, data model, automation, setup, message templates, build plan |

## Hermes is in charge

The governing design principle: **where a choice exists between hard-coding a behaviour and
letting Hermes decide, Hermes decides.**

Cron does not run scripts. It wakes Hermes with a situation and an appointment to think about it.
At 12:00 the midday trigger does not mean "send an update" — it means "look at the weather again
and decide whether anyone needs to hear about it." Sending nothing is a correct outcome. Every
discretionary choice writes an `agent.decision` row with its reasoning, so the owner can always
reconstruct why.

Hermes also notices things nobody asked it to watch: a worker gone quiet for three days, a block
sprayed twice in six days, a task logged inside an active re-entry interval, a listing that
matches what the owner has been hunting for. Those are `.hermes/skills/standing-duties/`, and the
list is explicitly non-exhaustive.

**Four things are enforced in Python, and they are not a leash.** They are the obligations Hermes
is accountable for, held below the prompt layer so a bad model day or an injected message cannot
break them — the same four a human vineyard manager operates under:

1. A compliance record commits only with the worker's «SÍ» on a confirmation card.
2. BC-required fields are validated server-side.
3. The worker's own words are kept verbatim.
4. An unverified re-entry interval is never asserted — Hermes asks for the label instead.

Plus two availability rules for when Hermes *isn't* running: the spray-window verdict is computed
in Python and fails safe to NO on degraded data, and emergency keywords are matched before any
LLM call.

## Hermes learns

Self-improvement is Hermes Agent's central mechanism, not an add-on, and this deployment leans on
it deliberately (`.hermes/skills/self-improvement/`).

After a non-trivial task, an error it recovered from, or **a correction from a person**, Hermes
distills a reusable skill with `skill_manage`. Skills are git-versioned in this repo and committed
nightly, so `git log .hermes/skills/` is the honest answer to "what did Hermes teach itself this
month," and a bad self-edit is a one-command revert.

- **Correcting Hermes is how you program it.** "Don't nudge Miguel on Fridays, he's off" is a
  durable change, not a one-time instruction. Tell the crew and the managers this explicitly.
- `skills.write_approval: true` is set **globally** — there is no per-skill gate upstream, and
  losing it on `spray-log` would be a compliance failure, so the friction on ordinary skills is
  the price. Review with `/skills pending` → `/skills diff` → `/skills approve`.
- `/learn <url|directory|"a described procedure">` builds a skill from a source without anyone
  authoring it — the fastest way to teach it the BC IPM regulation or a product label.
- `/journey` is the monthly review: the timeline of memory and skills, with pruning.

Memory holds small durable facts (Juan reports by voice), capped and lossy by design. **Compliance
facts never live there** — `MEMORY.md` is 2200 characters and gets compressed. SQLite is the
record.

## Start here

You can build and exercise the entire system **today, on Windows, with no SIM and no Ubuntu box**:
there is a native Windows installer, and `hermes chat` drives every flow without a messaging
platform attached.

    # 1. Install Hermes Agent
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash   # Linux/macOS/WSL2
    iex (irm https://hermes-agent.nousresearch.com/install.ps1)          # Windows

    # 2. Wire in this repo
    hermes/install/bootstrap.sh

    # 3. Pick a model, then talk to it
    hermes model && hermes doctor && hermes chat

`vineyard_mcp/` still has to be built — that is `docs/07-BUILD-PLAN.md`, and it is a much smaller
build than it looks, because it is only the compliance kernel.

## Read in this order

| Doc | What it is |
|---|---|
| `docs/01-ARCHITECTURE.md` | Components, data flow, decision records with rationale, cost, risks, roadmap |
| `docs/02-DATA-MODEL.md` | SQLite DDL, BC compliance field mapping, append-only + corrections design |
| `docs/03-AUTOMATION.md` | Trigger schedule, job contract, weather degrade ladder, REI monitoring |
| `docs/04-SETUP-GUIDE.md` | Non-technical owner guide: install, QR pairing, first run, crew onboarding |
| `docs/05-MESSAGE-TEMPLATES.md` | Every message, three languages (ES + PA workers / EN manager) |
| `docs/06-SOP-TRABAJADORES.md` | One-page worker SOP in Spanish |
| `docs/07-BUILD-PLAN.md` | **Builder starts here.** Milestones, acceptance criteria, config appendices |
| `docs/08-GO-LIVE.md` | **The sequenced path to production** — phases, hard gates, owner vs builder, what runs in parallel |

## The decisions that matter

- **WhatsApp via the Baileys bridge** on a dedicated prepaid number. $0/message, no Meta
  verification, no template approval, free-form replies, and **group support** — so safety
  broadcasts reach the whole crew at once while compliance interviews stay 1:1. Accepted risks:
  unofficial, ban risk, periodic protocol breakage. The Meta Cloud API fallback is DM-only, so
  migrating away would cost the crew group.
- **No public HTTPS endpoint.** Baileys connects outbound. No webhook, no domain, no TLS, no
  tunnel, no open port — the entire hosting and ingress problem disappears.
- **The top operational risk is boring:** cron is ticked by the **gateway** process, not by a chat
  session. No gateway, no jobs, no error — just a morning with no brief. Hence a boot-time service
  and a heartbeat that asserts *gateway* liveness rather than process liveness.
- **Storage is SQLite (WAL), append-only via triggers** — never agent memory. Managers get Excel
  as nightly and monthly *exports*, never direct database access.
- **Weather: Environment Canada primary**, free for commercial use. Open-Meteo's free tier is
  non-commercial, so it is only a fallback if the paid key is bought. Fail-safe "NO spray" when
  data is degraded.
- **Listings: email ingest only** (realtor MLS auto-search + Zealty alerts). No Realtor.ca
  scraping.
- **Hosting:** Ubuntu Server 24.04 on its own partition of the owner's Dell, systemd-supervised,
  GRUB defaulting to Ubuntu.

**Estimated running cost: US$0/month** in practice — transcription is local, and the Punjabi voice
is Google Cloud TTS, whose first 1M characters/month are free (then $30/1M; crew traffic sits far
under the allowance). Unlike the rest of this table it is a free *tier*, not a free *product*: if
traffic ever exploded, that line would start costing money. The only one-time cost is a prepaid
SIM (~CA$10–25) for the bot's dedicated number.

---

Verified against Hermes Agent **v0.20.4**. Upstream moves fast — re-check against the installed
version at build time, and treat `docs/07 §Verified capabilities` as the audit trail for what was
confirmed and when.
