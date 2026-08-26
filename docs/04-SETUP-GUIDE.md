# 04 — Setup Guide (non-technical)

Written for the owner/manager. Each step says who does it and roughly how long it takes.

**This got much shorter than the original plan.** Choosing Hermes Agent + Baileys removed Meta
business verification, message-template submission and approval, the domain purchase, the TLS
certificate, and the public webhook — along with their waiting periods. Nothing here blocks on a
third party except the SIM card.

## 0. You can start today — no SIM, no Ubuntu, no Dell ✅

Verification found a **native Windows installer**, and Hermes Agent's terminal chat exercises the
whole agent — LLM, tools, skills, database — with no messaging platform attached. So the build does
**not** block on the two things that take longest to arrange.

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```
(bundles uv, Python 3.11, Node, ripgrep, ffmpeg and a portable Git Bash — nothing to install first)

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash    # Linux / macOS / WSL2
```

Then, from this repo's folder:

```bash
hermes/install/bootstrap.sh   # installs SOUL.md + config, trusts the skills, checks the clock
hermes model                  # wizard: pick provider + model — PIN a specific one
hermes doctor                 # must pass before anything else
hermes chat                   # talk to it in the terminal
```

`bootstrap.sh` is what turns a stock Hermes install into *this vineyard's* Hermes: it copies
`SOUL.md` into the Hermes home (it is only ever loaded from there, never from a working folder),
installs the annotated config, runs `hermes skills trust` so the repo's 12 skills load, and
installs the libraries Hermes reaches for when it fetches weather or builds a workbook.

**This folder must be a git repository** — project-local skill discovery keys off the git root. If
you cloned it, you are fine. If you copied the files, run `git init` here first, or the skills
will silently not load.

What this gets you **without WhatsApp**: the compliance database and its append-only guarantees,
the spray-log interview, corrections, the spray-window verdict, weather fetching, listings parsing,
Excel exports, the EOD report, and the skills Hermes learns. Type «hice el spray de azufre en
bloque 3» into the terminal and the entire flow runs — the gateway is only how the crew reaches it.

What genuinely waits for the SIM: pairing (§2, §4), the crew group, voice notes over WhatsApp, and
the final round-trip test (§5). What waits for the Dell: 24/7 uptime and the boot-time service.

**One caveat:** cron jobs are ticked by the gateway process, not by a terminal session (docs/03 §0).
During local testing, fire jobs by hand with `hermes cron run <name>` — or run `hermes gateway run`
with a non-WhatsApp platform (or none) attached.

## 1. Things to gather first (owner, ~45 min)

- [ ] A **dedicated phone number for Hermes** — a cheap prepaid SIM (~CA$10–25 one-time). It needs
      to receive one SMS to activate WhatsApp, and the physical phone is needed once to scan a QR
      code. After that the SIM can sit in a drawer, but **keep it active** (top it up; a lapsed
      number can be recycled and the account lost).
      **Do NOT use your personal or main business WhatsApp number.** This is the number that
      carries the ban risk (docs/01 §D1), and it must be one you can afford to lose.
- [ ] Workers' WhatsApp numbers + full names, and each person's language (`es` / `pa` / `en`).
      Applicator certificate numbers are **not** collected — removed by owner decision,
      2026-08-21 (docs/02 §4).
- [ ] Block list: code, name, site, acres, variety (fills `seed/blocks.csv`).
- [ ] The products in your spray shed: trade name, PCP number **from the label**, REI, PHI.
- [ ] The **Dell** freed up, powered, on wired ethernet if possible, with sleep/hibernate disabled
      in both BIOS and Windows power settings.
- [ ] **Back up anything on the Dell you'd hate to lose** (docs/04 §4 shrinks the Windows partition
      to make room for Ubuntu — routine and low-risk, but it touches the live disk, so a backup
      first is the one non-negotiable precaution). Photos/files → external drive or cloud, per the
      earlier discussion.
- [ ] No credit card required — the running stack is free, two-way Punjabi included (docs/01 §5).
- [ ] **A ~10-second Punjabi voice recording** from a willing crew member, with their explicit
      permission, plus a written transcript of exactly what they said. This becomes the voice
      Hermes speaks Punjabi in (docs/01 §D11). A familiar-sounding voice lands better than a
      synthetic stranger.
- [ ] **Sit down with the spray applicator for 20 minutes** and write down, in his words, what he
      calls each product in the shed and each pest. That vocabulary goes into `templates/pa.yaml`
      and it is the difference between a system he uses and one he abandons. Do not build this
      list from a dictionary.

