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

## Isolated follow-up implementation (not deployed)

Worktree: `/tmp/hermes-vineyard-followups-20260916`, branch `followups-20260916-isolated`, based on f64aba5. Owner worktree and external skills were not modified.

Implemented in this increment:
- Correction-specific merge rules preserve raw/source provenance, reporter identity and the separate supersession target through follow-ups. Explicit block/product changes resolve again; changed products clear old label snapshots. Unrelated edits retain historical PCP/REI/PHI and rate warnings, including after registry changes. Unknown products remain collecting until label REI is supplied.
- Shared finite/positive checks for application amounts, task hours and quantities, finite weather/PHI checks, required task fields and calendar dates at draft/correction/commit gates. Task membership validation and membership preservation on corrections.
- Commit re-reads the token and checks supersession under BEGIN IMMEDIATE before insertion. A synchronized two-connection regression verifies exactly one correction commits. Original append-only records remain untouched; follow-ups require presentation again.
- Missing/invalid gust hours now fail safe and cannot belong to an approved window. Partial forecasts may approve only a covered run. Cached verdicts retain the refusal and template key. en/es/pa templates include the warning, with no English fallback. Punjabi warning requires human language review before deployment.
- Removed the pre-existing I001 blank-line issue.

Verification: clean f64aba5 archive baseline executed separately: 309 passed in 4.47s. New regression tests were observed failing before their corresponding fixes. Final verification: `/home/waris/hermes-vineyard/.venv/bin/python -m pytest -q`: 362 passed in 4.76s; `/home/waris/hermes-vineyard/.venv/bin/ruff check .`: All checks passed; `git diff --check`: clean.

Not completed in this increment:
- Explicit per-worker confirmed hours capture and read-only payroll export remain unimplemented. `hours_total` remains crew-hours, never confirmed individual payroll hours. No schema or export changes were made; the external exports skill's claim of existing per-worker hours remains incorrect.
- REI view/schema migration and its test are owned by the parent agent separately; not included or verified here. No live migration, services, messaging, production database access, push or deployment.
- Independent review is still required, especially for historical records with unknown label intervals. Direct arbitrary SQL edits are not made trustworthy by input validation. Existing API confirmation semantics are preserved; tests are not a legal compliance certification.

Curator recommendations (external skills intentionally read-only): replace wind-only gust approval advice with the strict covered-hour policy and render `spray_missing_gusts` in the recipient's language; correct exports/task-log guidance to distinguish crew-hours from explicitly confirmed individual hours; retain snapshot/provenance and fresh presentation instructions in correction guidance.

## Historical correction flow: NOT FIXED in accepted baseline

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
