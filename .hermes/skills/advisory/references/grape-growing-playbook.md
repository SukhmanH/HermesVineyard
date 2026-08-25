# Grape-growing playbook — Okanagan season management

The how-to layer under `okanagan-viticulture.md` (climate/pests) and `our-sites.md` (our ground).
Sources: BCWGC Best Practices Guide, BC Ministry of Agriculture fact sheets, cool-climate
maturity literature. Numbers here are REGIONAL DEFAULTS — the block record and the winery
contract always override them.

## The season as a checklist

**Dormant (Dec–Mar).** Prune to 2-bud spurs leaving adjustment buds; double-prune in frosty blocks
(mechanical pre-prune then hand-follow) to delay budbreak. Sample and mark crown-gall / trunk
damage after cold snaps. Order nursery stock; vineyard replant decisions feed the Enhanced Replant
Program eligibility window. Sanitize pruning tools between blocks with visible trunk disease.

**Budbreak–5 leaves (~late Apr–mid May).** Cutworm scout at dawn on bare buds — control window is
NOW or never (Altacor/Dipel class). First powdery-mildew protectant at 3–5 unfolded leaves on
susceptible varieties (sulfur unless rain-cold). Fix irrigation leaks BEFORE first water is needed.
Graft-union hills pulled down after frost danger.

**Shoot growth (May–Jun).** Shoot thinning at 20–30 cm: keep 2 shoots per spur, remove non-count
shoots on head/cordon — do it once, early, not repeatedly. Sucker trunks. Mildew cover every
10 days sulfur-based through this stretch.

**Flower–fruit set (~mid Jun).** The mildew-critical period begins: nothing may lapse now.
Basal-leaf removal in June (not August) — opens fruit zone, cuts leafhopper egg-laying AND bunch
rot; skip on sunburn-exposed SW blocks or do shaded-side only. Petiole sample at full flowering +
10 days for nutrition (N, P, K, Mg, Zn, B — lab ranges, not guesswork).

**Pre-bunch closure (~early Jul).** Botrytis decision #2 (bloom was #1): tight-cluster varieties
and damaged-berries blocks get covered. Last pass for cluster-zone leaf work. Topping only if
shoots 15+ nodes past top wire.

**July–August — pressure peak.** BC's mildew model data: shortest safe intervals fall here. Keep
10-day sulfur cadence or rotate FRAC groups per rotation rules in `/advisory`; never let cover
lapse over a heat spike + irrigation event (lush canopy = infection window). Irrigation: regulated
deficit from fruit set — target mild stress, watch midday leaf angle/water status rather than a
fixed schedule. Rust-mite/scorch check on young leaves.

**Veraison (~early–mid Aug).** Sampling starts: weekly 200-berry composite per block (walk a W,
both sides of canopy), crush/measure Brix-pH-TA. Drop green/hlaggard clusters at veraison, not
later. PHI math becomes binding — every product still in program gets checked against expected
picking date. Post-veraison water: deficit continues but never hard-stress a block behind its
Brix target (dilution vs concentration trade-off lives in `/fruit-and-water`).

**Pre-harvest (Sep).** Sampling every 2–3 days as blocks approach target. Botrytis pre-harvest
pass where label PHI allows. Bird netting verified, wasp nests reported not sprayed. Harvest
order across our sites runs south→north (#6 Osoyoos-side first, Penticton last).

**Post-harvest (Oct–Nov).** Refill soil profile before freeze-up (root winter protection).
Late-season N if petioles said deficient. Fall frost windows begin Sep 15 — leaves must stay
healthy until natural drop for carbohydrate reload; protect them like a crop.

## Maturity targets by variety (cool-climate starting points)

| Variety | Brix | pH | TA g/L | Notes |
|---|---|---|---|---|
| Pinot Gris | 21–23 | 3.2–3.4 | 6–8 | Pick on aromatics, not just numbers |
| Riesling | 20–23 | 3.0–3.3 | 7–9 | Acid-driven; style range wide |
| Chardonnay | 21–24 | 3.2–3.5 | 6–8 | Sparkling base picks far earlier |
| Gewürztraminer | 22–24 | 3.3–3.5 | 5.5–7 | |
| Pinot Noir | 22–25 | 3.3–3.6 | 5.5–7 | Phenolics + seed brownness matter |
| Merlot | 23–26 | 3.4–3.7 | 5–6.5 | Golden Mile benchmark variety |
| Cab Franc / Cab Sauv | 23–27 | 3.5–3.8 | 4.5–6 | South sites only; last picked |

Sampling truth: 200-berry composites beat bucket samples; measure same time of day; Brix moves
~+1.5–2/week in September heat, faster in a heat spike. **The winery contract spec in
`fruit_targets` overrides every number above** — that is what the check exists for.

## Nutrition & soil

Petiole sampling: full bloom +10d, 60–100 basal leaves per uniform block, clean paper bags.
Interpret against lab sufficiency ranges; correct documented deficiencies only — blind fertilizer
is money burned and vigour gained where you don't want it. Excess N = shade, mildew, poor colour,
poor hardening-off for winter. Cover crop: grasses to compete/vigour-control on vigorous blocks;
legumes only where N wanted; mow short (<5 cm) through frost season.

## Water arithmetic (ties to `/fruit-and-water`)

ETc = ET0 × Kc (stage table in config). Drip wine grapes in the dry south run roughly 60–70% of
ET0 replacement post-set; deficit fraction and alert threshold live in `settings.yaml`. Sandy
sites (#4 Tucelnuit country) need lighter/more-frequent sets than loamy Goldenmile ground.
Post-veraison watering fights sugar — coordinate, don't freelance.

## What NOT to do (learned-the-hard-way list)

- No sprays into a NO verdict, no softened verdicts — kernel owns that call.
- No product proposed outside `spray_options` output; no rate off-label.
- No repeated FRAC group three times running without saying so loudly.
- No harvest-call advice without checking `fruit_targets` PHI/spec conflicts first.
- No "it'll be fine" on winter protection at the southern sites — they freeze, ask 2024.
