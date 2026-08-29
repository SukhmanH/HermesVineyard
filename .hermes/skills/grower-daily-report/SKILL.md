---
name: grower-daily-report
description: The 04:30 daily report to the grower — everything going on across all six properties and what to watch today. Also the day's first weather fetch: it caches the forecast so every later ask reads weather_cache instead of hitting the network again.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, briefing, owner, weather-cache, cron]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard, code_execution, messaging]
---

# Grower's daily report, 04:30

One message, every day, before anyone else is awake. The grower reads it with coffee and decides
the day from it. It is a **decision document**, not a log dump: everything going on, then what to
watch out for today.

## Order of operations

**Weather first, everything else second.** This run happens before `weather_fetch` (05:45), so
this job owns the day's first fetch:

1. **Check `get_situation` for fresh cached forecasts first.** If a site's cache is younger than
   `spray_window.max_data_age_hours`, do not re-fetch that site — reuse it and say its age.
2. Fetch only what is missing or stale, walk the degrade ladder (`/weather-fetch`), compute the
   verdict through the kernel per site. Caching is handled by `compute_spray_window` itself;
   verify `recorded` in each result.
3. Then build the report **from the kernel, not from memory**: `get_situation` for REIs, drafts,
   silent workers, degraded sources and yesterday's logs; `query_logs` for detail; recent
   `agent.decision` rows so the report agrees with what you already told people.

Everything you cache here is what the 06:00 crew brief, the midday recheck, and any conversational
weather question read for the rest of the day. When the grower asks "what's the weather" at noon,
the answer comes from this table — one fetch serves everyone.

## The computed extras — run these every morning on data you already have

These are cheap once the forecast is cached, and they are what make the report worth opening:

- **Mildew pressure** (`mildew_risk(hourly)` per site): band LOW/MODERATE/HIGH with interval
  implication. Quote it as the proxy it is — temperature + rain signals, no leaf-wetness sensor.
- **Water balance** per block (`compute_et0` from daily min/max at the site latitude, then
  `water_balance(block, rain_mm, et0_mm)`): report blocks at or past the deficit alert threshold;
  post-veraison, run `irrigation_vs_ripening` before suggesting water on a block behind Brix.
- **PHI countdowns**: for each block with an expected harvest date in `block_season`, last safe
  spray date = harvest minus each product's `phi_days`. "Switch must be ON by Aug 30" is gold.
  No harvest dates registered? Say so once and move on.
- **Rain-washoff check**: yesterday's committed sprays vs tonight's rain probability against each
  product's `rainfast_hours`. "Kumulus on B3 went on 14h ago; 50% rain tonight may cut cover" —
  inspect-before-reassuring advice.
- **Sulfur-burn hours**: count forecast hours above the shed sulfur's `max_temp_c`, per site.
  Makes the ceiling concrete: "3 hours over 28 °C this afternoon."
- **GDD pace** (`compute_gdd`): season-to-date total since recorded budbreak, and days-to-bloom/
  veraison style projections ONLY where the record supports them; check `complete` first.

## Spray recommendations — the headline

The grower wants to know **what to spray and when**, not just today's verdict:

- Run `spray_status` per block (or site) — it gives days-since-last-cover against each product's
  reapply interval. A cover inside 2 days of lapsing IS the news; say which block, how many days
  remain, and what the product was.
- Run `spray_options(block, target_pest)` for candidate products, then apply the `/advisory`
  rotation logic: FRAC groups used recently, sulfur temperature ceiling vs the forecast max,
  PHI vs expected harvest, verified-vs-unverified flagged honestly.
