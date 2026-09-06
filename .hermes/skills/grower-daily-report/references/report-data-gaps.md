# Report Data Gaps — concise reference for grower-daily-report

When a data field is missing or `0.0`, the report should state the fact once and move on.

| Field | Empty / Zero Behaviour | Report Line |
|---|---|---|
| **Block acres** | `0.0` or `NULL` | "No acreage recorded yet. All blocks show 0.0 acres." |
| **Block variety** | `NULL` | "variety: TBD" |
| **Active REIs** | None | "No active REIs. All blocks clear for entry." |
| **Silent workers** | 3 workers, 0 reports/30d | "Juan (es): 0 reports in 30d, last report: never" (one line per silent worker) |
| **Recent decisions** | No rows | Omit the section entirely; do not say "no decisions." |
| **New listings** | No rows since last digest | "No new listings since last digest." |
| **Mildew pressure** | Out of season | Omit section; do not invent. |
| **Water balance** | No block data | "Water: no records." |
| **PHI countdowns** | No harvest dates registered | "No harvest dates registered. Say so once and move on." |
| **GDD pace** | No budbreak recorded | "GDD: no recorded budbreak." |
| **Sulfur-burn hours** | No forecast hours above ceiling | Omit; do not say "0 hours." |
| **Rain-washoff check** | No committed sprays or no rain forecast | Omit; do not add a line. |
| **Crew heat-stress** | No site tops 30 °C | "No heat-stress flag — no site above 30 °C." |

## Always say it once, then move on

- **Never repeat** the "no records" line in every section. Say it in the first relevant section and omit from subsequent ones.
- **If the whole day is quiet**: one line. `"Quiet. No records anywhere."` is a complete report.
- **`"not set up"`** — use once to flag a missing setup item (e.g. no harvest dates in `block_season`). After that, the daily report is not the place to re-explain it.

## Data that should NOT appear in the report

- Do not re-explain why data is missing. The setup gaps are flagged elsewhere.
- Do not fabricate or estimate values. `"TBD"` and `"no records"` are the correct placeholders.