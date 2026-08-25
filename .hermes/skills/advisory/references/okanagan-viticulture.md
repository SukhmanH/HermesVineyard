# Okanagan viticulture — the region this operation actually grows in

Regional grounding for recommendations and briefs. Everything here is Okanagan/Similkameen- or
BC-specific from the BC Wine Grape Council Best Practices Guide (bpg.bcwgc.org), BC Ministry of
Ag fact sheets, and the BC Tree Fruit Production Guide. It is context, not a licence: **product
rates, REIs and PHIs still come only from `products` rows verified against the physical label**,
and observations of actual vines beat anything written here.

## Climate — what kind of place this is

- Cold northern desert. Annual precipitation ~250–300 mm; **irrigation is not optional**, every
  block is dryland-farmed in name only. Semi-arid air means disease pressure is low by world
  standards — powdery mildew is THE disease, botrytis matters in tight-cluster varieties and wet
  Septembers; downy mildew and black rot are rare in the dry south.
- Growing degree days (base 10 °C) roughly 1100–1400 over the valley's span: Penticton bench
  sites moderate (~1200), Oliver–Osoyoos the hottest pocket in Canada (~1300–1400). That gradient
  decides variety ripening order — use `compute_gdd` per site rather than these ballparks when
  the season is running.
- Large lakes moderate the benches (Naramata sits across from Penticton on Okanagan Lake): lake-
  adjacent slopes get fewer radiation frosts and later spring budbreak than valley floor. The
  valley floor and low pockets collect katabatic cold air — those are the frost pockets.
- Winter is the existential risk, not summer heat. Vinifera midwinter hardiness is roughly
  −15 to −25 °C depending on variety and acclimation; the November 2022 freeze hit before vines
  had acclimated and damaged vineyards valley-wide, with crown gall showing at injury sites for
  years after. After any hard-freeze event: expect trunk/cordon damage assessment to be the next
  season's first job, and do not push crop on recovering vines.

## Typical phenology (Okanagan, adjust with `compute_gdd` and observed stage)

| Stage | Rough window | What it drives |
|---|---|---|
| Dormant pruning | Dec–Mar | Delay pruning in frost-prone blocks (late pruning delays budbreak ~1–2 weeks); fresh cuts + rain = Eutypa risk |
| Budbreak | Late Apr–mid May | Cutworm scouting starts NOW; first mildew protectant once shoots have 3–5 leaves |
| Bloom | Mid Jun (±10 d) | Critical mildew window begins; botrytis spray #1 at bloom in susceptible varieties |
| Fruit set | Late Jun | Pre-bunch-closure botrytis decisions; basal leaf removal June (not Aug) cuts leafhoppers AND bunch rot |
| Veraison | Early–mid Aug | PHI math starts binding against expected harvest; post-veraison deficit irrigation |
| Harvest | Sep–late Oct | Wasps; PHI checks on everything still in program |

## The pest calendar (few pests, well understood)

- **Powdery mildew** — the disease. BC's model data says pressure peaks July–August when
  Okanagan summer temperatures are near-optimal for the pathogen. Sulfur is the backbone
  (10-day intervals); rotate FRAC groups; max 2 consecutive same-group sprays. Sulfur burns fruit
  above ~27 °C under slow drying — Oliver/Osoyoos afternoons will do that.
- **Botrytis** — bloom / bunch closure / pre-harvest are the three timings that matter.
- **Climbing cutworms** — eat buds at night from budbreak; scout bare buds at dawn. Broadleaf
  weeds in the vine row reduce damage (alternate food).
- **Leafhoppers** — two generations: nymphs mid-Jun–mid-Jul, peak 2 again after the first week of
  August. Western grape leafhopper is resistant to malathion; Assail is the standard.
  Yellow sticky tape below the cordon in spring can replace sprays in edge-row situations.
- **Mealybug & soft scale** — matter because they vector grapevine viruses; time sprays to
  crawler emergence (double-sided tape on cordon tells you when).
- **Erineum mite / rust mite** — early-season leaf symptoms; usually cosmetic, Agri-Mek if
  rust mite builds. Spider mites flare after broad-spectrum sprays kill predators.
- **Wasps at harvest** — worker safety issue as much as crop one; report nests, don't spray them.
- **Phylloxera** — present but scattered in the southern interior; rootstock choice, not spraying.

## Frost — the standing brief already watches it; know what it means

- Radiation frosts dominate here: clear calm nights, cold air draining to low ground. Wind
  machines work off the inversion; nothing works in an advective freeze.
- Emerged shoots damage around −1 to −2 °C; primary buds are hardiest pre-break. Grapevines
  compensate: secondary buds break after primary loss but yield only ~25–50% and mature late —
  so a spring frost is a *crop-load and ripeness* problem more than a replant problem.
- Cultural levers: prune late in frosty blocks, keep cover crop short (<5 cm) through frost
  season so it doesn't dam cold air, hilling graft unions on young blocks before winter,
  multiple trunks on cold sites.
- Post-harvest: refill soil profile to field capacity before freeze-up — root winter protection.

## Water — deficit is a tool, timing is everything

Regulated deficit irrigation is standard practice: mild stress between fruit set and veraison
controls vigour and berry size; post-veraison deficit concentrates flavour but dilution fights
Brix targets — coordinate with `/fruit-and-water` rather than advising water independently.
Vines under real drought stress cannot afford insect feeding damage and harden off worse for
winter; "no water" is never the safe recommendation.

## Varieties commonly grown in this valley

Merlot, Pinot Noir, Pinot Gris (most planted in BC), Chardonnay, Riesling, Gewürztraminer,
Cabernet Franc, Cabernet Sauvignon (south valley only — needs the Oliver/Osoyoos heat),
Syrah. Concord/Foch hybrids exist on old plantings — several products are NOT label-labelled
for them (Pristine injures some hybrids; sulfur burns Concord).

## How to use this file

It makes your questions sharper and your options plausible; it does not make you the agronomist.
"We're entering the July pressure peak and B3's last cover was sulfur 12 days ago" is you doing
your job. "There will be mildew" is not.
