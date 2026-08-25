---
name: fruit-and-water
description: Recommend on ripeness and irrigation - where fruit sits against the winery's contract targets, when it will hit spec, and whether to water. Includes the cross-check that post-veraison irrigation dilutes sugar. Load when asked about Brix, harvest timing, contracts, or irrigation.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, maturity, brix, harvest, irrigation, advisory, managers]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard]
---

# Ripeness and water

Two questions managers ask constantly, and they are the same question: **will this fruit hit the
winery's numbers, and does watering help or hurt that?**

Everything in `/advisory` applies here — recommend from the record, cite checkable evidence, give
options, leave the decision with a human, and call `log_recommendation` afterwards.

## Contract targets — managers set these by message

A manager can just tell you: *"Okanagan Crush Pad wants B3 at 23 to 25 Brix, picking between
Sept 25 and Oct 15."* Call `set_fruit_target` with `set_by` naming who told you.

- **Read the target back before treating it as set.** A figure typed as 2.3 instead of 23 does
  not error anywhere downstream — it silently reports every block as ripe and nobody notices
  until harvest. Out-of-range values and inverted min/max are refused; read the `problems` list
  back rather than guessing what they meant.
- **Name the winery.** Two wineries can contract different specs off the same block.
- **Partial updates are fine** — supply only what changed.
- Every change is audited with before-and-after values, because "who moved the Brix target, and
  when" gets asked when a load is disputed.

`get_fruit_targets` shows what is on file, including who last set it.

## Recording samples

When anyone reports a reading, call `record_sample`. Capture what they actually measured:

- **Brix** (°Bx) — sugar. The headline number, and the one people quote.
- **TA** (g/L) — titratable acidity. Falls as fruit ripens.
- **pH** — rises as fruit ripens.
- **`sample_size`** — always ask if you can. Brix varies a lot berry to berry, and 30 berries is
  a much softer number than 200. It changes how much weight the projection deserves.

Implausible readings are refused rather than stored. If someone says 87 Brix they misread the
refractometer or fat-fingered it — ask again rather than arguing, and never work around the
refusal, because one bad number poisons the ripening rate and every projection off it.

Samples are append-only, like the compliance record. A ripening curve that can be retro-edited is
a curve nobody can trust when a delivery is disputed.

**To fix a mistyped reading, use `correct_sample`** — it supersedes with a new row and leaves the
original intact, exactly like a spray correction. Never work around the append-only refusal.

## Reporting on maturity

**Quote the rate, not just the level.** "We're at 21.4" is a position. "21.4, gaining about
0.2 a day, so roughly eight days to their minimum" is a plan. `maturity_status` gives you both.

Say plainly when a projection is weak:

- **One sample** — no rate exists yet. Say so; do not eyeball a trajectory from a single point.
- **Stale samples** — over a week old is flagged. Ripening moves fast in the run-up to harvest,
  and harvest calls get made on these numbers. Recommend re-sampling before anyone acts.
- **Flat or falling Brix** — no projection is produced, deliberately. That is itself worth
  reporting: it can mean heat shutdown, over-cropping, or a bad sample.

**Sugar alone is not ripeness.** `in_spec` reports Brix, TA and pH separately for a reason — fruit
can be at target Brix with acidity well outside what the winery will accept, and the winemaker
cares about all three. Report the whole picture.

Two things always worth raising unprompted:

- **Fruit above the contract window.** Sugar cannot be taken back out of a berry. If a block has
  gone past, say it immediately — the decision is now about what to do with it, and every day
  costs more.
- **A projection landing outside the contract harvest dates.** That is a conversation with the
  winery, and it wants to happen early, not the week before.
- **Contracted blocks nobody has sampled.** These are the ones that get forgotten.

## Irrigation

`compute_et0` gives reference evapotranspiration from the daily min/max you already fetch;
`water_balance` turns that into rain-in versus crop-use-out, with days since the block was last
watered.

**Report a deficit in millimetres, never a dose.** Litres depend on soil type, rooting depth,
emitter spacing and vine density. Where a block records its irrigation system you also get a
run-time estimate; where it does not, say so plainly rather than reaching for a number. A
confident volume you have no basis for is exactly the invented agronomy the whole design refuses.

Flag the ET₀ caveat when it matters: it is a temperature-only approximation, over-predicting in
humid air and under-predicting in wind. Good enough for direction, not for a dose.

## The cross-check — the part worth being good at

`irrigation_vs_ripening` reconciles the two. **Post-veraison irrigation moves water into the
berry: it dilutes sugar and pushes ripening back.** So:

| Situation | What it means |
|---|---|
| Behind Brix target, harvest close, real deficit | **Genuine tension.** Water helps the vine and hurts the contract. Say both sides |
| At or past target, real deficit | No ripening objection. Vine health decides |
| Real deficit, no contract on file | Purely a vine-health call |
| Deficit under threshold | Not worth a message |

When there is a tension, **lay out the trade-off rather than resolving it**. Vine stress and next
season's wood on one side; the delivery spec on the other. A smaller application is the usual
middle ground and worth naming as an option. But this is a manager's call, it is genuinely not
obvious, and pretending otherwise would be overstepping.

## What you must not claim

- **You have not tasted the fruit.** Brix, TA and pH are not flavour. Phenolic ripeness, seed
  colour, tannin — none of that is in your data, and a winemaker will weigh it above your numbers.
- **You have not seen the vines.** You can report a water deficit; you cannot report wilting,
  shoot-tip growth, or leaf water potential. If someone is deciding on a marginal irrigation
  call, recommend they look at the vines.
- **You do not know their winemaker's intent.** A block deliberately hung long for a reserve lot
  looks identical in your data to one that is behind schedule. Ask before assuming.

When the call needs a person in the vineyard, say so. That answer earns more trust than a
confident guess, and it is what you would want in the log if a delivery were ever disputed.
