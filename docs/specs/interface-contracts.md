# Spec: Interface contracts on two handoffs
Status: Draft; the agreed scope is the task of 2026-10-08. Location: docs/specs/interface-contracts.md.
No architecture change: the engine stays pure, the gateway stays the only caller of a model, the export stays in the API.
Amended 2026-11-07 (George, structure-aware reading; docs/specs/structure-extraction.md): `contract_version` 27. `role_metrics.integrity_flags[].kind` gains `hardcoded_in_formula_row` and `total_omits_cells` (each with `file`, `count`, `cells` as "Sheet!D5", "(hidden)" after a cell in a hidden row or column, and `text`); `role_metrics.structure_checks` ({files, files_with_formulas}, optional) says whether the two tests had a workbook with formulas to test. The parent rows of a sheet with a SUM total row are the formula's own (the stored reading keeps the reader's). The data-integrity table gains the two checks (Green none, Amber 1-2 cells, Red 3 or more). Results stored under 26 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 27`.
Amended 2026-11-06 (George, sheet types): `contract_version` 26. A sheet's type comes from its name, else the text above its header row: P&L (pnl, p&l, profit, income statement), cash flow, balance sheet (`MapSheet.sheet_type`, set by code). P&L roles (revenue, cost of revenue, S&M, R&D, G&A, OPEX, EBITDA, margins) are read from P&L-type or untyped sheets only; such a row on a cash-flow or balance-sheet sheet is relabelled `other` (`classified_by` "sheet_type", note "cash movement, not a P&L line"), at register time on stored readings like the label rule, and is in no reconciliation, TOTAL-vs-months check or trend. A cash balance is read from a cash-flow or balance-sheet sheet first. Reconciliation sources are different files or deck pages, never two sheets of one file. `integrity_flags[].double_counted` (totals_mismatch): the parts sum to twice the total within 5 %; the text reads "parts counted twice — the sheet has two breakdowns of this total; the calculation uses the total" and Worth flagging leaves it out. Results stored under 25 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 26`.
Amended 2026-11-06 (George, mapping-page cards): `contract_version` 25. `role_metrics.integrity_flags[].kind` gains `totals_mismatch`: a total row whose mapped parts do not add up to it within 1 % (absolute values, first period column that fails) is an integrity finding and no rejection, re-read or card; the total row is kept as read. The flag carries `sheet`, `row`, `total`, `parts_sum`, `difference` and `pct` (a fraction of the total) besides `file`, `count` (1), `cells` and `text` ("CASHFLOW row 23: total 129,200 vs parts 62,891, 51% — a part row may be unmapped or the total hard-coded"); the data integrity table lists it as "Totals that don't add up" and Worth flagging prints it when the difference is over 5 %. A cited cell that holds a formula error is that error ("cell AW4 holds #REF!"), counted in the formula-error flag, not a disagreement. Results stored under 24 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 25`.
Amended 2026-11-06 (George, board-pack dating): `contract_version` 24. A month header with no year ("December") takes its year from the quarter, half or year header that closes its block (the first to its right with no dated month between: "Q4 2023", "TOTAL 2023"), else from a year title above its block; never from the most recent year of another block or a date-typed header elsewhere. Periods increase left to right across a sheet: a month that goes back or repeats, one its closing header does not contain, and one nothing dates is "undated", left out of every series, stored on the sheet map as `undated` ({cell, text}, written with the series, stripped before the reader's schema) and told by a `mapping_flags` entry (role `periods`, `rows` the header row, new `undated` list of header cells). The latest year's revenue (growth by year, yearly revenue and the yearly-basis block) is the TOTAL column when the monthly sheet has one, the as-of year counting although it is not over; the sum of twelve months is used only for a year with no total column. The TOTAL of the latest year is compared with its months to the as-of month; a difference above 1 % is a `mapping_flags` entry (role `revenue`) naming both cells and Worth flagging prints it. The as-of year, while the as-of month is before its fiscal year end, carries `label` "YYYY (to Mon)" ("2024 (to Nov)") on `growth_by_year`, `pnl_trend.periods` and the trend values; `period` stays the key. The trend lists that year when its TOTAL column states it. The label is printed in the trend table, growth by year, the templated lines, the Excel trend sheet and the growth card. A mapping flag counts each row once, however many reads or records hold it ("rows 4, 4, 4" is never produced). Results stored under 23 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 24`.
Amended 2026-11-06 (George, board-pack layout and mapping-page fixes): `contract_version` 23. Every period column is classified from its header as a month, a quarter ("Q1 2024") or a year ("TOTAL 2021", "FY 2021", "2021"; a datetime header is a month). A row's `series` holds the columns of the sheet's own grain only; the quarter and year columns of a monthly sheet are the row's `subtotal_series` (periods "2024-Q1", "2021"), and the role table gives them records of their own at the quarterly and yearly granularity, so yearly revenue, EBITDA, gross margin and CAC payback read the TOTAL columns and no quarter lands on a month's key. A growth-by-year citation lists the month cells one range per contiguous run. A hidden sheet is read and named "(hidden)" in every citation; a role mapped on a visible and on a hidden sheet is read from the visible one and the hidden copy is a `mapping_flags` entry (`used_sheet`, `hidden`). `role_metrics` gains `integrity_flags` (`kind` formula_error, `file`, `count`, `cells`, `text`): a file with cells holding #REF!, #DIV/0!, #N/A, #VALUE!, #NAME?, #NUM! or #NULL!, listed with the data integrity findings and under Worth flagging. The reviewer's `ReviewFinding` gains the optional `fix` ({field currency | role | metric, value}); a card offers `apply_fix` only for a fix code accepted, and a card with no fix has no action. Results stored under 22 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 23`.
Amended 2026-11-05 (George, reading consistency, second pass): `contract_version` 22. A held row feeds no estimate: while a row an OPEX-split estimate is built from (OPEX, S&M, R&D, G&A) is held out because the two reads disagree on it, the S&M, R&D and G&A estimates, and a "No estimate" line, read "awaits confirmation" (status `needs_row`, no value); `pnl_trend` rows gain the optional `reason` ("awaits confirmation" when a role the line needs is held and a value was dropped or a period is left without one; an estimate built from a held row is dropped); the mapping flag skips the role `other`. Two reads that differ in the segment flag alone are no disagreement. Results stored under 21 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 22`.
Amended 2026-11-04 (reading consistency, docs/design/reading-consistency.md): `contract_version` 21. `role_metrics` gains `awaiting_confirmation` (`{count, rows, figures}`): the spreadsheet rows and deck figures the two reads disagree on, whatever their role or metric. A deck figure with the flag `reading uncertain` is held out of the reconciliation and the growth by year; a spreadsheet row the reads disagree on (role, metric, series, segment flag, parent row, unit, currency or basis; the last three added 2026-11-05) carries `uncertain` in the role table and is held out of every calculation, and so does every row of a sheet the reads disagree on at sheet level (a sheet only one read gives, or a layout field that differs: granularity, header row, last actual column; review of commit 2, 2026-11-05); a metric that needs only held rows reads "awaits confirmation". Results stored under 20 read "Stale – re-run audit".
Amended 2026-11-04 (reconciliation and parts-sum rules): `contract_version` 20. `role_metrics` gains `mapping_flags` (`[{role, file, sheet, rows, used_row, text}]`): two or more rows of one role in one sheet with no parent link, text "two rows mapped as customers (rows 23, 24); the calculation uses row 23", listed under Worth flagging. `role_metrics.reconciliation` is yearly revenue only (ARR, MRR, customers, EBITDA, cash and headcount are not compared across sources); a source is a sheet of a file or a deck page, never a row; the percentage difference is the difference over the largest value (the legacy `revenue_reconciliation` divided by the P&L before). The mapping-page parts-sum check compares absolute values. Results stored under 19 read "Stale – re-run audit".
Amended 2026-11-04 (cleanup PR 6): `contract_version` 19. No field is added or removed. Yearly revenue read from a monthly revenue file with no yearly P&L says "needs a yearly P&L; the revenue file is monthly" instead of "needs a revenue row". EBITDA margin is no longer the margin of one month of a monthly row: it is read from a yearly or quarterly EBITDA row (quarterly rows are now read), or from the twelve months of one fiscal year (sum of EBITDA over sum of revenue, both rows' actual series, the fiscal year of the audit's year-end; a cumulative-to-date or last-12-months row is never summed; the entry's basis is yearly with the label "full year, sum of 12 months", so the Excel yearly sheets list it), else "needs an EBITDA row at yearly or quarterly granularity, or twelve months of one year". Results stored under 18 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 19` and the stale version 18.
Amended 2026-11-04 (George, three-way OPEX split, docs/design/pnl-lines.md): `contract_version` 18. `role_metrics` gains the metric `sm_expense` (S&M expense of the latest actual year, an estimate only: actual OPEX × the pooled plan share of S&M over S&M + R&D + G&A, when that year carries OPEX and no S&M, R&D or G&A value and the plan years carry all three; same checks (a) and (b) as the two-way split, the share check on each of the three shares; a failed check gives no S&M line and R&D and G&A carry the "No estimate: check (a)/(b) failed ..." reason). R&D and G&A expense take the same three-way estimate in that case; the two-way split is unchanged and takes priority when the year has actual S&M. The estimate flag, label and cells are as in contract 17; `pnl_trend` S&M share can carry the flag. Results stored under 17 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 18` and the stale version 17.
Amended 2026-11-03 (George, PR 226, docs/design/read-check-review.md section 16): `contract_version` 17. `role_metrics` gains two metrics, `rnd_expense` and `ga_expense`, and every `RoleMetric` the flag `estimate` (default false): R&D and G&A of the latest actual year, from the file's own row where it states the year, else estimated as the plan split (r = R&D ÷ (R&D + G&A) over the plan years) applied to the year's OPEX less S&M, gated by checks (a) parts = OPEX within 1 % in every plan year and (b) r within 10 points; a failed check or a missing input gives no value and the one reason line the engine wrote ("No estimate: ...", kept by `report_text.apply_reasons`). An estimate carries the label "Estimate – plan split applied to actual OPEX" and its method with every cell in `source.rule`, is read by no rating, stays on the data request, and sits in its own Appendix C table "Estimates". `role_metrics` also gains the server-only block `pnl_trend` (the yearly P&L trend with the cells of every value). Every cost role is the sum of all the total rows mapped to it, a part left out only when its parent row holds a value in the series being summed. Results stored under 16 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 17` and the stale version 16.
Amended 2026-11-01 (George, docs/design/read-check-review.md section 16, PR 4, #213): `contract_version` 16. A new server-only block `role_metrics` (`RoleMetrics`: every metric by the role of the rows it reads, computed with its `RoleSource` of cells or "needs a <role> row" with the roles it needs; `plan_to_date`; `growth_by_year`; `reconciliation`, the same metric and period across files and decks), fed by the stored map and its series; the yearly payback reasons name the role row they need. `role_metrics` is declared server-only in `test_gateway_data_boundary.py`. Results stored under 15 read "Stale – re-run audit". `test_interface_contracts.py` pins `CONTRACT_VERSION == 16`.
Amended 2026-10-28 (George, docs/design/deck-actuals.md): `contract_version` 13. One optional engine field is added: `yearly_basis.years[].revenue_cells`, the cells of the year's revenue line, so a deck figure reconciled with the yearly P&L cites its file cell ("File P&L!E3"). The register gains `period_sort`, `deck_status`, `deck_only`, `source`, `details` and `data_request` (computed on read, not engine fields); results stored under 12 read "Stale – re-run audit"; demo audits are reseeded (SEED_VERSION 20). `test_interface_contracts.py` pins `CONTRACT_VERSION == 13`.
Amended 2026-10-29 (George, docs/design/read-check-review.md section 4, PR 2): `contract_version` 15. No engine block changes. `FileMap` (`schemas/metrics.py`: `sheets` with their rows, the last actual column and its evidence; `figures` with their source; one schema for sheets and decks) is the reader's answer and the shape of a stored reading (`app/readings.py`, collections `readings`, `reading_uses`, `reading_rereads`, `reading_overrides`, `reading_checks`). The JSON schema the model is sent is generated from it (`llm/schemas.file_map_schema`), as text inside the request since 2026-10-30 (the provider refused the file map as a strict output schema; `FileMap` validates the reply in code, one retry with the first ten errors, then "reading did not match the map schema"). The as-of month now comes from the reader's checked evidence; the boundary-cue suggestion of PR 199 and the last-unmarked-column fallback are removed. Results stored under 14 read "Stale – re-run audit"; `SEED_VERSION` 22. `test_interface_contracts.py` pins `CONTRACT_VERSION == 15` and holds the file map's contract test.
Amended 2026-10-28 (George, docs/design/pnl-lines.md): `contract_version` 14. A new server-only block `pnl_lines` (`PnlLines`: `basis`, `findings` of the sum, recompute and sign checks, `plan` cells with implied against observed rate, `source`) is built from any P&L read as a statement, yearly or monthly, and `yearly_basis.years` gains `cac_payback_label` ("yearly, revenue-based"). S&M leaves out the sub-lines of its totals that are mapped to overhead (internal events). `pnl_lines` is declared server-only in `test_gateway_data_boundary.py` and cited in `test_interface_contracts.py`. Results and claim matches stored under 13 read "Stale – re-run audit" until Run audit calculates again; `SEED_VERSION` 21. `test_interface_contracts.py` pins `CONTRACT_VERSION == 14`.
Amended 2026-10-27 (George, docs/design/page-image.md sections 4 and 5): `contract_version` 11. No engine block changes. A page claim gains four nullable fields (`label_text`, `segment`, `share_of`, `is_quote`) and the checks that retyped a claim now run on a blank field only, so claim matches and results stored under 10 read "Stale – re-run audit" until Run audit calculates again; demo audits are reseeded (SEED_VERSION 18).
Amended 2026-10-26 (George, docs/specs/forecast-and-payback.md section 4.5): `contract_version` 10. The yearly-basis block (`yearly_basis.years`, chat-upload.md §26.8) gains optional fields: `period_start`, `period_end`, `sm_expense`, `sm_scope`
(sales and marketing, marketing only, sales only, unknown), `arr_year_end`, `arr_prior_year_end`, `net_new_arr`, `cac_payback_net_new_arr_months` and `cac_payback_net_new_arr_reason`; `cac_payback_months` is named the revenue-growth
proxy. The register rows gain `calc_lines` and `calc_details` (register fields, not engine output). Results and claim matches stored under version 9 read "Stale – re-run audit" until Run audit calculates again; `SEED_VERSION` 17.
`test_interface_contracts.py` pins `CONTRACT_VERSION == 10`, the stale versions 1 to 4, 8 and 9, and the source keys of an annual payback claim (`yearly_basis.years.cac_payback_months` and `.cac_payback_net_new_arr_months`).
Amended 2026-10-26 (George, docs/specs/claim-groups.md): no engine output field changes and `contract_version` stays 9. `group_id`, `group_role` and `relationship` are register fields (claim-matching.md §6) and `audits.group_choices` is
an analyst decision stored on the audit (hashes, no deck text); none is a results key, so `schemas/metrics.py` and `test_interface_contracts.py` do not change.
Amended 2026-10-25 (George, docs/design/simplified-flow.md): `contract_version` 9 marks the simplified flow. No engine block changes. What changes is how the stored
claims read: they enter the register without an approval, a stated figure the app cannot test reads Unverified, gates are written from the claim and the ratings
are computed, so results and claim matches stored under version 8 read "Stale – re-run audit" until Run audit calculates again. `ic_inputs.note` (the optional analyst note,
at most 1,000 characters, one line in the memo, never sent to a model) is an analyst input stored on the audit, not a results key; `ic_inputs.ratings` and
`ic_inputs.judgment` stay stored and are no longer read. `test_interface_contracts.py` pins `CONTRACT_VERSION == 9` and the stale versions 1 to 4 and 8.
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
start. The last month is read as for NRR (the as-of month always counts as complete, amended 2026-10-28). `metric_periods` gains `gross_churn_monthly` (first, last, missing months of the series). The series is the register's and the export's: server-only
(`SERVER_ONLY_FIELDS` of `test_gateway_data_boundary.py`, never sent to a narrative). `test_interface_contracts.py` drops it and breaks it in its violation table; `test_monthly_churn.py` pins the arithmetic.
The xlsx export gains a "Churn Series" sheet (month, trailing-12-month rate, monthly rate); a source key under `gross_churn.series` or `gross_churn.monthly_series` names that sheet.

Amended 2026-10-24 (George, chat-upload.md §30 point 6): results are also "Stale – re-run audit" when a set-up input they were computed with changed since (audit field `setup_stale`: Reporting currency, Target ARR, Target date,
As-of month, fiscal year-end, FX rates). `run_audit.results_stale` reads both; every reader of §7 above behaves the same. Run audit calculates again and clears the field. No engine output field and no contract version change.

Amended 2026-10-26 (source association, docs/specs/source-association.md): no engine output field, no register field and no contract version change. The deck claim's `flags` may hold four
more closed words (`sources disagree`, `source ambiguous`, `source not associated`, `extraction incomplete`); `DECK_CLAIM_FIELDS`, the baseline CSV and the memo's Appendix A are unchanged.
