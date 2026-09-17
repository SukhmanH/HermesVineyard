# Research-backed grower features

## Selection

NC State Extension describes crop estimation from actual bearing vines, representative clusters per vine, and expected harvest cluster weights. It warns that missing vines, weight variation, and subsequent fruit loss affect predictions.[1]

Health Canada distinguishes the Pre-Harvest Interval from the Restricted Entry Interval; labels govern both, and rain does not shorten the Pre-Harvest Interval.[2]

WorkSafeBC says temperature alone cannot predict heat-stress risk. Monitoring should begin as temperatures approach 23–25°C, but those are not exposure limits.[3] Therefore this batch does not invent a temperature-only work/rest prescription. Disease infection prediction is also outside this batch.

## Offline crop and bin planner

From the repository root:

    .venv/bin/python -m tools.plan_harvest docs/examples/harvest-scenario.json

The supplied example is synthetic, not a vineyard record. Copy it outside the repository and replace every input before using it for planning. Output is JSON on stdout; no database access, network calls, records or messages are created.

Inputs:
- block_name: grower's property name, carried verbatim rather than resolved to a database block.
- sampled_on: explicit YYYY-MM-DD, carried through for the manager to assess freshness; no automatic freshness assurance.
- bearing_vines: actual positive integer bearing-vine count, not planted spaces.
- clusters_per_sampled_vine: nonnegative integer counts from distinct representative bearing vines. Include zero-cluster sampled vines. Sample cannot exceed bearing-vine count.
- harvest_cluster_weight_g: positive low/expected/high harvest-weight scenarios in grams, in order.
- weight_basis: explanation of where those expected harvest weights came from.
- bin_payload_kg: positive usable fruit payload per bin, excluding bin tare.

Formula: bearing vines × sample mean clusters/vine × harvest cluster grams / 1000 = kilograms. Metric tonnes = kilograms / 1000. Bins are rounded up independently for each scenario.

The low/high results are user-supplied scenarios, not confidence intervals. The tool does not extrapolate immature cluster weights, invent missing acreage, calculate wages, prescribe thinning, or provide harvest clearance. Reassess inputs after thinning, weather damage or fruit loss. It cannot verify representative sampling or detect a false weight basis.

Validation rejects missing fields, invalid dates, booleans as numbers, negative/nonfinite values, fractional cluster/vine counts, empty samples and reversed weight scenarios. A measured zero cluster count produces a zero crop rather than a missing-data error.

## Pre-harvest restriction check

Separate implementation under review; not yet integrated at the time of this document's first commit. No automatic daily-report wiring, production migration, service restart or push is included in this batch.

## Operational integration boundary

Existing grower-daily-report and other vineyard skills reside in the external skill directory and were not edited. Adopt the relevant skill through `hermes curator adopt <name>` before changing its procedure. The crop planner is an offline CLI, not a new MCP tool: it does not need privileged kernel access. Existing production report/cron edits remain untouched.

## Verification

See commit and final main-tree test results reported with the implementation. CLI tests execute real subprocesses with synthetic inputs, read JSON output, and check the input is unchanged.

## Sources

[1] https://content.ces.ncsu.edu/north-carolina-winegrape-growers-guide/chapter-12-crop-prediction
    > "Crop estimation is based on several pieces of critical information: (1) a good historical record of average cluster weights at harvest; (2) an accurate count of current bearing vines per acre or block; and (3) an accurate determination of the average number of clusters per vine at the time of the crop estimate."
[2] https://www.canada.ca/en/health-canada/services/consumer-product-safety/reports-publications/pesticides-pest-management/fact-sheets-other-resources/preharvest-intervals.html
    > "Be sure to read and follow the pesticide label in order to always respect both the REI and PHI."
[3] https://www.worksafebc.com/en/health-safety/hazards-exposures/heat-stress
    > "Temperature alone cannot be used to predict the risk of heat stress."