## 2. Set up the bot's WhatsApp account (owner, ~20 min)

1. Put the prepaid SIM in any spare phone.
2. Install WhatsApp, register the new number, verify by SMS.
3. Set the profile name to **Hermes Viñedo** and a recognizable photo (a grape/vineyard image) so
   the crew can identify it in their contacts.
4. Add the number to the crew's existing WhatsApp group — **as a normal participant.** This is
   what lets Hermes post the morning brief and REI warnings to the whole crew at once.
5. Leave the phone charged and nearby for the pairing step in §4. WhatsApp requires the primary
   phone to come online periodically to keep linked devices alive.

That's the entire messaging setup. No Facebook account, no Business Portfolio, no verification
documents, no template submission.

## 3. Other accounts (owner, ~30 min)

- [ ] **Gmail for Hermes** (e.g. hermes.vineyard@gmail.com) → enable 2FA → create an
      **App Password** (this is what goes in `.env`, never the real password).
- [ ] **Zealty.ca** free account → saved search: South/Central Okanagan, agricultural/acreage/
      vineyard, ≥2 acres → email alerts ON, sent to the Hermes Gmail.
- [ ] **Ask your realtor** (10 min of their time, free): set up an MLS auto-email search —
      vineyard / agricultural / acreage, Penticton–Naramata–Summerland–OK Falls–Oliver–Osoyoos —
      delivered to the Hermes Gmail. This is the best listings source we can legally get.
- [ ] **healthchecks.io** free account (the "is Hermes alive?" watchdog that emails you).
- [ ] Confirm **Tailscale** is installed and the 9router gateway is reachable, or decide on a
      fallback LLM provider (docs/01 §D7).

## 4. Installing (builder, per docs/07 M8 — owner assists at two points)

The builder shrinks the Windows partition to free up space, installs Ubuntu Server 24.04 into a new
partition alongside it (dual-boot via GRUB), then installs Hermes Agent and `vineyard-mcp` there,
and imports `seed/*.csv`. **Your existing Windows install and files are not touched** — they sit
untouched on their own partition; Ubuntu just gets a separate slice of the same disk. The Dell will
default to booting Ubuntu automatically; Windows stays reachable by selecting it at boot, but the
whole point of this setup is that you won't need to.

The owner is needed for exactly two things:

1. **Scan the QR code.** The builder runs `hermes whatsapp` on the Dell; a QR code appears in the
   terminal. On the bot's phone: WhatsApp → Settings → **Linked Devices** → **Link a Device** →
   point the camera at the screen. That pairs Hermes to the bot's WhatsApp account.
2. **Fill in `.env`** (guided template): Gmail app password, healthchecks URL, 9router key, owner
   phone number.

**The one thing that must be right, or nothing runs:** Hermes's background service has to be
installed and running. It is what delivers WhatsApp messages *and* what fires every scheduled job —
a terminal session does not (docs/03 §0).

```bash
sudo hermes gateway install --system     # boot-time service
hermes gateway status                    # confirm it is actually up
```

If this is not running, there is no error and no message — just a morning with no brief. That is
why the watchdog in §5 step 6 is not optional.

## 5. First-run smoke test (owner + builder, 15 min)

1. Owner sends «hola» to the Hermes number from their own WhatsApp → expects a Spanish/English
   greeting per their contact language.
1b. **The Punjabi test, and do not skip it.** Two parts. First: have a Punjabi worker send five
   real *task* reports as voice notes and count how many correction turns each takes — that is
   the honest measure of whether free transcription is good enough, and a benchmark number is not
   evidence. Second: confirm Hermes can speak a Punjabi message back, and that a worker finds the
   voice clear. If corrections are constant, the paid ASR upgrade in docs/01 §D11 is a one-key
   change.
1c. **Confirm the applicator's spray reports work in typed English**, end to end, and ask him
   which language he wants his briefs and alerts in. Do not assume.
2. Send «CLIMA» → expects the current weather block.
3. Send a fake spray report «hice azufre en bloque 3» → answer the follow-ups → confirm with «SÍ»
   → check the row appears in the nightly Excel (or send «EXPORT»).
4. Confirm the REI warning posted to the **crew group**, not just the DM.
5. Trip the failure path: builder blocks the weather source → confirm the degraded morning brief
   and the owner alert both arrive.
6. Trip the gateway path: builder stops the WhatsApp gateway → confirm the owner gets an **email**
   alert (docs/03 §7) — this is the failure that would otherwise be silent.

## 6. Onboarding the crew (manager, one morning)

