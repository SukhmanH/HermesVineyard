# Questions only the owner can answer

Each entry: question → why it blocks → what was done meanwhile. Work continues around all of these.

## Open

1. **Real block data** — acres, varieties, row counts, per-property block splits, irrigation
   type / emitter rate / vines-per-acre, soil type, budbreak dates this season.
   Blocks: any split of a property into multiple blocks? Current registry is one block per property.
   → Blocks: water balance, GDD pace, Pre-Harvest countdowns, spray-rate math.
   Meanwhile: intake/validation tooling built so data lands safely the moment it arrives.

2. **Product label reads** — someone must physically read PCP number + REI (+ PHI, rate) off the
   shed containers (start: Kumulus DF, Microthiol Disperss) so `verify_product` can unblock
   Restricted Entry Intervals.
   → Blocks: legal spraying advice, REI statements.
   Meanwhile: verification flow documented; kernel enforces the rest.

3. **Crew WhatsApp group JID** (and manager enrollment/consent for real worker numbers).
   → Blocks: crew briefs, NO-ENTRAR broadcasts reaching the real group; morning_brief currently
   delivers `local`.
   Meanwhile: jobs registered with local delivery; channel rules documented.

4. **Listings inbox IMAP credentials** (the dedicated email the owner forwards listings to).
   → Blocks: listings_poll actually seeing mail.
   Meanwhile: triage skill + notepad dedupe ready; job registered.

5. **healthchecks.io account/URL** (free dead-man's switch) for the heartbeat to ping.
   → Blocks: off-machine alerting if the gateway dies.
   Meanwhile: heartbeat job runs; script checks ticker freshness + gateway text.

6. **Payworks pay-period schedule** (weekly/biweekly? which day?) so the Sunday hours workbook
   headers match the real period.
   Meanwhile: workbook layout parameterized by pay-period dates from logs.

7. **Winery contracts** — buyer, Brix/TA/pH windows, harvest dates per property (or confirm the
   fruit is sold spot with no spec).
   → Blocks: Pre-Harvest countdowns, maturity_status conformance checks.
   Meanwhile: `set_fruit_target` flow ready; manager can set it by message.
