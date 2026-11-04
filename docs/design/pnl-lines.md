# P&L lines: what each line feeds

Addendum to the adopted spec. Date: 28 Oct 2026. Applies to any file read as
financial_statements or pnl, yearly or monthly. The adopted spec is not amended.

## 1. Rule

Every mapped line of a P&L is used. No line is "not used" once mapped. A line
feeds the audit in one of four ways: a value series, a sum check, a recompute
check, or an exclusion. The table in section 5 names the use per line.

## 2. Periods

- A column labelled "FY 2021" or "2021" is the twelve months ending at the
  fiscal year-end month of that year (PR #196).
- A rate row (growth %) inherits the period of the columns it is computed
  from. A yearly file gives yearly growth. It is never read, shown or matched
  as monthly. Conversion between periods happens only in code, with the
  formula shown, and the result is labelled "annualised".
- A margin % row (gross margin %, opex %, EBITDA %) is a ratio, not a rate of
  change. It has no period of its own and may be compared at any period.
- Columns ending on or before the as-of month are actuals. Columns after it
  are plan, whatever their header says. A column marked budget, plan or
  forecast is plan even before the as-of month (PR #196).

## 3. Integrity checks

- Sum check: each total line is recomputed from its sub-lines. A gap beyond
  the app's money tolerance is an integrity finding: "OPEX total differs from
  the sum of its lines by X in FY 2021".
- Recompute check: each % row is recomputed from the money rows. A gap
  beyond the app's rate tolerance (±1 point) is an integrity finding. A gap
  within it is not shown.
- Sign check: costs written as negatives are read as costs. A sign that
  differs between a total and its sub-lines is an integrity finding.

## 4. Plan columns

- Each plan cell of a money line is a claim with source "File <sheet>!<cell>
  (plan)". It enters the register beside deck forecasts and is ranked by
  value at stake the same way.
- A plan claim is never Verified or Contradicted. It is tested as implied
  rate against observed rate: implied growth = plan FY 2022 ÷ actual FY 2021
  − 1, shown next to observed growth FY 2020 → FY 2021, with the gap in
  points. Same for gross margin, S&M growth, opex growth and EBITDA.
- Where the deck carries a forecast for the same metric and period, the two
  are compared. Within tolerance: one claim, two sources. Beyond it: "plan in
  file differs from plan in deck", listed under Worth flagging.
- When a later file or deck brings actuals for a plan period, the stored
  plan value is the forecast for the forecast track record (bias and accuracy
  score). The plan value must keep its period when stored.

## 5. Lines and uses

The rows below are examples from one real file. The engine assigns a use by
the line's mapped role (revenue, cost of revenue, S&M, R&D, G&A, other
income, D&A, tax, total, rate), never by its label text. A file with other
labels or other groupings gets the same uses through the same roles.

| Line (as mapped) | Use |
|---|---|
| OPEX total | burn base; opex ÷ revenue trend; sum check against the department totals |
| revenue growth rate | recompute check against the revenue row, same period |
| Revenue (Recognised) | yearly revenue series; growth; reconcile with revenue file, deck actuals; base of every growth claim |
| Revenue sub-lines (products) | segment series under the revenue total (segment-partitions.md); mix and growth by product |
| Cost of Goods Sold | gross margin input; sum check against its sub-line |
| Cloud processing and database | cost ÷ revenue per year; falling = scale economies, rising = none (defensibility) |
| Gross Margin | recompute check |
| Gross margin % | recompute check |
| OPEX % | recompute check |
| Research & Development | share of opex by function (strategic coherence) |
| HR costs (R&D) | R&D headcount proxy; hiring pace vs plan |
| Sales | S&M input for CAC payback; share of opex |
| HR costs (Sales) | sales headcount proxy |
| sales-related travel | part of S&M |
| Marketing | S&M input; channel split with the two lines below |
| HR costs (Marketing) | marketing headcount proxy |
| events (physical & virtual) | channel spend |
| content marketing, media and ads | channel spend |
| internal events | not S&M; counted in G&A for CAC payback |
| General & Administration | overhead ratio; share of opex |
| HR costs (G&A) | G&A headcount proxy; sum of the four HR lines = total HR cost, checked against a headcount file when supplied |
| office and facilities | fixed cost base |
| IT equipment | fixed cost base |
| audit, tax, legal services | fixed cost base; note whether accounts are audited |
| patents, IPR, certifications | IP spend trend (defensibility) |
| EBITDA | operating burn per year; runway with a cash balance when supplied |
| EBITDA % | recompute check |
| Interest income / costs | excluded from operating burn |
| Other income: venture capital | funding received per year; excluded from revenue and EBITDA |
| Other income: grants | grant dependency = grants ÷ (revenue + grants); excluded from revenue; a plan that assumes grants continue is a claim |
| Depreciation & amortization | if large relative to R&D, R&D is partly capitalised; noted |
| EBT | recompute check |
| Tax paid | cash tax |
| RnD Tax credits | recurring cash inflow; in runway; dependency noted |
| Net income | recompute check |

Lines not in this table are mapped by the same rules: a money line is a
series and takes part in the sum check of its parent; a % line is a
recompute check; an income line outside operations is an exclusion.

## 6. CAC payback on yearly data

S&M = Sales + Marketing totals, minus internal events. Gross margin from the
file. New revenue = revenue in year N minus revenue in year N−1 (no
customer-level data). Result labelled "yearly, revenue-based", never "months".
Where a monthly revenue file exists, the monthly payback stands and the
yearly one is shown as a check. The yearly basis exists only when there is no
monthly P&L.

## 7. Matching deck figures to yearly columns

Every match of a deck figure against a yearly column goes through
`yearly_year` in claim_matching.py (PR #196). A deck year matches only a
column ending in the same month; otherwise the claim reads "period not
covered".

## 8. Screen

- One Type line per file. When rules and AI agree: "Type: Financial
  statements". When they differ: "Type: Financial statements · AI suggests
  P&L (yearly summary) · Change".
- The "Used" column shows the use from section 5 in two or three words
  ("series", "sum check", "recompute check", "excluded"), never "Not used".

## 9. Tests

The real yearly P&L fixture (anonymised, FY 2019–FY 2024, as-of Dec 2021):
every line mapped shows a use; the sum check reports the OPEX sign gap; the
growth rate row reads yearly; the revenue growth recompute is within
tolerance; FY 2022–FY 2024 revenue cells are plan claims with implied growth
next to observed; the deck's FY 2022 revenue forecast is compared with the
file's FY 2022 plan.

## 10. Built 2026-10-28 (sections 1-8)

Code: `backend/app/structures/pnl_lines.py` (uses, periods, checks, plan cells), `sheet.view` (`use`, `period` per line), `sheet.feed` (`lines`),
`growth_engine.compute_pnl_lines` and `yearly_basis.years.cac_payback_label`, `claim_matching.plan_candidates` / `_compare_plan` / `yearly_year(plan=True)`,
`integrity.statement_findings`, `UploadChat.jsx` (one Type line), `SheetMap.jsx` (Used column). Engine contract 13. Decided in the build (rule 19):
- A use comes from the mapped role (role, meaning, parent, basis, the numbers), never from the label. The model's reply schema is unchanged: R&D, G&A,
  other income, D&A and tax are not meanings of their own; a line mapped to no meaning and no parent is excluded, a total of parts is a sum check
  unless the engine reads it as a value.
- Money tolerance is the sum check's own 0.5% (`sheet.TOLERANCE`); the rate tolerance is the register's ±1 point (`claim_matching.RATE_TOLERANCE_PP`).
- Result lines below EBITDA (EBT, net income) are found by the numbers (equal to the line above plus the lines between, in half of the periods) and are
  recomputed as written; plan cells are read from yearly columns only.
- Internal events are S&M-excluded when the sub-line is mapped to overhead (opex) under an S&M total; the label rule that maps "internal events" to
  overhead sits at the mapping step (`sheet.meaning_of`).
- The deck forecast is compared with the plan line for revenue, gross profit and EBITDA claims; a cost forecast names no one plan line.
- The yearly revenue-based payback reads "CAC payback FY 2021: 12.5 months (yearly, revenue-based)": unit kept, label kept (George, 2026-10-29).

## The comparison lines (memo block "What the plan assumes")

George, 2026-11-03. The memo carries a block "What the plan assumes" directly after the Scorecard: the yearly P&L trend table and the lines below. Code: `app/plan_lines.py`
(templates, tolerances), `role_engine.pnl_trend` (values and cells), `role_metrics.pnl_trend` (stored, contract version 18). No model writes a line.

**Trend table.** One row per metric: revenue, gross margin, S&M share, R&D share, G&A share, EBITDA margin. Actual years first (fiscal years that end at or before the as-of
month), then plan years (the other years the plan holds), the plan years marked "(plan)". A value with an input missing is "—". R&D and G&A of an actual year that carries OPEX
only are the estimate of the Estimates block (plan split applied to actual OPEX, non-S&M OPEX × r) and carry the label "Estimate – plan split applied to actual OPEX"; when its
check (a) or (b) fails there is no estimate and the cell is "—". **Three-way split (contract 18).** When the latest actual year has an OPEX total and no S&M, R&D or G&A value, and the plan years carry rows of all three and OPEX, actual OPEX is split three ways: share of X = the sum of X over the plan years ÷ the sum of S&M + R&D + G&A over the plan years. Checks: (a) S&M + R&D + G&A = plan OPEX within 1% in every plan year; (b) each share moves no more than 10 points across the plan years; a failed check gives no estimate and the line "No estimate: check (a) failed …" or "check (b) failed …" naming the check. S&M, R&D and G&A expense (metric `sm_expense` is new) and their shares of revenue in that year are estimates: flagged, labelled "Estimate – plan split applied to actual OPEX", citing the actual OPEX cell and every plan cell used, read by no rating and by no CAC payback (yearly), which stays Missing with its data request. The data request for the actual split stays. The two-way split above stays, and takes priority, when the year has actual S&M. `sm_expense` exists only when the three-way estimate is computed; only the latest actual year is estimated. Each value is stored with the cells it was computed from (Appendix C, "Yearly P&L trend"). A plan row may be a
plan cell of the line's own row or a `forecast` row that names its line by its metric.

**Stable.** Shares and margins: within ±2 points. Money: within ±5% of the first figure (the claim-matching amount tolerance, `AMOUNT_TOLERANCE`). The boundary is stable.

**Lines.** `{metric}` is the table's name, lower-cased in mid-sentence ("gross margin"; "S&M share of revenue" and "EBITDA margin" keep their capitals). `{label}` is ", estimate"
when the actual value is an estimate, else empty. A figure goes through the one formatter.

| Kind | Template | When |
|---|---|---|
| Plan against the past | Plan assumes {metric} rises from {a} ({year_a}{label}) to {p} ({year_p}). | latest actual year against the last plan year; p above a, outside the tolerance |
| | Plan assumes {metric} falls from {a} ({year_a}{label}) to {p} ({year_p}). | p below a, outside the tolerance |
| | Plan holds {metric} at about {a} ({year_a}{label}) through {year_p}. | within the tolerance |
| Trend (actual years) | {metric} rose from {first} ({year}) to {last} ({year}). | two or more actual years; last above first, outside the tolerance |
| | {metric} fell from {first} ({year}) to {last} ({year}). | last below first, outside the tolerance |
| | {metric} moved between {min} and {max} over {year}–{year}. | last within the tolerance of first; min and max over the actual years |
| Plan to date | Revenue is {gap} ({gap_pct}) behind plan to {month}. / … ahead of plan to {month}. | plan-to-date gap outside ±5%; also listed under Worth flagging |
| | Revenue is on plan to {month}. | within ±5% |
| Reconciliation | {metric} {year} differs across sources by {diff} ({pct}): {list}. | status Differs; Agrees gives no line |

**No line** when an input is missing (no row, no year, no percentage because the plan is zero), when the estimate's checks failed, or for the trend of an estimated row (an
estimate is the plan's split applied to one year's OPEX, not a trend). Each line is footnoted with the cells it was built from.

