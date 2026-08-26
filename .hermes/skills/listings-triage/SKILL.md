---
name: listings-triage
description: Read the dedicated listings inbox over IMAP yourself, extract real Okanagan vineyard and acreage listings from realtor MLS auto-search and Zealty alert emails, dedupe, and decide what is worth interrupting the owner for today. Runs every 30 minutes, remembering what it has seen in its cron notepad.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, listings, imap, execute-code, real-estate]
    category: vineyard-ops
    requires_toolsets: [code_execution, mcp-vineyard]
---

# Listings triage

You read the inbox yourself with `execute_code`, `imapclient`, and `beautifulsoup4`. There is no
`listings.py`.

**Memory across runs is your cron notepad** — `hermes cron notepad <job_id> set/get` — a durable
key-value store that survives restarts. Keep the MLS numbers you have already reported there. (The
`continuity` flag described in older notes does not exist; the notepad replaces it and is better,
because it holds structured state rather than your last message.)

**Email ingest only. Never scrape Realtor.ca** — it is a CREA terms violation and a bot-detection
arms race that would break constantly.

## Sources

Two, both allowlisted in `LISTINGS_ALLOWED_SENDERS`:

- The owner realtor MLS auto-search email (freshest data, standard practice).
- Zealty.ca saved-search alerts.

Anything from another sender is not a listing source. Newsletters, market reports, and open-house
blasts are noise. Ignore them silently.

**Sender matching is subdomain-aware.** REALTOR.ca does NOT send listing alerts from
`*@realtor.ca` — they come from subdomains like `noreply@notifications.realtor.ca` and
`mlsnotifications.realtor.ca`. So a `*@realtor.ca` entry must match `dom == "realtor.ca" OR
dom.endswith(".realtor.ca")`, not an exact string compare. A literal exact-domain check silently
drops 100% of REALTOR.ca listing alerts (this bit the first triage run: UNSEEN returned empty
because the only listing mail, from `notifications.realtor.ca`, failed the match). Zealty sends
from `noreply@zealty.ca` directly, which matches as-is.

## Extract

Read UNSEEN mail, strip the HTML, and pull `{mls_number, title, price, acres, address, area,
url}`. Dedupe on `dedupe_key`: MLS number when present, otherwise `sha1(address|price)`. The same
property arrives from both sources routinely, and twice from Zealty when the price changes.

Apply the filter from `settings.yaml` under `listings`: areas of interest, `min_acres`, and the
keyword set. Write survivors to the `listings` table.

## Then the part that was never code

Decide whether anything here is worth interrupting the owner for **today**, or belongs in tonight
EOD digest. Default is the digest.

Interrupt for something that clearly matches what the owner has been hunting for: right area,
right acreage, priced to move, or a property they have mentioned before. Getting this threshold
right is a judgement to keep refining. If the owner tells you a call was wrong in either
direction, write it into a skill so it holds. That correction is worth more than the listing was.

## Price changes

A relisting or a price drop on a property already in `listings` is often more interesting than a
new listing, because it means motion on something they may have already looked at. Note it rather
than discarding it as a duplicate.
