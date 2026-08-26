---
name: weather-fetch
description: Fetch the forecast for all three vineyard sites yourself with execute_code, walk the degrade ladder when a source is down, compute the spray-window verdict through the kernel, and cache both. Runs at 05:45 and again at midday. You do the fetching; the verdict is not yours to soften.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, weather, execute-code, spray-window]
    category: vineyard-ops
    requires_toolsets: [code_execution, mcp-vineyard]
---

# Weather

You fetch this yourself. There is no `weather.py`, and that is deliberate: a tool that "fetches
the weather" would be a capability you already have, narrowed to the one call someone thought of.

## Sites

Three, with their ECCC citypage codes in `config/settings.yaml` under `sites`. **The fetch
mechanics, URL scheme and full field mapping are in `references/eccc.md` — read it before
writing any fetch code.** The URL format changed in 2026 and the older documented form 404s.

| Site | Station | Distance |
|---|---|---|
| penticton | Penticton `s0000772` | 2 km |
| naramata | Summerland `s0000351` | 6 km, **across the lake** |
| oliver | Osoyoos `s0000397` | 18 km, **hotter pocket** |

**Only Penticton has a station of its own.** When conditions are marginal, name the station you
actually read — "Osoyoos, 18 km south" is honest; presenting it as Oliver's weather is not, and
that difference decides a drift call.

## Local sensors — Wunderground PWS (current conditions, not forecast)

Each site also has a hyper-local personal weather station (`wunderground_pws` in settings):
Penticton `IPENTI39`, Naramata `IBCNARAM1` (a vineyard station on the bench), Oliver `IOLIVE36`.
**Mechanics, endpoints and etiquette in `references/wunderground.md`** — but the shape is:
PWS = observations (temp, humidity, dew point, wind) at or near the vines; ECCC = forecast.
Spray verdicts come from forecast hours; the PWS gives the current-conditions line in reports
("Rust station: 24 °C, RH 38%, dew point 8 °C") and the honest weather-at-application reading.
Always Celsius — convert if a source ever returns Fahrenheit.

## The degrade ladder, in order, never silently skipped

1. **ECCC citypage XML** per site — the FORECAST source. Free for commercial use, authoritative
   for Canada, carries official frost advisories. About 24 h of hourly data, which covers the
   only questions asked: can we spray today, and is it freezing tonight?
2. **Open-Meteo**, only if `OPEN_METEO_API_KEY` is set. The free tier is non-commercial and this
   is a commercial operation, so without the key this rung does not exist. Do not use it anyway.
3. **Last cached forecast under 24 h old**, marked STALE / DATOS DE AYER.
4. **Nothing usable.** Send the apology from the template plus an owner alert. Never stay silent.

Current CONDITIONS are a separate, parallel ladder: **Wunderground PWS first** (hyper-local,
carries humidity + dew point), **ECCC `currentConditions` second — the government site is the
automatic backup** when a PWS is dead or stale (derive dew point from its temp + RH — formula in
`references/wunderground.md`, label it "estimated"), worker-reported last (marked as such).
A PWS outage never downgrades a spray verdict — verdicts ride on the forecast ladder only.

Fetch with `execute_code` and `httpx`. Parse defensively: ECCC XML is clunky and occasionally
malformed. If a site fails but others succeed, report per-site rather than failing the whole run.

**⚠ ECCC publishes hours in UTC.** Keep the offset on every timestamp you pass
(`2026-08-21T22:00+00:00`, not `2026-08-21T22:00`) — the verdict converts offset-aware times to
Okanagan local before it filters by hour of day, so tagged UTC is handled correctly and naked
local-looking strings are not. The tool has no `tz` argument to override; it is always
`America/Vancouver`.

Getting this wrong does not error — it silently reports the calm overnight hours as a morning
spray window. It happened on the first live fetch, and it produced a confident YES on a day with
25 km/h daytime wind. Set `age_hours` from the **file's publish timestamp**, not from when you
downloaded it.

## Then compute the verdict, do not judge it

Normalize the hours to the shape `compute_spray_window` expects and call it **per site**. It is a
pure function over already-fetched hours, which is what lets you feed it data from any rung.

It returns NO whenever data is stale or wind is missing. **You may not soften a NO into a YES**,
reword it into a maybe, or add encouraging context that implies otherwise. Fail-safe is a
property of that function precisely because it must hold on a day when your own reasoning is
degraded.

You must always name the **source** and any caveat: "ECCC, updated 05:40" or "yesterday's data,
treat with caution."

## Cache — handled for you, but check it happened

`compute_spray_window` writes the forecast and the verdict to `weather_cache` itself, per site.
**Do not call `cache_weather` after it** — that would store the same run twice.

This used to be your job and it was the step that went missing (2026-08-23: a correct verdict
delivered with no row behind it). Recording it in the tool is what makes the audit trail
independent of anyone remembering.

What you still owe: **read `recorded` in the result.** On `false`, the verdict is safe to act on
now but nothing was written — say so plainly and alert the owner, because the spray-log flow
reads this table hours later to auto-fill weather-at-application, and a gap there degrades a
compliance record quietly.

## Frost

During the frost windows (Mar 1 to May 31, Sep 15 to Nov 15), any site with an overnight minimum
at or below 2 C is an immediate alert to the crew group and managers, in both languages, at the
20:00 trigger and sooner if you see it sooner. Frost is not an EOD-digest item.
