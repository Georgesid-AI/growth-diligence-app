# Spec: Interface contracts on two handoffs
Status: Draft; the agreed scope is the task of 2026-10-08. Location: docs/specs/interface-contracts.md.
No architecture change: the engine stays pure, the gateway stays the only caller of a model, the export stays in the API.
Amended 2026-10-15 (docs/specs/dates-and-periods.md §7): `contract_version` 3 adds `source_period` and `metric_periods` (months as
text, no figure, server-only); results stored under version 2 are recomputed on first read.
Amended 2026-10-17 (docs/specs/crm-dedup-clustering.md §3): `contract_version` 4 adds `anomalies.deals_duplicate_id` and
`won_deal_closes` (won deals per close month, counts only, server-only); results stored under version 3 are recomputed on first read.
Amended 2026-10-22 (docs/specs/chat-upload.md §28): `contract_version` 6 marks the page reader (deck claims carry `basis`, `scenario`
and `flags`; amended 2026-10-23: `schemas.metrics.DECK_CLAIM_FIELDS` names the three, the register row (`claim_matching.FIELDS`), the baseline CSV and
the memo's Appendix A carry `basis` and `scenario`, the deck list all three; contract test in `test_interface_contracts.py`, `test_pr164_review.py`); results and claim matches stored under version 5 read "Stale – re-run audit" until Run audit calculates again
(no recompute on a read, as amended 2026-10-20). `SEED_VERSION` 13 reseeds demo audits held under contract 5.

## Goal
One written definition of what the calc engine hands over, checked at the two places where a wrong unit turns into a
wrong figure the analyst or the model reads:

| Handoff | From | To | Check |
|---|---|---|---|
| H1 | engine output stored in MongoDB (`audits.results`) | LLM gateway | validate against `MetricsPayload` before any prompt is built (§4) |
| H2 | engine output stored in MongoDB | memo / xlsx export | validate, then a unit check, before any cell is written (§5) |

Strict types: a number is a number, never text that reads as one ("5", "0.4"); a count is an
integer.

Out of scope: every other reader of the stored results (dashboard, claim register, banner, usage) keeps its own
logic. They change only where the unit change of §2 forces it (§7); none gets a new validation.

## 1. The model
`backend/schemas/metrics.py` holds one Pydantic model, `MetricsPayload`, and the unit types its fields are declared
with. It is the only description of the engine output.

- `compute_all` builds its return value from the model: the blocks the metric functions produce are validated into
  `MetricsPayload` and its dump is what is stored. A field the engine emits that the model does not declare fails the
  run (`extra="forbid"` on every fixed-key model); a field the model declares and the engine omits is Optional or
  required exactly as the model says. There is no second list of fields: the data-boundary test, the formatter's
  kind table and the export read their kinds from the model (§6).
- Top level: `contract_version` (2), `reporting_currency` (the currency code; it is never repeated inside a value),
  `as_of_month`, then one field per block: `arr`, `nrr`, `gross_churn`, `new_mrr_by_quarter`, `cac_payback`,
  `sales_cycle`, `win_rate`, `founder_win_rate`, `acv_path`, `segment_paths`, `anomalies`, `mrr_series`,
  `revenue_series`, `revenue_reconciliation`, `customers_series`, `cohort_retention`, `missing_data`,
  `questions_for_management`.
- A block that the engine could not compute is `null`; the reason is in `missing_data`, not in the block.
- Every figure's type and unit are in the model: a field is declared `Fraction`, `Count`, `CountUp`, `Days`,
  `Currency`, `Months`, `Ratio`, `Plain` or text. The currency of every `Currency` is `reporting_currency`.
- Citation: every block that carries a number the analyst can query has `source` (file, sheet, rows, row numbers, rule),
  and the model requires it: `arr`, `nrr`, `gross_churn`, `cac_payback`, `sales_cycle`, `win_rate`, `founder_win_rate`,
  `acv_path`, `segment_paths`, `anomalies`, `mrr_series`, `revenue_series`, `customers_series`, `cohort_retention`, and
  both sides of `revenue_reconciliation`. `new_mrr_by_quarter` is a dict keyed by quarter, so its citation is the
  top-level `new_mrr_by_quarter_source`. `anomalies` also has `deals_source` (the CRM file, for deals closing before
  they were created), absent when no CRM was uploaded. The citation is built by the engine from the audit's source list
  (file and sheet per upload) and the rows that fed the block, in the format of the other blocks (file, sheet,
  "rows 4–30 (27 rows)", rule). A block added later is decided in `test_interface_contracts.py`: cited, or listed as
  not needing one with the reason.
- Version: adding the five citations makes `contract_version` 2. Results stored under version 1 are recomputed on first
  read (§7), because they would otherwise fail the gateway and the export.
- Screen: each citation shows like the other blocks' (hover on the block title: file, sheet, rows, rule): MRR by
  segment, cohort retention, anomaly flags (dashboard and diagnostics), the segment paths panel, and the "New MRR"
  column header of the CAC table.
- Gateway: `segment_paths.source` and `cohort_retention.source` go out as the rule only (file, sheet and rows are
  dropped as for every block); `new_mrr_by_quarter_source`, `mrr_series` and `anomalies` stay server-side
  (test_gateway_data_boundary.py extended).

## 2. Units
| Unit | Type | Rule | Example |
|---|---|---|---|
| Fraction | float | a percent is its fraction: 1.0641 is 106.41%; finite; 4 decimals from the engine | NRR 1.0641 |
| Count | int | an observed count, rounded to nearest (half up) by the engine | 12 |
| CountUp | int | a required or implied count, rounded UP by the engine | 129 |
| Days | float | full precision; the display and the export round UP when they write it | 42.1 shows as 43 |
| Currency | float | reporting currency, full precision (the display rounds) | 3129104.4 |
| Months | float | a duration, full precision (the display shows one decimal) | 12.24 |
| Ratio | float | a quotient, 2 decimals from the engine where it was before | 1.28 |
| Plain | int | an identifier or a setting | 1 |

The field names keep their historical `_pct` suffix (`nrr_pct`, `overall_pct`, `win_rate_pct`, `gross_margin_pct`,
`gap_pct`, `moved_mix_pct`, ...): the value is a fraction. Renaming them would touch every stored result and every
reader for no change of behaviour.

Rounding happens once, in the engine, after every calculation that needs the full-precision number has run (the
reconciliation of the two Path to Plan views reads unrounded values, as before). The display rule of each kind
(app/formatting.py) gives the same string for an already-rounded number as for the raw one, so nothing the analyst
reads changes, except as noted in §8.

## 3. The unit check
`schemas.metrics.unit_violations(payload)` walks a validated payload and returns every field that breaks its unit:
- a Fraction outside its range: 0 to 10 (0% to 1000%); -10 to 10 for the fields that can be negative by definition:
  `gross_margin_pct`, `shift_pct_points`, and the NRR fields (a credit note sinks a segment's NRR below zero; the
  engine already handles that case, so the export must not refuse the whole audit for it); no range for `gap_pct` (a
  gap against the P&L has no natural bound);
- a Count or CountUp that is not an integer.

A value of 106.41 where a fraction belongs is caught here (it is above 10), which is the failure this contract
exists for.

## 4. Gateway (H1)
`generate_narrative` and `read_cached_narrative` validate `audits.results` against `MetricsPayload` after loading the
run and before any prompt is loaded or built. On a failure:
- no model call, no cache write, no lock taken;
- one log line with the run id and the paths and error types of the violations (never a value, a segment name or a
  reason text; a data key shows as `*`); no `llm_calls` row, because no call was made;
- the response is `narrative_status="unavailable"`, `reason` = "Narrative could not be generated. The computed
  metrics below are unaffected.", and `metrics` still holds the step's slice, so the dashboard renders every
  computed metric with its citation (CLAUDE.md rule 20).

The validation is the model, then the §3 unit check: a percent of 106.41 where a fraction belongs would otherwise reach
the model as "10641%", and the numeric guard (which compares the model's words with the same payload) would pass it. The
price is that a legitimate figure outside the §3 range (a cohort NRR above 1000%) also makes the narrative unavailable;
the metrics render with their citations either way. A stored result of the old engine (whole-number percents) carries
no `contract_version`, so it fails the validation whatever its values are (a churn of 6.1 for 6.1% is inside the §3
range and could not be told from a fraction by its size).

## 5. Export (H2)
`build_export_workbook` validates `results` against `MetricsPayload`, then runs the §3 unit check, before the first
cell is written. A failure raises `ExportContractError` naming the field paths and the rule; the endpoint answers with
that message and writes no file. In the writer, `xlsx_value` re-checks each cell it prepares (a percent outside
-10 to 10 or a count that is not an integer raises) so no path around the model can write a wrong cell.

Percent cells hold the fraction and carry the Excel format `0%`; Excel shows 1.0641 as 106%. Counts are
written as integers and days are rounded up at the write. Any code that reads a Fraction as a raw number for display multiplies by 100 first
(`fmt_pct`, `fmtPct`, the claim register, the banner text).

## 6. Contract test
`backend/tests/test_interface_contracts.py`:
1. Runs the engine on `sample_data` (revenue, CRM, P&L) and on the demo-audit inputs.
2. Compares every key path of the engine's own output with the model: a path the model does not declare fails the
   test and names the path (the engine output is read before the model touches it).
3. Passes the stored form through the gateway validator and the exporter.
4. Opens the xlsx: the NRR cell on the Headline sheet is numeric, its number format is `0%`, and its displayed text
   is the whole-percent of the engine's NRR ("106%"), never "1%".
5. Failure cases, each shown to fail on a deliberate violation: NRR written as 106.41; a fractional day count; a
   missing `contract_version`; an undeclared engine field; each of `segment_paths`, `new_mrr_by_quarter`,
   `cohort_retention`, `mrr_series`, `anomalies` without its citation; a citation without its rule.
   A block of the model that is neither cited nor listed as exempt fails the test, and so does an engine run whose
   cited block has no rule or rows.
6. Gateway: a bad payload makes no model call and returns the fixed sentence with the metrics.
7. The formatter's kind table is the schema's (no field in one and not the other).

## 7. Readers changed only by the unit change
| Reader | Change |
|---|---|
| `app/formatting.py` `fmt_pct`, `xlsx_value` | multiply by 100 for display; the cell keeps the fraction |
| `frontend/src/lib/format.js` `fmtPct`, `format_vectors.json` | same, pinned by the shared vectors |
| Dashboard, Segment paths, Diagnostics | thresholds and raw `${v}%` text read fractions |
| `app/claim_matching.py` | NRR, churn, win rate, gross margin are read as percent points (x100), as the claims are |
| banner text for the reconciliation blocker | prints `gap_pct` x 100, same words |

Amended 2026-10-20 (George): results stored under another `contract_version` than the code running are no longer recomputed on a
read. They are "Stale – re-run audit" until Run audit calculates again (deterministic Python, no model, no cost): `/results` and the
export answer 409 `{"code": "results_stale", "message": "Stale – re-run audit"}`, the claim register answers no rows and
`results_stale: true`, the dashboard and the register say "Stale – re-run audit", every other reader sees "not computed", and the
review summary reports `engine_stale`. No stored figure is shown as current, whatever its version (the percents of version 0 would
read 100 times too large). Tests: `test_interface_contracts.py` section 6, `test_run_audit.py`, `test_recognition_review.py` L2.

## 8. Consequences to know
- Sales-cycle days (`median_days`, `iqr`) are stored unrounded, so claim matching reads the unrounded median and its
  gaps and labels are unchanged (claim-matching.md section 9 stands). Rounding a median up before matching would move a
  claim across its tolerance at the edge (a Verified claim becomes Contradicted), which is a labelling decision.
- A cohort or segment NRR above 1000%, or a negative one, fails an export with the field named instead of writing it.
- New results key: `contract_version` (server-only: not in the gateway allowlist; backend/tests/test_gateway_data_boundary.py extended).

## 9. Rule
CLAUDE.md rule 23: any change to engine output fields changes `backend/schemas/metrics.py` and the contract test in
the same PR.

Amended 2026-10-20 (George, review): `GET /audits/{id}` and the review summary carry `results_stale`; with stale results `results` is null on
`GET /audits/{id}`, so no stored figure reaches the browser. The header's "evidence to <month>" and the deck list's conversion date (when
the as-of month is defaulted: `fx.date_stale`) read "Stale – re-run audit"; the Review, Diagnostics, the verdict and the memo name it in place
of "compute the audit first" when results exist but are stale. `SEED_VERSION` 12 reseeds demo audits held under contract 4.

Amended 2026-10-20 (George): while the results are stale the banner shows exactly one line, "Stale – re-run audit" (`kind` `results_stale`),
and no blocker. It is a replacement of the blockers, not a fourth blocker, so CLAUDE.md rule 21 holds. Test: `test_interface_contracts.py` section 6.

Amended 2026-10-23 (George, deck read quality): **contract 7.** `CONTRACT_VERSION` 7 and `SEED_VERSION` 14. No engine output field changes: the page reader's closed
metric list gains `arr`, `mrr`, `churn`, `nrr`, `market_share`, `pricing` and `use_of_funds`, which Python maps to register claim types and groups (chat-upload.md
§28, amended 2026-10-23), so the claim types and groups of stored deck claims differ from contract 6 and results and claim matches stored under 6 read "Stale – re-run
audit" until Run audit calculates again. `DECK_CLAIM_FIELDS` (`basis`, `scenario`, `flags`), the register row, the baseline CSV and the memo's Appendix A are unchanged;
`flags` may now hold `year label below: YYYY`. `test_interface_contracts.py` pins `CONTRACT_VERSION == 7`; `test_page_metrics.py` pins the list and the mapping.

Amended 2026-10-23 (George, ARR, MRR, Churn, NRR and CAC payback as claim types): **contract 8.** `CONTRACT_VERSION` 8 and `SEED_VERSION` 15. One engine output field is added (below); the page reader's closed
metric list gains `cac_payback`, and `arr`, `mrr`, `churn` and `nrr` reach the register as claim types of their own (claim-matching.md, amended 2026-10-23), so the claim types of stored deck
claims differ from contract 7 and results and claim matches stored under 7 read "Stale – re-run audit" until Run audit calculates again. `MetricsPayload` gains `gross_churn.monthly_series` (its
`contract_version` literal is 8); `DECK_CLAIM_FIELDS`, the register row, the baseline CSV and the memo's Appendix A are unchanged. `test_interface_contracts.py` pins `CONTRACT_VERSION == 8` and
the stale versions 1 to 7; `test_recurring_claim_types.py` pins the types, the metric each is tested against and the reasons.

Amended 2026-10-23 (George, decision on PR 171; contract 8 stays): **`gross_churn.monthly_series`**, a required list of `{month, churn_pct}` (a Fraction, null when the MRR at the month's start is
zero), one rate per month from the second data month: MRR lost in the month (churn and contraction, expansion not netted, as `overall_pct`) over the MRR of the customers that had revenue at the month's
start. A Possibly partial last month is skipped as for NRR. `metric_periods` gains `gross_churn_monthly` (first, last, missing months of the series). The series is the register's and the export's: server-only
(`SERVER_ONLY_FIELDS` of `test_gateway_data_boundary.py`, never sent to a narrative). `test_interface_contracts.py` drops it and breaks it in its violation table; `test_monthly_churn.py` pins the arithmetic.
The xlsx export gains a "Churn Series" sheet (month, trailing-12-month rate, monthly rate); a source key under `gross_churn.series` or `gross_churn.monthly_series` names that sheet.
