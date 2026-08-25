# Environment Canada citypage XML — how to actually fetch it

Verified working 2026-08-21. **The URL scheme changed from what older documentation describes**;
the stable `.../citypage_weather/xml/BC/s0000772_e.xml` form now 404s.

## Current scheme

    https://dd.weather.gc.ca/today/citypage_weather/BC/<HH>/<TIMESTAMP>_MSC_CitypageWeather_<SITE>_en.xml

- `<HH>` is the **UTC hour** directory, `00`–`23`.
- Filenames are timestamped, so you must list the directory and take the newest match for your
  site rather than constructing the filename.
- Site list (if codes ever need re-resolving):
  `https://dd.weather.gc.ca/today/citypage_weather/docs/site_list_en.csv`

To fetch: list `.../BC/<HH>/`, regex for `([^"]*<SITE>_en\.xml)`, take `sorted(...)[-1]`. If that
hour's directory is empty or missing, walk back an hour or two — a publish gap of one hour is
normal and is not an outage.

## Our stations

| Site | Code | Station | Distance |
|---|---|---|---|
| penticton | `s0000772` | Penticton | 2 km |
| naramata | `s0000351` | Summerland | 6 km, **across the lake** |
| oliver | `s0000397` | Osoyoos | 18 km, **hotter pocket** |

Naramata and Oliver have no station of their own. Say which station a reading came from when
conditions are marginal — "Osoyoos, 18 km south" is honest; presenting it as Oliver's weather is
not, and the difference decides a drift call.

## Field mapping

`hourlyForecastGroup/hourlyForecast` — **24 hours**, all carrying wind:

| XML | Normalize to | Notes |
|---|---|---|
| `@dateTimeUTC` (`202608212200`) | `time` | UTC; convert for display |
| `temperature` | `temp_c` | `units="C"` |
| `wind/speed` | `wind_kmh` | `units="km/h"`. Present on all 24 hours |
| `wind/direction` | `wind_dir` | `S`, `NW`, … |
| `wind/gust` | `gust_kmh` | **Frequently empty.** Leave it `None` — never coerce to 0 |
| `lop` | `precip_prob_pct` | "likelihood of precipitation", `units="%"` |
| `condition` | `sky` | e.g. `Smoke`, `Sunny` |

`currentConditions` carries `temperature`, `relativeHumidity`, `wind/{speed,gust,direction}` —
use it for weather-at-application when a worker reports a spray happening now.

**Hourly has no humidity.** `rh_pct` comes from `currentConditions` or stays absent.

## Warnings

`warnings/event` carries `@description` (e.g. `ORANGE WARNING - AIR QUALITY`),
`@alertColourLevel`, and `@expiryTime`. Frost advisories appear here too.

An air-quality or smoke warning is worth passing to the crew even though no spray rule depends on
it — people working outside all day should hear it.

## Feeding compute_spray_window

Normalize to `{time, temp_c, wind_kmh, gust_kmh, precip_prob_pct}` and pass `source="eccc"` plus
`age_hours` measured from the file's timestamp, **not** from when you fetched it. A file published
three hours ago is three hours old however recently you downloaded it — and `age_hours` is what
drives the fail-safe.