1. Add each worker to `contacts` (builder provides an admin command / CSV import).
2. In the existing group chat, share Hermes' contact card + the Spanish SOP (docs/06) as an
   image/PDF.
3. Each worker sends «HOLA» to Hermes 1:1 → this records their consent timestamp and opens the
   private channel for their own logging. Hermes replies with a mini-tutorial in Spanish.
4. Explain the two channels plainly: **the group is where Hermes tells everyone things** (weather,
   NO ENTRAR); **the private chat is where you tell Hermes what you did.**
5. **Ask each worker: do you want the alerts as voice notes too?** Set `voice_replies` accordingly.
   Ask it as a plain preference, one-to-one, alongside the other onboarding questions — reading
   ability is not something to make anyone announce, and the honest answer is the useful one. Voice
   is *additional* to the text either way, so saying yes costs them nothing.
6. Show them they can send **photos of problems**, not just labels — powdery mildew, damaged
   clusters, anything odd. Catching disease a week earlier is worth more than any spray record.
7. First week: a manager watches the EOD reports and nudges anyone not reporting. (Adoption is a
   people problem — the champion matters more than the software.)
8. **Tell everyone that correcting Hermes is how you teach it.** Hermes distils what it learns into
   reusable procedures (docs/01 §3.2), and being corrected is one of the three things that triggers
   it. "Don't message me before 6" or "Miguel is off Fridays" is a permanent change, not a one-time
   request. This is the highest-leverage habit the crew and managers can build, and it costs them
   nothing — they just have to say the thing out loud instead of working around it.

## 7. Ongoing operations (owner)

- Managers get everything by WhatsApp + email; nobody touches the database.
- `EXPORT` by WhatsApp → current Excel on demand. Monthly compliance workbook arrives by email
  on the 1st — **file it; that's your BC 3-year record.**
- New product in the shed → tell Hermes («producto nuevo…») or ask a manager to add it; verify
  REI/PHI against the label when prompted.
- New worker → manager adds contact; worker texts HOLA; manager adds them to the group.
- **Keep the bot's SIM topped up and the Dell awake and booted into Ubuntu.** Those are the things
  that quietly kill the system. GRUB defaults to Ubuntu on its own, so this should stay a non-issue
  unless someone deliberately reboots into Windows.
- **Monthly: skim what Hermes taught itself.** The monthly email lists new and changed skills
  (docs/01 §3.2). Most will be sensible and you can ignore them. If one looks wrong, the builder
  reverts it with a single `git revert` — every skill change is versioned. Changes to the
  spray-logging procedures don't take effect at all until a human approves them, so this review is
  about quality, not safety.
- **Expect it to get better.** Second season should ask fewer questions and need less correcting
  than the first — Hermes accumulates procedures specific to your blocks, products, and crew. If it
  is *not* improving, that is a symptom worth reporting.

## 8. If the WhatsApp connection drops (owner, ~10 min)

Expect this occasionally — it is the accepted cost of the free path (docs/01 §D1). Symptoms: no
morning brief, and an email alert from the watchdog.

1. Most often it is **not** a re-pair. The saved session survives WhatsApp protocol updates unless
   the device was manually unlinked ✅, so try in this order:
   `hermes gateway status` → `hermes doctor --fix` → `hermes update` → restart the service. That
   fixes the majority of outages without touching the phone.
   If the session really was unlinked: builder runs `hermes whatsapp`, owner re-scans the QR.
2. If the bot's phone shows the account was **banned**, the number is gone. The database is
   unaffected — no records are lost. Get a new SIM, redo §2, re-pair, and tell the crew the contact
   changed. Consider migrating to the official Meta Cloud API (docs/01 §D1) if it happens twice.
3. While it is down, managers relay the weather call by phone. The spray-window rule of thumb is in
   the printed SOP; if in doubt, the answer is don't spray.

## 9. Disaster recovery (builder writes the runbook, owner keeps it printed)

Nightly database snapshots live in `backups/`, the monthly copy is in the owner's email, and the
`~/.hermes/` auth state is backed up alongside (docs/02 §6).

- **Dell dies** → new machine (or a cloud VM) → run installer → drop in latest snapshot + auth
  state → done. If the auth state restored cleanly, WhatsApp reconnects without a re-pair;
  otherwise re-scan the QR. Target: under an hour, at most one day of data lost — and even that day
  is recoverable from `messages_raw` on the old disk or from WhatsApp history.
- **Moving to a real server later** (Oracle ARM, a $6 VPS, anywhere) is the same procedure. Nothing
  in the system is tied to the Dell; there is no domain or IP to repoint because there is no
  inbound endpoint (docs/01 §D6).
