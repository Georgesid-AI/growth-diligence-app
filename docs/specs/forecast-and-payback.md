# Spec: Forecast diagnostics, annual payback and the shared four-column presentation
Status: Agreed scope, the task of 2026-10-26: sections 3, 5 and 6 of docs/design/claim-review-simplified-design.md (that design note is not amended), and one conclusion fix
(section 7 below). Location: docs/specs/forecast-and-payback.md. Sections 1 and 2 of the design note are docs/specs/claim-groups.md; section 4 (source association) is
docs/specs/source-association.md. Code: `backend/app/forecast_calc.py`, `backend/app/payback_definition.py`, `backend/growth_engine.py` (`compute_yearly_basis`),
`backend/app/claim_matching.py`, `backend/app/verdict.py`, `backend/app/ic_memo.py`, `frontend/src/components/ClaimRegister.jsx`, `FiveClaims.jsx`.
Fixture decks only: synthetic companies, synthetic figures.
No architecture change (docs/architecture.md is frozen): both new modules are pure like `claim_matching`, nothing reaches a model, and the evidence tiers, citations and source
references stay as they are. The engine output changes only in the yearly-basis block (section 4.5), so `CONTRACT_VERSION` moves to 10 in the same change (CLAUDE.md rule 23).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: a forecast claim reads today "Forecast period after the data ... cannot be tested" on every row, with a "to go" gap; the analyst gets no view of how demanding the plan is
  against what the company has done. A yearly-basis P&L gives one payback proxy under one name and no sign of what the S&M line covers. The register, the five, the memo and the CSV each
  word the same row their own way. The simpler version: one backend result per row (the existing fields plus two lists of calculation lines), read by every view; no new verdict logic.
- Deleted first: the "Forecast period after the data" sentence on every row (`FORECAST_AFTER_DATA`, `forecast_after_data`); the rule that a period after the as-of month makes a claim a
  forecast; the seven-column register (rank, segment and extraction-confidence columns move under Details); the `#rank` prefix on every screen; the proposed 5-point pass/fail rule
  and the "beat" wording for a forecast (neither exists in the code: nothing to delete, and a test pins that a forecast never reads Verified, Contradicted or beat); the proposed
  "all five are forecasts" branch (not in the code either). The "beat" of an actual result that is within tolerance (claim-matching.md section 4, 2026-10-13) is another thing and stays.

## 1. Map of the design note to what exists
| Design note | Existing | Built here |
|---|---|---|
| 3. Actual or forecast from the source classification; a later period alone is missing coverage | `figure_type` (analyst, parser target cue, else Python from the period), `basis` and `scenario` of the page reader, `origin` forecast_file, `_figure_type` | section 2: the period alone no longer decides |
| 3. Required annual growth, historical comparator, gap in points, calculation basis | nothing: a forecast row shows the "to go" gap and one sentence | `forecast_calc.diagnose`, section 3; register fields `calc_lines`, `calc_details` |
| 3. Comparable bases (annual revenue, quarter or month revenue, ARR, MRR, customers) | `revenue_series`, `mrr_series`, `customers_series`, `metric_periods` (`_Span`) | section 3.2 |
| 3. Under 12 months the history is limited; observations are not elapsed time | `NRR` and churn need 12+ months (`insufficient_history`) | section 3.4 |
| 3. Ranges as ranges; remaining amount; no verification of the future | `claimed_high`, "to go" gap, label Unverified | sections 3.5 to 3.7 |
| 3. Revenue per customer, ARR per customer cross-checks in Details when definitions align | none | not built: no cross-check exists today to align; nothing is added (section 9) |
| 5. Annual payback with an explicit basis; denominators named; scope of the numerator | `compute_yearly_basis` (revenue-growth denominator only, S&M scope unread), `YearlyYear` | section 4; `YearlyYear` gains optional fields; contract 10 |
| 5. Compare a claim only with a matching definition, period and cost basis | CAC payback claims are read against a calendar quarter of the monthly P&L; an annual claim reads "the period is not one calendar quarter" | `payback_definition`, section 4.3 |
| 5. Missing or non-positive denominators or margin: a specific reason; scoped data requests | `cac_payback_reason`; one "CAC payback" Missing Data item for the whole metric | sections 4.2 and 4.4 |
| 6. Four columns; one note for forecasts; no rank prefixes; stable references | seven register columns, three on the five, a note per row, `#rank` prefixes | section 5 |
| 6. One backend result across views; flatten for a flat format | register row = `claim_matching.FIELDS`, baseline CSV and memo Appendix A read it | section 5.3 |

