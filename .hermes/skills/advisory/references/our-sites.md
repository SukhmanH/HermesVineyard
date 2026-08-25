# Our six properties — what we know about each site

Owner-provided locations + regional terroir data (Oliver Osoyoos Wine Country terroir series,
BCVQA sub-GI documentation, Wine BC). Soil and microclimate notes are REGIONAL CHARACTER —
verify block-level truth by walking the ground, digging a hole, or asking the owner. Update this
file when blocks are registered in `blocks` with real lat/lon.

| # | Name | Address | Site key |
|---|---|---|---|
| 1 | Upper Bench | 70 Upper Bench Rd, Penticton, V2A 8T1 | `penticton` |
| 2 | Naramata | 2017 Naramata Rd, Penticton, V2A 8T9 | `naramata` |
| 3 | Rust | 4444 Goldenmile Dr, Oliver, V0H 1T1 | `oliver` |
| 4 | Tucelnuit | 7199 Tucelnuit Dr, Oliver, V0H 1T2 | `oliver` |
| 5 | Hwy 97 | 4152 BC-97, Oliver, V0H 1T0 | `oliver` |
| 6 | Cassini | 4798 Okanagan Hwy · 49.134041, -119.582336 · V0X 1C0 | `oliver` |

## 1 & 2 — Penticton / Naramata (the northern pair)

**Upper Bench Rd, Penticton.** West side of Okanagan Lake on the bench above town. Penticton
sits in one of Canada's mildest semi-arid pockets (~2000 sun hours); upper-bench land drains cold
air toward the lake, so radiation-frost risk is lower than the valley floor but not zero in
spring. Lake moderation delays budbreak slightly versus south-valley sites — often a feature,
not a bug.

**Naramata Rd (2017).** The road north out of Penticton climbs the east-shore bench — the
address says Penticton, the growing conditions are **Naramata Bench**: west-facing slopes over
the lake, afternoon sun reflected off water, glacial-lake deposits (sands, silts, gravels).
Officially a sub-GI since 2019. Known for Pinot Gris, Chardonnay, Merlot, Pinot Noir,
Gewürztraminer/Riesling — mid-season varieties. Lake effect = fewer extreme-cold nights than
inland benches, but spring frost still happens on the bench shoulder. Weather station caveat:
naramata site reads Summerland's station ACROSS the lake — say so whenever readings look marginal.

## 3 — Rust (Goldenmile Dr), Oliver

On the **Golden Mile Bench**, west side of the valley south of Oliver — BC's FIRST sub-GI
(2014), and the workers' name is literal: Rust Wine Co.'s home vineyard sits here. Character:
**east-facing slopes** (gentle morning sun, sheltered from searing afternoons), elevations
~300–600 m, gravelly glacial deposits over sandy loam and silt draining off Mount Kobau.
Signature plantings: Merlot (the benchmark variety here), Cabernet Franc, Syrah, Pinot Gris,
Chardonnay. The east aspect makes it the slightly cooler, more elegant half of Oliver — which
matters for spray calls: fewer degree-hours of sulfur-burn risk than Black Sage, but still hot.

Regional caution worth remembering: winter cold has bitten this bench before — Rust's own
Zinfandel block was lost after the 2024 January freeze. Winter-hardiness questions are not
theoretical at our southern sites.

## 4 — Tucelnuit Dr, Oliver

North-east of Oliver town toward Gallagher Lake — east-side benchland between Oliver North and
the Black Sage country. Soils trend sandier on this side of the valley (glacial outwash),
free-draining, warm nights. Expect faster vigour burn-through in sandy stretches: irrigation
management matters more here than on the heavier Golden Mile soils. Treat as intermediate heat —
warmer than Golden Mile mornings, less extreme than Black Sage afternoons.

## 5 & 6 — Hwy 97 and Cassini, south of Oliver

**Hwy 97 (4152 BC-97, Oliver, V0H 1T0)** sits along the valley-floor highway corridor just south
of Oliver — valley floor means **cold-air drainage territory**: highest spring-frost risk of all
six properties on clear calm May nights, and the first place to check after any frost warning.
Heat is full-south-Okanagan.

**Cassini (4798 Okanagan Hwy, 49.134041, -119.582336, V0X 1C0)** lies further south on the
western side, on the approach to Osoyoos — the hottest end of our range, effectively continuous
with the Osoyoos/Mount Kobau bench country. Longest season, earliest budbreak, latest harvest,
highest sulfur-temperature vigilance. If Cabernet Sauvignon goes anywhere, it wants to be here.

## Operational consequences (why this file exists)

- **Frost order, spring:** watch #5 (valley floor) first, then #6, benches last. Reverse that
  order for harvest timing — #6 ripens first.
- **Spray temp ceilings:** sulfur ceiling bites at #6 and #5 first, Goldenmile last among
  Oliver sites; check per-site forecast max against `products.max_temp_c`, not one valley number.
- **Weather sources:** penticton has its own station; naramata borrows Summerland (across the
  lake), oliver borrows Osoyoos (18 km, hotter pocket) — name the station in marginal calls.
- **Variety fit (if asked):** mid-season white/red varieties suit #1–#3; Bordeaux reds and
  anything late want #4–#6.
