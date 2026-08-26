# Wunderground PWS — hyper-local current conditions

Verified working 2026-08-25 against all three of our stations. This is the OBSERVATIONS layer:
what the air is doing at (or nearly at) the vines right now — temperature, humidity, dew point,
wind, precipitation. It is **not a forecast**; the spray verdict still comes from the ECCC
citypage hourly forecast.

## Why this exists

ECCC's nearest stations are 2–18 km away and miss bench microclimates. The PWS network has
sensors effectively at our properties, including a station ON a Naramata vineyard. Humidity and
dew point drive the mildew call; a station 18 km away in a hotter pocket does not see our dew.

## Our stations

| Site | Station ID | What it is | Serves |
|---|---|---|---|
| penticton | `IPENTI39` | Penticton | Upper Bench |
| naramata | `IBCNARAM1` | "Boulder Beach Vineyard" — a vineyard station on the bench | Naramata |
| oliver | `IOLIVE36` | Oliver town, 0.7 km off site coords | Rust, Tucelnuit, Hwy 97, Cassini (5–9 km) |

Station IDs live in `config/settings.yaml` under each site's `wunderground_pws`. If a station
goes dead (PWS owners unplug them), find a replacement with the geolookup call below and update
settings — do not silently report stale data.

## Endpoints

    GET https://api.weather.com/v2/pws/observations/current?stationId=<ID>&format=json&units=m&numericPrecision=decimal&apiKey=<KEY>
    GET https://api.weather.com/v2/pws/observations/hourly_7day?stationId=<ID>&format=json&units=m&apiKey=<KEY>
    GET https://api.weather.com/v3/location/near?format=json&geocode=<lat>%2C<lon>&product=pws&apiKey=<KEY>

- `units=m` returns metric (temp/dewpt in °C, windSpeed in km/h, pressure hPa, precip mm).
  **If you ever use `units=e` (imperial) instead, convert: C = (F − 32) × 5⁄9.** The report is
  always in Celsius; never ship an F number through unconverted.
- `current` fields you want: `observations[0].metric.temp`, `.dewpt`, `.humidity`,
  `.windSpeed`, `.windGust`, `.windDir`, `.precipTotal`, plus `observations[0].epoch` (obs time —
  PWS upload gaps are common; report the age).
- `hourly_7day` gives the past week hour-by-hour — useful for "how long was it wet this morning"
  style questions the ECCC forecast cannot answer.
- `near` (geolookup) lists PWS sorted by distance around a coordinate — how IOLIVE36 was found.

## The API key

`weather_sources.wunderground_api_key` in `config/settings.yaml`. It is The Weather Company's
**public web client key** — the same one wunderground.com's own pages use, extractable from
their JS bundle (`/bundle-next/main-*.js`, regex `apiKey`). It is not a secret, but it can be
rotated by TWC without notice: on 401s, re-extract from the bundle and update settings.

## Rate limits and etiquette

This is a free web key shared with every wunderground.com visitor — do not hammer it. One
`current` call per site per report cycle (the 04:30 job, the midday recheck, and on-demand
questions) is plenty; cache what you fetch and say its age. If a call fails, walk on to the next
source rather than retrying in a loop — ECCC currentConditions is the fallback.

Current CONDITIONS are a separate, parallel ladder (see SKILL.md): **Wunderground PWS first**,
**ECCC `currentConditions` second** — the government station is the automatic backup when a PWS
is dead or stale — and worker-reported last (marked as such).

**Dew point on the ECCC fallback:** ECCC gives temperature + relative humidity but no dew point.
Derive it (Magnus, good to ~±0.5 °C here):

    gamma = ln(RH/100) + (17.62 * T) / (243.12 + T)
    dewpt = 243.12 * gamma / (17.62 - gamma)

Label it "estimated" in the report when it comes from this formula rather than a sensor.

## Where it feeds

- **Daily report / briefs**: the current-conditions line per site — "Rust station: 24 °C, RH 38%,
  dew point 8 °C". Dew point near single digits in a warm day = dry air, mildew-unfriendly;
  dew point within a few degrees of the temperature = saturation, mildew-friendly.
- **Weather-at-application** on spray records: a reading from 0.7 km beats one from 18 km in a
  hotter pocket. Prefer the PWS obs nearest the application time.
- **Cross-check**: if the PWS disagrees with ECCC by a lot (wind especially — bench drafts),
  say so and trust the closer sensor for on-the-ground calls, the official station for the
  compliance record.