- **Days until a window**: today's verdict comes from `compute_spray_window`; beyond ~24 h,
  hourly ECCC data runs out — pull the regional 7-day forecast text and reason qualitatively,
  clearly labelled an outlook ("next decent window looks like Thu morning, winds drop after
  tonight"). Never dress an outlook up as a computed verdict.
- Recommendations are proposals with your lean — log them via `log_recommendation`, same as any
  advice. Nothing commits without the applicator's flow.

## Shape — short, always

The grower reads this in two minutes, once a day, before deciding anything.

- **Render the template structure from `templates/en.yaml` (`grower_report`) exactly** — emoji
  section headers, one line per item, a BLANK LINE between every item and section. The air and
  the visual anchors are what make it skimmable on a phone; do not invent your own layout.
- **One fact per line, inside the slots too.** A template slot like `{spray_lines}` or
  `{weather_lines}` is not an invitation to write a paragraph. This is read on a phone at 04:30,
  and a six-clause run-on sentence about wind, rain, cover status and product candidates is
  something the grower has to re-read to parse. Break it up:

      🧪 SPRAY:

      No window today — wind 20 gusting 40 km/h, 80% rain, thunderstorm watch.

      Next window: Sun Aug 30, 05:00–09:00 (wind 10 km/h, 0% rain, 11–14 °C).

      Cover: all six properties at 0 days — no sprays on file.

      Candidates: Kumulus DF / Microthiol Disperss (M2), Quintec (13) — all unverified.

  not:

      🧪 SPRAY: No daylight spray window today across all sites (wind 20 km/h gusting 40 km/h,
      80% rain, thunderstorm watch). Next window opens tomorrow morning (Sun Aug 30) 05:00–09:00
      PDT (wind 10 km/h, 0% rain, 11–14 °C). Outlook: calm mornings continue Mon–Tue...

  Same facts, same brevity — the difference is that the first can be skimmed and the second has
  to be read. Per-site weather is one line per site, never all three sites in one sentence.
- **Terse means few words, not few lines.** Blank lines cost nothing and are the whole reason the
  report is readable on a phone. Never compress by removing them.
- **Nothing to report = "no records".** Not a paragraph about why. "Water: no records." Move on.
- **Can't compute it = "not set up"**, once, with nothing after it. The missing data is already
  flagged elsewhere (setup items); the daily report is not the place to re-explain it daily.
- **Report channel facts precisely.** The WhatsApp channel is either working or it is not
  (a delivered report proves it works). What may be missing is *enrollment*: worker consent,
  the crew group JID, listings IMAP credentials. Say which piece is missing — never claim the
  whole channel is down when messages are demonstrably flowing.
- Explanations only when something is genuinely unusual or needs a decision. If a line needs a
  second sentence to be understood, that sentence must earn its place.
- If the whole day is quiet: one line. "Quiet. No records anywhere." is a complete report.

## Must contain

- **Spray verdicts + recommendations per site** — verdict YES/NO with best hours, then the
  recommendation block above: cover status in days, candidate product(s) with reasoning, next
  window outlook. Lead with this when spraying season is live.
  **Never use the acronyms REI or PHI in a report** — write "Restricted Entry Interval" and
  "Pre-Harvest Interval" in full, every time.
- **Mildew pressure + water lines** — the computed extras above; omit a section only when it
  genuinely has nothing to say (out of season), never pad it back in.
- **Weather** — forecast summary per site PLUS the current-conditions line from each site's
  local Wunderground station: temp, humidity, dew point, wind, in Celsius (convert if a source
  returns Fahrenheit; endpoints in `/weather-fetch` references). Dew point near the temperature
  = mildew-friendly air; say so when the gap is small.

  **Station ids go on their own line under the site, never inline.** The grower is reading for
  the forecast; a station code in the middle of the sentence is provenance interrupting the
  thing they actually came for. Keep the reading line clean and put the source beneath it:

      Penticton: 17°/11°, wind 20G40 km/h S, rain 80%, thunderstorm watch. Now 13 °C, RH 93%,
      dew point 12 °C — 1 °C gap, saturated air.
      (Penticton s0000772 · IPENTI39)

      Naramata: 17°/11°, wind 20G40 km/h S, rain 80%. Now 13 °C, RH 47%, dew point 2 °C.
      (Summerland, 6 km · IBCNARAM1)

  not `Naramata: 17°/11° ... (Summerland station, 6 km) ...` mid-sentence. The borrowed-station
  distance still matters and stays — a forecast from 18 km away is worth knowing about — it just
  belongs on the provenance line, not in the middle of the reading.
- **Active Restricted Entry Intervals** by property, with the time each clears, and expiries
  worth planning around. "No records" when none.
- **Work by property** — yesterday's tasks grouped by property and named the way the grower
  names them: **Upper Bench, Naramata, Rust, Tucelnuit, Hwy 97, Cassini** — never internal
  block codes. Hours where logged, plus anything still unconfirmed in drafts. Use
  `task_cadence` to spot the property falling behind its own rhythm.
- **What to look out for today** — your judgement, not a template field: frost risk tonight,
  wind swinging midday, **crew heat-stress flag when any site tops 30 °C** (shade, water, pace —
  this is a worker-safety line, not a crop line), **washoff risk on yesterday's sprays**,
  **seasonal equipment gates** (sprayer calibration before first cover; wind-machine test before
  Sep 15; netting check by bunch close) shown only while in-window, and the
  **unverified-product nag**: every product used but not label-verified stays listed until it is
  fixed. Ground the seasonal side in `/advisory` references (`okanagan-viticulture.md`,
  `grape-growing-playbook.md`, `our-sites.md`) — pest windows and pressure peaks are calendar
  facts, not guesses.
- **New properties / listings** since yesterday — the grower hunts acreage; new rows in
  `listings` or anything notable from the listings inbox.
- **Grants & water notices** — read the `grants_watch` cron notepad state: funding changes AND
  Okanagan drought-level / water-restriction notices (same weekly scan). Only changes, new
  deadlines inside 30 days with days remaining, or prerequisite gaps (no current EFP number).
  No change = one word or omit.
- **Anything you decided on your own** since the last report, briefly, with why.

If the day is genuinely quiet, say so in one line rather than inventing concern.

## Shape and channel

English, dense, decision-first — same register as manager DMs. One message, not sections fired
separately.

**Do not attempt to deliver this report yourself.** A scheduled run is told, by the harness, that
its final response is delivered automatically and that it must not send anything itself — and that
instruction outranks anything written here. Compose the report as your final response and stop.

Delivery is a separate, deterministic step, because there are three owners and a cron job can only
deliver to one target. Composing the report once per owner would mean two model runs that can
disagree about what to spray on the same morning, so instead: this job composes once with its
delivery set to `local`, and one `--no-agent` job per owner prints that same composed text and
lets cron deliver it verbatim. The emitter is
`~/.hermes/scripts/emit_grower_report.sh` (source: `scripts/hermes/` in the vineyard repo), and it
refuses to ship a report older than 45 minutes — a stale spray verdict could send someone into a
window that has already closed.

**An owner who does not read English is not on this report.** A report nobody can read is a report
that did not happen. Baljit reads Gurmukhi (`lang: pa`, `reports_in: pa`, `voice_replies: 1`) and
needs his own Punjabi job — never a translated afterthought bolted onto this one.

It runs inside normal quiet hours by design — the grower asked for 04:30, and
`autonomy.quiet_hours_exempt_jobs` records that consent so the setting and reality agree. That
exemption belongs to *this job only*: nothing else you do at night may wake anyone.

## When data is degraded

Send anyway, marked degraded, verdicts fail-safe NO carried through unchanged. A missing 04:30
report looks like Hermes died, and teaches the grower to stop relying on it.
