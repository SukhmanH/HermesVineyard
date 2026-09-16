# Grower improvements — 2026-09-16

## Accepted code and verification

Final accepted code HEAD: 7508f5b. Full fixture-only suite after removing the rejected correction prototype: 309 passed in 4.87s. Initial baseline: 265 tests. No deployment/restart or production data migration was performed. Existing owner changes in schema.sql, cron setup and report emitter were left uncommitted and intact.

Commits:
- dd05d94: recursive SQLite triggers close the INSERT OR REPLACE append-only hole; spray-window output discloses missing/partial gust coverage. Disclosure is NOT a hard gust safety downgrade.
- 11bafd9: same-day Brix retests no longer silently remove the ripening projection.
- 094084a: products lacking pest registration on file are not offered as usable.
- 49c545b, 2587a79: separate winery contract assessments, public winery filter, deterministic retest ordering, season-scoped samples, sample-date anchored projections, and multi-contract irrigation cross-check. Independent re-review passed, 47 focused tests, no blockers.
- 8652b7a: water balance credits usable logged irrigation volumes; future records excluded, missing acreage/volume disclosed. This remains an estimate, not a soil-water measurement.
- d34f11d: canonical real spray dates and times required.
- 6572b5d: finite nonnegative REI validation and spray commit revalidation. This does not fully validate other numeric fields or protect every mutable-draft scenario.
- 7508f5b: NULL expiry restrictions remain in both existing safety lists as unknown, entry_allowed=false. Direct SQL consumers of the unchanged rei_active schema view still omit NULL expiry; migration follow-up required.
- 6abc145: monthly compliance workbook, including raw superseded records, immediate correction IDs across months, Vancouver month boundaries, audit sheet, metadata and literal text cells. Four fixture tests include a real CLI execution.

Monthly export command from repository root:
    .venv/bin/python tools/build_exports.py --compliance-month 2026-08
It writes to configured EXPORT_DIR without running backup/rotation. No real production export was generated in this work session. Weekly payroll prototype was not shipped: task_workers has only task_log_id/contact_id, not per-worker hours. Crew totals cannot be presented as confirmed individual payroll hours.

## Correction flow: NOT FIXED

The uncommitted correction rewrite passed 315 tests, but independent isolated probes found blockers. It was removed from active source, not committed as working code. Reference-only patch and its six regression tests are archived alongside this file; they are not safe to apply as a completed solution.

Required follow-up design/tests:
1. Preserve historical product PCP/REI/PHI snapshots through every correction follow-up unless product identity or label data is explicitly corrected. An unrelated rate confirmation replaced historical REI 24 with current registry REI 2 in the rejected prototype.
2. Resolve changed product identity and clear previous label data; unresolved-product follow-ups must retain label collection requirements and apply supplied label REI. Do not become ready with an unknown interval.
3. Apply correction-specific immutable-field rules through ordinary draft merge as well as correction creation. Preserve original raw message/source metadata; append correction wording rather than replacing provenance.
4. Share finite positive numeric validation through ordinary intake, correction creation and commit. NaN spray rate can become NULL; missing/NaN task hours can commit NULL. Require task_type/log_date at every gate.
5. Preserve existing rate warnings on unrelated corrections; recompute on changed product/rate. Stored rate_flag and draft _rate_flag currently diverge.
6. Resolve block changes instead of overwriting them with original block identity; preserve worker memberships when superseding task rows.
7. Check supersession inside the commit write transaction; two separately prepared corrections must not both supersede one original.
8. Keep originals immutable and correction targets immutable. The earlier audit claim that changes.corrects_log_id could supersede an unrelated record was NOT reproduced: commit uses the separate draft-row target.

Until these are resolved, correction output should receive explicit manager verification; do not describe the correction pipeline as hardened. Existing defects remain in accepted baseline.

## Other unresolved limits

Missing gusts still permit YES with explicit coverage flags. Deterministic multilingual qualification/conditional approval policy is not implemented. Never interpret missing gust data as calm wind.

Unknown REI rows are surfaced without an invented expiry; operational resolution requires actual label/application evidence. New dates and REI checks do not constitute a comprehensive compliance certification.

Repository-wide lint has the pre-existing I001 in tests/test_intake_identity.py; changed-file lint was clean during implementation. Passing tests are scoped evidence, not proof of legal compliance or production deployment.
