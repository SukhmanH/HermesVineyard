# 08 — Go-Live Plan

The sequenced path from this repo to a system the crew uses every day. `docs/07` is the *build*
task list; this is the *order of operations*, including everything that is not code.

**Two tracks run in parallel.** The build (Phases 1, 3, 5, 6) and the owner's gathering (Phase 2)
are independent until Phase 4. Starting Phase 2 late is the most common way a project like this
slips, because label verification and a SIM card cannot be rushed at the end.

Legend: 🔨 builder · 👤 owner · 🔒 hard gate — do not proceed past it

---

## Phase 0 — Prove the control plane (today, ~1 hour) 🔨👤

No SIM, no Ubuntu, no seed data, no money. Do this first: it turns an abstract plan into something
you can talk to, and it validates that the identity/skills layer actually loads.

1. Install Hermes Agent on the existing Windows machine —
   `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
2. `hermes/install/bootstrap.sh` from this repo (Git Bash ships with the installer).
3. `hermes model` — point at 9router over Tailscale, **pin a specific model**. If 9router is not
   reachable yet, use any provider to unblock; this is swappable later.
4. `hermes doctor` — must pass.
5. `hermes chat`, then:
   - `skills_list()` → **12 skills** appear, tagged `[project]`
   - Ask "what are you responsible for?" → it should answer as the operations manager, citing
     standing duties. If it answers like a generic assistant, `SOUL.md` did not load.
   - Ask "what happens if you're not sure about a re-entry interval?" → it should say it asks for
     the label rather than guessing.

🔒 **Gate:** the 12 skills load and Hermes describes its own authority correctly. If not, nothing
downstream behaves as designed — fix this before writing a line of Python.

---

## Phase 1 — Build the compliance kernel 🔨 — ✅ **DONE 2026-08-21**

`docs/07` M0, M1, M3, M5. Nothing here needed WhatsApp, the Dell, or real data.

- [x] `schema.sql` from `docs/02 §2`, append-only triggers included
- [x] `vineyard_mcp/`: `config.py`, `db.py`, `compliance.py`, `weather_math.py`, `queries.py`,
      `server.py`, `cli.py`
- [x] Draft/commit/correction path with the `confirm_token` gate
- [x] `compute_spray_window()` — pure, fails safe to NO on stale or missing wind
- [x] `query_logs`, `rei_active`, `get_situation`, `log_decision`, `job_start`/`job_finish`/`skip_job`
- [x] `seed/*.csv` with example rows (owner replaces the values in Phase 2)
- [x] MCP server registered — **22 tools**, verified over stdio
- [x] `SOUL.md` installed to `$HERMES_HOME`; 12 project skills loading
- [x] `templates/es.yaml`, `en.yaml`, `pa.yaml` written from `docs/05`. **`pa.yaml` is
      drafted but UNREVIEWED** — `doctor` blocks on it until a Punjabi speaker signs off
      (`meta.reviewed_by`), because two of its strings are safety warnings and a clumsy safety
      warning is worse than none. That review is a Phase 3 item.

🔒 **Gate — PASSED.** 68 pytest cases green with no LLM in the loop, `ruff` clean. Specifically
asserted: commit without a token fails; a consumed token fails; a cross-intent token fails; an
unverified product yields no REI; a correction leaves the original **byte-identical**; direct
`UPDATE`/`DELETE` raise the trigger; `rei_expires_at_utc` is correct across the 2026-03-08 DST
boundary; stale or wind-less forecast data yields NO however good the rest looks.

**One real bug caught by the tests**, worth remembering because it is the failure mode this
whole layer exists to prevent: block resolution matched the word "one" in *"the far one by the
road"* and silently resolved it to block B1. Number-word substitution now only fires on a bare
block reference, ambiguous numbers return `None`, and both cases have regression guards.

---

## Phase 2 — Owner gathering 👤 — **start this now, in parallel**

Nothing here is hard. Several items have lead times measured in days, and one is genuinely tedious.

**Data**

- [ ] `blocks.csv` — code, name, site, acres, variety, rows
- [ ] `contacts.csv` — phone, name, **`lang` per person** (`es` / `pa` / `en`), role,
      applicator certificate number
- [ ] `products.csv` — every product in the spray shed
- [ ] ⚠️ **Label-verify every product**: PCP number, REI, PHI, max temp, read off the physical
      label. **This is the tedious, legally load-bearing one.** Until a product is verified,
      Hermes refuses to state its re-entry interval — by design. An unverified shed means a
      crew that gets "ask your manager" instead of an answer, all season.
- [x] ~~ECCC citypage site codes~~ **DONE 2026-08-21** - but **confirm the two substitutions**:
      Naramata reads Summerland (6 km, across the lake; alternative is Penticton at 13 km on the
      same shoreline) and Oliver reads Osoyoos (18 km south, a hotter pocket - watch the sulfur
      temperature ceiling). Wind on a bench is not wind at the station, and wind is what the
      drift call turns on. Override in `config/settings.yaml` if they read wrong.

**Punjabi** (§D11)

- [ ] A **~10-second Punjabi voice recording** from a willing crew member, with explicit
      permission, plus an exact written transcript. This becomes the voice Hermes speaks in.
- [ ] **20 minutes with the applicator**, writing down in his words what he calls each product
      and each pest. This goes in `pa.yaml`. Not from a dictionary.
- [ ] Ask the applicator which language he wants **briefs and alerts** in. He types spray reports
      in English; that does not tell you how he wants to read a frost warning.

**Accounts**

- [ ] Dedicated prepaid SIM (~CA$10–25), WhatsApp registered on it.
      **Never a personal or main business number** — this is the number carrying ban risk.
- [ ] Bot added to the crew's WhatsApp group **as a participant**
- [ ] Gmail for Hermes + app password
- [ ] Zealty saved search → alerts to that Gmail
- [ ] Realtor MLS auto-email search → same Gmail (ask your realtor; 10 min of their time)
- [ ] healthchecks.io free account

**Hardware**

- [ ] Dell freed up, on wired ethernet if possible
- [ ] **Back up anything on it you'd hate to lose** before Phase 7 touches the partition table
- [ ] Sleep/hibernate disabled in BIOS *and* Windows power settings

---

## Phase 3 — Language + the Punjabi risk gate 🔨👤

This is the phase most likely to change the plan, so do it **before** WhatsApp, not after.

- [ ] **Review `templates/pa.yaml` with the applicator.** It is drafted; every line needs
      reading aloud and correcting to what he would actually say. Highest priority: `rei_alert`
      and `frost_alert`. Fill in `meta.reviewed_by` and `meta.reviewed_at` — `doctor` fails
      until you do.
- [x] ~~Punjabi TTS engine~~ **DONE, twice.** IndicF5 self-hosted 2026-08-22; **replaced with
      Google Cloud TTS (`pa-IN-Chirp3-HD-Puck`) 2026-08-23** — novel renders went from 47–79 s to
      ~1–3 s, and quality went from rejected by the owner to chosen by the owner. One-time setup
      on any new host: `bash tools/punjabi-tts/setup.sh`, then `gcloud auth
      application-default login` (billing project account), then `python speak.py --setup`.
- [x] ~~GPU transcription~~ **DONE.** `stt.language` was pinned to `en`, force-decoding Spanish
      and Punjabi as English — confident nonsense, no error. Now auto-detect, `large-v3`, and
      CUDA enabled: **RTF 1.97x → 0.18x**, a 30 s note in 5 s instead of 60 s.
      `hermes/install/enable-gpu-stt.sh` **must be re-run after every `hermes update`**.
- [x] ~~Replies are spoken automatically~~ **DONE 2026-08-23.** Any Gurmukhi reply ≤600 chars
      ships with a playable audio message alongside the text. Built as a **plugin**, not a shell
      hook — a shell hook cannot transform LLM output and fails silently while `hooks doctor`
      reports all-green (§D14 in `docs/01-ARCHITECTURE.md`).
      **Required on a new host, easy to forget:**
      ```
      hermes plugins enable punjabi-voice     # plugins are opt-in
      hermes gateway restart                  # plugins load at startup
      ```
      Missing either step looks exactly like the feature being broken: text arrives, no audio,
      nothing in the log. Verify by sending Gurmukhi and confirming audio comes back — not by
      checking config, which looked correct the whole time it was failing.
- [ ] **Pick the final voice WITH the applicator.** The default is `pa-IN-Chirp3-HD-Puck`
      (owner's pick). Preview all 38 `pa-IN` voices in the console's voice picker; changing it is
      a one-line edit to `VOICE` in `tools/punjabi-tts/speak.py`, and both caches invalidate
      automatically. They will hear this voice every morning.
- [ ] **The measurement:** a Punjabi worker records **five real task reports**. Count correction
      turns per report.

🔒 **Gate — a real decision, not a formality:**

| Result | Action |
|---|---|
| ~1 correction turn per report | Free stack holds. Proceed. |
| 2–3 turns | Marginal. Tighten to one field per question, re-measure. |
| 4+ turns, or the worker gives up | **Buy the ASR upgrade** (Sarvam/ElevenLabs, ~$3–10/mo). One key in `.env`. Do not ship a flow people abandon. |

Also confirm: the applicator's **typed English** spray report runs end to end and commits a
correct row. That is the legally binding path and it must be boring and reliable.

---

## Phase 4 — WhatsApp 🔨👤

`docs/07` M2. Needs the SIM from Phase 2.

- [ ] `hermes whatsapp` → QR pair from the bot's phone (owner scans)
- [ ] **Capture the crew group JID** and put it in `.env` as `CREW_GROUP_JID`
- [ ] `group_policy: allowlist`, `group_allow_from: [<JID>]`, `require_mention: false`
- [ ] `unauthorized_dm_behavior: ignore` — strangers get nothing, enrolment is a manager's job
- [ ] Keyword fast-path (CLIMA/AYUDA/ALTO/EXPORT/CORREGIR + emergency) resolving **before** any
      LLM call
- [ ] Consent + rate limits enforced **in the send tool**, not as instructions
- [ ] `chmod 700` the session directory and add it to the backup set

🔒 **Gate:** real phone round trip in each language; a group message arrives with `is_group=1`; a
duplicate message id processes once; `ALTO` suppresses an EOD nudge but **not** an REI alert; a
send to a non-consented number is refused and audit-logged.

---

## Phase 5 — Automation 🔨

`docs/07` M6. The phase with the project's top operational risk in it.

- [x] ~~Confirm the cron flag names~~ **DONE 2026-08-22.** `--schedule`, `--prompt`,
      `--context-from` and `--continuity` did **not exist**; schedule and prompt are positional,
      and `--workdir` (missing entirely) is mandatory or the job loads no `HERMES.md` at all.
      `setup-jobs.sh` rewritten and a real job was created, run, and verified to load
      `HERMES.md` + `SOUL.md` + an attached skill. See docs/03 §0.5.
- [x] ~~Agent-side libraries~~ **DONE.** `execute_code` runs on the **Hermes agent venv**, not
      your shell's Python; installed there with uv and verified through `execute_code` itself.
- [x] ~~heartbeat~~ **DONE.** Rewritten around `cron/ticker_heartbeat`; both failure branches
      tested. Note `gateway status` exits 0 when down.
- [ ] `CREW_GROUP_JID=... hermes/cron/setup-jobs.sh`
- [ ] `timezone: America/Vancouver` **and verify the system clock**
- [ ] `sudo hermes gateway install --system`

🔒 **Gate:** a job **actually fires on schedule** — not "the service is running". Re-running
`morning_brief` the same day is a no-op. A degraded weather source still produces the degraded
message rather than silence. A deliberate skip writes `agent.decision` with a reason and is
**distinguishable from a crash** in the audit log. Seed an anomaly (worker silent 4 days; block
sprayed twice in 5) and confirm Hermes surfaces it **without a dedicated tool existing for it**.

---

## Phase 6 — Listings, reports, exports 🔨

`docs/07` M7. No Python — these are skills driving `execute_code`.

- [ ] Fixture emails in the test inbox: a Zealty alert, an MLS auto-email, an irrelevant
      newsletter → 2 listings in, newsletter ignored, re-poll inserts nothing
- [ ] EOD report names every committed log, every active REI, every seeded anomaly

🔒 **Gate:** the monthly compliance workbook opens in Excel with the required sheets, superseded
rows flagged `SUPERSEDED-BY`, and an audit sheet. Assert on **facts present, not wording** —
phrasing varies by design and a golden-file text test would be a bug.

---

## Phase 7 — Production host 🔨👤

`docs/07` M8. Only now does Ubuntu matter.

- [ ] Back up the Dell (again, properly)
- [ ] Shrink the Windows partition, install Ubuntu Server 24.04 alongside, GRUB defaults to Ubuntu
      with a short timeout
- [ ] Reinstall the stack; copy `hermes.db`, `~/.hermes/`, `.env`; re-pair WhatsApp
- [ ] Tailscale joined; nightly backups + off-box copy; heartbeat registered

🔒 **Gate:** reboot the Dell → it boots straight to Ubuntu unattended → `hermes gateway status`
reports **connected** → **a cron job fires**. The reboot test is worthless without that last step.
Then kill the gateway deliberately and confirm the **email** alert arrives (WhatsApp is what's
broken, so it cannot be the alert channel).

---

## Phase 8 — Soft launch 👤

Do not switch the whole crew on at once.

1. **Week 1** — one manager and one willing Spanish-speaking worker. Real reports, real briefs.
2. **Week 2** — add the applicator. This is the compliance path; watch it closely.
3. **Week 3** — add the Punjabi crew, then everyone.

Tell the crew and the managers explicitly: **correcting Hermes is how you program it.** A manager
saying "don't nudge Miguel on Fridays" is a durable change. This is the highest-leverage thing
they can do and nobody does it unprompted.

**Watch weekly for the first month:**

- Correction turns per report, by language — the Punjabi number is the one to watch
- Message volume per worker — an over-eager agent is a real failure mode
- `agent.decision` rows — are its judgement calls ones you'd have made?
- `/skills pending` — approve or reject promptly; a week-old 200-line diff is not reviewable
- Unverified products still in use

---

## The critical path

Everything else can slip without moving go-live. These cannot:

**Phase 1 (kernel) → Phase 3 (Punjabi gate) → Phase 4 (WhatsApp) → Phase 5 (cron + gateway) → Phase 7 (host)**

Phase 2 gates Phases 3 and 4, which is exactly why it starts now.

## ⚠ REVERT BEFORE THE SPANISH CREW ONBOARDS

**`stt.language` is pinned to `'pa'`** (set 2026-08-22 at the owner's request). Auto-detect kept
misreading short Punjabi voice notes as Portuguese, Polish, Czech and Kannada; pinning removes
the guess.

**This breaks Spanish and English voice notes.** A Spanish note decoded as Punjabi produces
Gurmukhi gibberish, not an error — the same silent-wrong-language failure, pointed at a different
crew. It costs nothing today because only Sukhman (`pa`) is enrolled and the SAWP crew is not.

Before onboarding anyone who speaks Spanish or English:

1. Set `stt.language` and `stt.local.language` back to `''`
2. Restore the Spanish/English `initial_prompt` (currently Punjabi-only)
3. Rely on **per-contact forced transcription** instead — `resolve_contact` then
   `tools/transcribe.py --lang <their lang>`, the standing rule in `HERMES.md`

That per-contact path is the real solution; the global pin is a stopgap for a single-user test.

**Note on live config:** comments written into `~/.hermes/config.yaml` do NOT survive — Hermes
rewrites the file and strips them. Anything that needs to be remembered belongs in this repo,
not in the config.

## Do not go live until

- [ ] Every product in the shed is label-verified, or the crew knows why some get "ask your manager"
- [ ] The Punjabi correction-turn measurement was actually taken with a real worker
- [ ] A cron job has been observed firing after an unattended reboot
- [ ] The gateway-down email alert has been tested by killing the gateway
- [ ] A correction has been round-tripped and the original row confirmed byte-identical
- [ ] Someone other than the builder has read a morning brief and understood it
- [ ] **`stt.language` is back to `''`** if anyone but a Punjabi speaker will send voice notes
- [ ] **A spray verdict leaves a record.** Tested 2026-08-23 by asking whether B1 could be
      sprayed. Hermes fetched the forecast and called `compute_spray_window` — both correct;
      fetching is deliberately Hermes's job, since the tool is a pure function over hours it is
      handed. It then **never called `cache_weather`**, so a correct verdict was delivered with
      **no `weather_cache` row and no audit trail**. The answer was right and unreconstructable.
      Verify: ask a spray question, then confirm `SELECT COUNT(*) FROM weather_cache` increased.
      The row, not the confidence of the reply, is the evidence.
      *(An earlier draft of this entry blamed web search for bypassing the kernel. That was
      wrong — the fetch is supposed to come from the web; only the caching step was missing.)*
      (see the revert section above)
- [ ] A spray verdict has been observed coming from `compute_spray_window` — check that
      `weather_cache` gains a row and an `agent.decision` is written. Verified 2026-08-22 that
      Hermes will otherwise answer spray questions from a web search, which is exactly what
      §3's fail-safe exists to prevent
