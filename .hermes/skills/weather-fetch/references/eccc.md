# Environment Canada citypage XML — how to actually fetch it

Verified working 2026-08-21, re-verified live fetch 2026-08-29. **The URL scheme changed from what older documentation describes**;
the stable `.../citypage_weather/xml/BC/s0000772_e.xml` form now 404s.

## Current scheme

    https://dd.weather.gc.ca/today/citypage_weather/BC/<HH>/<TIMESTAMP>_MSC_CitypageWeather_<SITE>_en.xml

- `<HH>` is the **UTC hour** directory, `00`–`23`.
- Filenames are timestamped: `20260829T050621.692Z_MSC_CitypageWeather_s0000772_en.xml`
- Site list (if codes ever need re-resolving):
  `https://dd.weather.gc.ca/today/citypage_weather/docs/site_list_en.csv`

## Fetching — the working recipe (live 2026-08-29)

Directory listing returns HTML `<a>` tags. The filename format includes a millisecond-precise
timestamp prefix, so use a regex like:

```python
pattern = re.compile(
    r'(\d{8}T\d{6}\.\d+Z)_MSC_CitypageWeather_' + re.escape(site_code) + r'_en\.xml'
)
matches = pattern.findall(resp.text)
latest = sorted(matches)[-1]  # string sort works on ISO timestamps
```

Then build the full URL: `{dir_url}{latest}_MSC_CitypageWeather_{site_code}_en.xml`.

**Walk back 2–3 UTC hours.** On 2026-08-29, fetching at 05:39 UTC, the 05:00 and 04:00 hour
directories were populated but the 03:00 hour directory was empty — normal publish timing, not an
outage. A one-hour gap is routine; two is acceptable; three means degrade.

**HTTPS required** — HTTP returns a 301 redirect to HTTPS. Use `https://` throughout.

## Our stations

| Site | Code | Station | Distance |
|---|---|---|---|
| penticton | `s0000772` | Penticton | 2 km |
| naramata | `s0000351` | Summerland | 6 km, **across the lake** |
| oliver | `s0000397` | Osoyoos | 18 km, **hotter pocket** |

Naramata and Oliver have no station of their own. Say which station a reading came from when
conditions are marginal — "Osoyoos, 18 km south" is honest; presenting it as Oliver's weather is
not, and the difference decides a drift call.

## Field mapping — XML element names (not attributes)

`hourlyForecastGroup/hourlyForecast` — **24 hours**, all carrying wind. Note: the hourly
forecast elements use **child XML elements with text content**, not attributes:

| XML element | Normalize to | Notes |
|---|---|---|
| `dateTimeUTC` (text: `202608212200`) | `time` | UTC, YYYYMMDDHHMM. Convert to `+00:00` offset for compute_spray_window |
| `temperature` (text) | `temp_c` | `units="C"` |
| `wind/speed` (text) | `wind_kmh` | `units="km/h"`. Present on all 24 hours |
| `wind/direction` (text) | `wind_dir` | `S`, `NW`, … |
| `wind/gust` (text) | `gust_kmh` | **Frequently empty/None.** Leave it `None` — never coerce to 0 |
| `lop` (text) | `precip_prob_pct` | "likelihood of precipitation", `units="%"` |
| `condition` (text) | `sky` | e.g. `Chance of showers`, `Smoke`, `Sunny` |

`currentConditions` carries `temperature`, `relativeHumidity`, `wind/{speed,gust,direction}` —
use it for weather-at-application when a worker reports a spray happening now.

**Hourly has no humidity.** `rh_pct` comes from `currentConditions` or stays absent.

## Warnings

`warnings/event` carries `@description` (e.g. `YELLOW WARNING - AIR QUALITY`),
`@alertColourLevel`, and `@expiryTime`. Frost advisories appear here too.

An air-quality or smoke warning is worth passing to the crew even though no spray rule depends on
it — people working outside all day should hear it.

## Feeding compute_spray_window

Normalize to `{time, temp_c, wind_kmh, gust_kmh, precip_prob_pct}` and pass `source="eccc"` plus
`age_hours` measured from the file's publish timestamp (`xmlCreation` `dateTime` element, UTC zone),
**not** from when you fetched it. A file published three hours ago is three hours old however
recently you downloaded it — and `age_hours` is what drives the fail-safe.