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
yearly one is shown as a check.

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