## 2. Actual or forecast (design note section 3, first paragraph)
- A claim is a forecast when its source classification says so, and only then: the analyst's figure type `target`; the parser's `target` (a target cue in the claim's words,
  claim-types-and-correction.md section 2.1); the page reader's `basis` `projection` or `scenario`; a claim read from a forecast table (`origin` forecast_file, unchanged: never
  matched). The period alone no longer decides.
- `figure_type` is therefore: the analyst's or the parser's value; else `target` when a target cue stands in the claim's words; else `target` when the reader's `basis` is
  `projection` or `scenario` **and** the period ends after the as-of month; else `actual` when the period is known; else unknown. A `basis` of `projection` for a period on or before the
  as-of month stays `actual` with the existing flag "basis conflicts with period" (claim-matching.md, M2).
- A claim of type `actual` whose period ends after the as-of month is not a forecast: its months are not in the data, so the existing coverage rule applies ("claim period not in
  supplied data: after the latest valid source period, {month}" or "months missing: ..."), label Unverified, no calculation, no "to go".
- A forecast is never Verified or Contradicted and has no "beat": its label is Unverified, whatever the calculation says. A target for a period that has passed keeps
  "target figure: the deck states a plan for this period, not a result".

## 3. Forecast calculation (`forecast_calc.py`)
Pure Python over the stored series; no model. It runs for a forecast claim whose metric is Revenue, ARR, MRR or Customer count, read for the whole company or a segment the series
holds. Every other forecast claim keeps label Unverified with the reason "Forecast: no comparison is calculated for this metric" and no calculation lines.

### 3.1 The formula
`required annual growth = (forecast / base) ^ (12 / elapsed months) - 1`, calculated only when the forecast, the base and the elapsed months are all positive and the amounts are
comparable (same metric, same scope, the claim in the reporting currency at the saved rate, a population that matches). Otherwise the line reads
`Required growth: not calculated – {reason}` with one reason of section 3.8. A claim never stands in for a missing base, and a quarter or a month is never divided by an annual total.

### 3.2 The comparable base
| Claim | Base | Elapsed months |
|---|---|---|
| Revenue, a fiscal year (twelve months) | the latest complete actual fiscal year before the claim's year (all twelve months in the data, the last at or before the last month the data can be read at); if the data holds no complete fiscal year, the complete trailing 12 months ending at that last month. The line names the exact window | from the end of the base window to the end of the claim's period |
| Revenue, a fiscal quarter or a calendar month | the same quarter or month in the latest earlier year whose months are all in the data (the claim's window moved back 12, 24, ... months) | 12 × the years moved back |
| ARR, MRR, Customer count | the latest actual observation of the same metric and scope (the last month the data can be read at) | from that month to the end of the claim's period |
A period that is not twelve, three or one month long is not calculated ("period is not a year, a quarter or a month").

### 3.3 The historical comparator
- Preferred: growth between comparable annual windows: base window ÷ the window twelve months before it − 1 (fiscal year over fiscal year; trailing 12 months over the 12 before; a
  quarter or month over the same quarter or month a year before; a balance over the same balance twelve months before). Both windows must be complete and positive. The line names both
  windows: `Historical growth: 21.0% (FY2024 → FY2025)`.
- The difference is `required − historical`, in percentage points, shown only against this comparator: `Difference: +12.4 percentage points (required less historical)`. It is a number,
  not a verdict: there is no threshold, no pass or fail and no word such as beat, ahead or behind.
- When the annual comparator is not available but at least two months of the series are, the line reads `Pace indicator (monthly endpoint growth, not annual growth): 18.2%
  annualised, 2023-01 to 2024-02, 13 months elapsed, 14 observations` and no difference is shown against it. A pace indicator over fewer than 12 elapsed months adds `history limited: under 12
  months`. Observations and elapsed months are two numbers: eleven observations can span 30 months.

### 3.4 Insufficient history and missing periods
- No annual comparator: `Historical growth: not available – insufficient history: {what is missing}`, with the specific window ("no complete 12 months before 2023-12") or the months
  missing ("months missing in the comparator window: 2023-05").
- A gap inside a window makes that window incomplete, never a smaller figure: the base is the latest complete window (a fiscal year, a quarter or a month moves back one year at a time), and
  when none is complete the reason is `no complete 12 months of actual revenue` (or the missing comparator of a quarter or month). A gap inside the comparator window leaves the base as it is and
  names the months: `insufficient history: months missing in the comparator window FY2023: 2023-05`.

### 3.5 Ranges
A claim with a range (`claimed_high`) shows the range, not the end that compares best: `Required growth: 20.1% to 33.4% a year (...)`, and the difference as a range. Both ends must pass
section 3.1; if either does not, no growth is calculated and the reason names the end.

### 3.6 Remaining target
When months of the claim's period are already in the data (a fiscal year partly actual, a flow), the remaining amount is the claimed amount less the actual to date, labelled as a calculation:
`Remaining to reach the target: €1.2M (calculation: 5 of 12 months actual, €0.9M to date)`. For a balance it is the claim less the latest observation. It is not a gap, a miss or a shortfall.
The existing "to go" gap, gloss and ordering of the register stay as they are.

### 3.7 No verification of the future
The label is Unverified. The reason is `Forecast: required growth 33.4% a year against 21.0% historical`, or `Forecast: {unavailable reason}`. The one sentence "Forecast calculations
describe assumptions; future outcomes are unverified." is shown once above the register, once under the five and once in the memo's summary, whenever a forecast row appears, and
on no row.

### 3.8 Reasons a calculation is unavailable (closed list; the boundary test lists them)
For the required growth: `period is not a year, a quarter or a month` · `no complete 12 months of actual revenue` · `no actual revenue for the same {quarter|month} of an earlier year (missing
comparator: {window})` · `no actual observation of {metric}` · `base not positive` · `forecast not positive` · `elapsed months not positive` · `population differs: the claim counts {claimed}, the series
counts {measured}`. For the comparator: `insufficient history: no complete 12 months before {window}` · `insufficient history: no complete {quarter|month} a year before {window}` · `insufficient history:
months missing in the comparator window {window}: {months}` · `insufficient history: no observation of {metric} at {month}` · `comparator base not positive`. A claim in another currency with
no saved rate reads `FX rate needed` and a segment the data lacks reads `segment not in the data`, as before, and have no calculation.

### 3.9 Register fields
`calc_lines` (list of strings: required growth, historical comparator or pace indicator, difference, remaining) and `calc_details` (list of strings: the formula, each input with its
window and source, the comparator inputs). Both are last in `claim_matching.FIELDS`, empty for a row with no calculation; the baseline CSV joins a list by "; " (so no line holds "; ").
They hold figures and closed words only, no deck text.

## 4. Annual payback (design note section 5)
### 4.1 Calculation
`annual payback = 12 × S&M / (incremental annual recurring value × gross margin)`, in months, per actual fiscal year of the yearly-basis block. Two proxies are always named and kept:
- **Revenue-growth proxy**: incremental value = revenue this year less revenue the year before (the existing figure; `cac_payback_months`).
- **Net-new-ARR proxy**: incremental value = year-end ARR less the prior year-end ARR (ARR = the revenue file's recurring MRR of the fiscal year's last month × 12, the whole company).
Neither verifies a claim whose definition differs. Each row of the block shows the value, the fiscal year, the denominator basis and its source.

### 4.2 Unavailable
A proxy without a value carries one reason: `no S&M line` · `no revenue for the year before` · `no ARR series (revenue file)` · `no ARR for the year-end before` · `new revenue not positive` ·
`no ARR for the year-end` · `net new ARR not positive` · `gross margin not positive or missing` · `S&M not positive`.

### 4.3 The numerator's scope and the claim's definition
- The S&M line's scope is read from its label(s): `sales and marketing` ("sales and marketing", "s&m", a sales line with a marketing line, "Sales" alone in a cost section
  as chat-upload.md rule 4), `marketing only` ("marketing", "advertising"), `sales only` ("sales expenses", "sales costs"), else `unknown`. It is stored as `sm_scope` and shown beside the
  figure. A marketing-only line is calculated and named as such; it is never presented as total S&M.
- A CAC payback claim whose period is one fiscal year is read against these figures only when its definition matches (`payback_definition.py`, read from the claim's own words
  in Python, as the growth basis is): the denominator (`net new ARR` or `revenue growth`), gross-margin adjusted, and the cost basis (`sales and marketing`, `marketing only`). A part the claim
  does not state is unknown and never assumed equal (design note section 1). All three known and equal to a proxy of that year with a value, and the period is that fiscal year:
  tested as any claim (tolerance of the CAC payback metric, labels Verified or Contradicted, a Definition check beyond the usual gap). Otherwise the row is Unverified with the reason
  `definition not compared: {what differs or is not stated}` and both figures are listed in `calc_lines`. The claim never reads against a differently defined figure.
- A CAC payback claim for a calendar quarter, or one with no annual period, keeps the monthly path (quarter, lag).

### 4.4 Data requests
The Missing Data item "CAC payback" stays for the monthly timing, and only the claim whose question the annual figure answers (a matching definition, a year with a value) is taken out of
it: its row reads its label, not `Missing: ...`, and is not listed as blocked by the gap. A claim of another year, of a definition the annual figures do not answer, or with no value for its
year keeps the request, with the specific reason from section 4.2 beside it. The yearly-basis block's `missing` list names the monthly timing as "CAC payback (monthly timing)".

### 4.5 Engine output (schemas/metrics.py, `YearlyYear`; contract 10)
Optional fields added: `period_start`, `period_end` (months, `YYYY-MM`, from the header read for the audit's year-end), `sm_expense` (Currency), `sm_scope` (closed words above),
`arr_year_end`, `arr_prior_year_end` (Currency), `net_new_arr` (Currency), `cac_payback_net_new_arr_months` (Months), `cac_payback_net_new_arr_reason` (text, closed list).
`cac_payback_months` and `cac_payback_reason` keep their meaning and are the revenue-growth proxy. Results stored under contract 9 read "Stale – re-run audit" until Run audit
calculates again; `SEED_VERSION` 17.

## 5. One presentation (design note section 6)
### 5.1 The four columns
**Claim and period · Evidence / calculation · Result · Source**, in this order, on the register and on the five selected claims (shared component `ClaimFourColumns`, one list in
`frontend/src/lib/claim_columns.json`, which the backend pins and the memo's Appendix A opens with). Claim and period: the claim's words and figure, its period and its period note.
Evidence / calculation: for a forecast or an annual payback claim its `calc_lines`; otherwise the observed figure with the month it was read at and the gap. Result: the evidence label
with its definition on hover, and the row's reason. Source: the observed source, the figure's citation and the deck page.
Under Details (a native `details` element, the content stays in the page): `calc_details`, the relationship and parts of a group, the segment and metric controls, the extraction
confidence, how the deck was read, the gloss, value at stake, overlaps, the gate sentence, the turnover, definition and growth-basis controls, the corrections (the existing edit, exclude
and Undo controls are reused unchanged).
The seven-column register, the three-column five ("Plan assumes · Evidence shows · Result", docs/design/simplified-flow.md) and the per-row forecast sentence are replaced by this section; that note is not
amended.
### 5.2 No rank prefix
No screen shows `#rank`. A claim is named by its words and period; its stable reference is `claim_id`, which the API, the CSV and the memo's Appendix A keep. Texts the server writes for a
screen no longer cite a rank: the repeat note reads "Same figure as the one stated on {page}; counted once"; the reasons, the Worth flagging lines, the data-gap lines and the unmeasured list
name the claim ("Revenue, FY2025"). The memo keeps its rank column and footnote numbers in Appendix A and the footnotes, the position references of that printed document; the CSV keeps `rank` and `claim_id`.
### 5.3 Same values everywhere
The screen reads the register row; the memo's Appendix A and the baseline CSV read the same row. Value, evidence label, relationship, source and calculation lines are the same strings in
all three (a test builds one audit and compares them). The memo's Appendix A opens with the four column names; its other columns (approval, basis, case, relationship, value at stake,
overlaps, gate, key gate, top 5) follow, the rank in a column "Ref" (the memo keeps its position references: its footnotes and "counted in" notes cite them).

## 6. Contract, data boundary
- `schemas/metrics.py`: `YearlyYear` only (section 4.5); `CONTRACT_VERSION` 10; `test_interface_contracts.py` pins 10 and the stale versions 1 to 4, 8 and 9 (docs/specs/interface-contracts.md).
- `forecast_calc`, `payback_definition` and the register's new fields import nothing from the gateway and log nothing. `calc_lines`, `calc_details`, `sm_scope` and the closed reasons of
  sections 3.8 and 4.2 join the boundary lists of `test_gateway_data_boundary.py` (CLAUDE.md rule 14): never in a gateway payload, a log line or a gateway collection. The claim's words are read
  in Python only, as the growth basis is.

## 7. Conclusion with open annual conflicts
When every annual figure of the register is in an open conflict (docs/specs/claim-groups.md section 5) and no other claim can be one of the five, the conclusion is **Insufficient evidence**, code `insufficient`, with
the rule line `No claim can be tested yet; {n} conflict(s) open.` ("2 conflicts open."), in the verdict and in the memo (summary line "Conclusion: Insufficient evidence – ..."). "No testable claims" is
shown only when the register holds no claim and no conflict. The conflicts stay listed under the conclusion as before, and the open-question count on the rule line does not count them twice.

## 8. Tests (the acceptance table, this scope)
| Capability | Check | File |
|---|---|---|
| Forecast diagnostics: like-duration bases | annual against fiscal year, trailing 12 months when no fiscal year is complete, a quarter against the same quarter, a month against the same month, a balance against its latest observation; a quarter never against an annual total; March year-end | `test_forecast_calc.py` |
| Insufficient history, missing periods | no comparator window; months missing in the base or comparator window; pace indicator named apart, with dates and interval, "limited" under 12 months, observations apart from elapsed months | `test_forecast_calc.py` |
| Zero and negative inputs | base, forecast, elapsed and comparator base zero or negative: a specific reason, never a number | `test_forecast_calc.py` |
| Ranges | both ends shown, never the better end; an invalid end blocks the calculation | `test_forecast_calc.py` |
| Remaining target | the part-year actual, the remaining amount labelled as a calculation, none for a balance without a gap | `test_forecast_calc.py` |
| No verification of future outcomes | a forecast is Unverified however large the gap; no beat; no pass or fail; the note once, not on a row | `test_forecast_register.py` |
| Actual or forecast from the classification | period alone is missing coverage; projection and target cue are forecasts; the analyst's type wins | `test_forecast_register.py` |
| Annual payback: matching and mismatching definitions | the claim states denominator, margin and cost basis; one differs or is unstated: Unverified, "definition not compared" | `test_annual_payback.py` |
| Annual payback: proxies | revenue-growth and net-new-ARR proxies both kept and named; neither verifies a differently defined claim | `test_annual_payback.py`, `test_growth_engine.py` |
| Annual payback: missing years or costs, invalid denominator | each reason of section 4.2; a marketing-only line named as such | `test_annual_payback.py`, `test_growth_engine.py` |
| Correctly scoped data requests | the answered claim leaves the request; another year, another definition and monthly timing keep it | `test_annual_payback.py` |
| Consistent outputs | the same values, status, relationship, source and calculation lines in the register payload, the baseline CSV and the memo's Appendix A | `test_consistent_outputs.py` |
| The four columns, one note, no rank | the register and the five render the four columns and the note once; no `#` prefix; the corrections under Details; the two proxies in the Years table | `ClaimRegister.forecast.test.jsx`, `FiveClaims.forecast.test.jsx`, `claimColumns.test.js`, `YearlyBasis.test.jsx` |
| Conclusion with open conflicts | Insufficient evidence with "n conflicts open" in the verdict and the memo; "No testable claims" only for an empty register | `test_conclusion_conflicts.py`, `Verdict.conclusion.test.jsx` |
| Boundary | no gateway module names the new fields; closed reasons; no log line | `test_gateway_data_boundary.py` |

## 9. Decided (engineering, rule 19) and left out
- The pace indicator is named apart and carries no difference in points: it is not annual growth (design note section 3).
- The comparator is the growth of the base window over the window before it; the claim's own year is never in it.
- The cross-checks of the last paragraph of design note section 3 (revenue per year-end customer, ARR per customer against a matching recurring-value measure) are not built: the application
  computes neither today, so there is nothing to align or to explain; adding them would be a new feature (CLAUDE.md rule 6). They are listed under "Decisions for you".
- A forecast-table claim (`origin` forecast_file) keeps its note and has no calculation: it is never matched or tested (chat-upload.md section 20).
- Contract 10 is a bump for the new optional fields of `YearlyYear`, as contracts 3 and 4 were for theirs: stored results are recalculated by Run audit, never on a read.

## Files
`backend/app/forecast_calc.py`, `backend/app/payback_definition.py`, `backend/app/claim_matching.py`, `backend/app/verdict.py`, `backend/app/ic_memo.py`, `backend/app/claim_groups.py` (repeat note),
`backend/growth_engine.py`, `backend/app/structures/sheet.py` (`sm_scope`), `backend/schemas/metrics.py`, `backend/server.py` (`SEED_VERSION`), `frontend/src/lib/claim_columns.json`,
`claimRegister.js`, `ClaimRegister.jsx`, `FiveClaims.jsx`, `ClaimFourColumns.jsx`, `Verdict.jsx`, `YearlyBasis.jsx`, the tests of section 8.

## Done when
Section 8 passes in the full backend and frontend suites, each new test has failed without its change and on a deliberate violation (docs/test-runs/forecast-and-payback_2026-10-26.md).
