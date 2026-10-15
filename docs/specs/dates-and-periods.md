# Spec: Dates and periods (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 3 and 7.1 (D5 amended, decisions of
15 Oct 2026, final). Location: docs/specs/dates-and-periods.md. Amends claim-matching.md §2 (table 2b), §4, §6,
verdict-and-memo.md §7.2 and interface-contracts.md §1 (two new engine output fields, contract version 3).
Implementation order: 2 of 6.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: one date (the as-of month) stood for four things, so a June 2026 setting was printed against June 2019 data.
  The simpler version: keep the as-of month as the engine's cut-off and add what each figure covers, read from the data;
  the analyst's date only dates the analyst's text.
- Deleted first: the Missing Data item "Revenue up to the as-of month" (the latest valid source period of §2 says the same,
  without printing the setting as a period); "Figures reflect company data through {as-of}" on the Dashboard and "as of
  {as-of}" in the page header and the ACV Bands title (each replaced by the evidence end of §2); the xlsx Headline row
  "As-of month" (replaced by "Evidence to" and "Latest valid source period").

## 1. Four fields, always shown separately, never merged
| # | Field | Set by | Where it is shown |
|---|---|---|---|
| 1 | Requested analysis date | the analyst; default today | set-up fields (chat-upload.md §2), the Dashboard's "Dates and periods" line, the memo date line |
| 2 | Latest valid source period | the engine, from the revenue file | the Dashboard's "Dates and periods" line, the memo summary, the xlsx Headline sheet |
| 3 | Period and gaps per metric | the engine | beside every computed metric on the Dashboard; in the memo next to each figure |
| 4 | Claim-period coverage | claim matching, on read | every register row; the memo's Appendix A |

The Dashboard's "Dates and periods" line, under the page title, reads: "Requested analysis date: 15 Oct 2026 · Latest valid
source period: June 2019 (Complete)". The two never share a cell or a sentence.

## 2. Requested analysis date and latest valid source period
- Requested analysis date: audit field `analysis_date`, an ISO date (2000–2100) or null; null means today, the day the
  page or the memo is built. Set-up label "Requested analysis date", help "The date of this analysis. It dates the memo and
  your own text; it never changes the period of a figure." Not a recompute trigger. Used only for the memo date line and the
  "as of" label of the analyst's own text (a line under the "Deal thesis" heading: "Analyst's text, as of {date}."; the
  analyst judgment of claim-review-conclusion.md). It is never printed next to a value.
- Latest valid source period: engine output block `source_period`:
  `{"month", "status", "complete_by", "evidence_to"}`.
  - `month`: the last month of the revenue file, as uploaded (before the as-of cut), that has a row with a valid invoice
    date and a non-zero amount. Null with no revenue file (the block is then null, its reason in `missing_data` as today).
  - `status`: "Complete" when the audit's as-of month (stored, or defaulted as today: last P&L month, else last MRR month) is
    later than `month`, or the analyst ticked "Last month is complete" (audit field `last_month_complete`, a recompute
    trigger, a checkbox under the as-of month on the set-up fields); else "Possibly partial". `complete_by`: "as_of",
    "analyst" or null.
  - A Possibly partial month is shown in every series and figure, and excluded from the NRR (series, overall, by segment)
    and from growth (§5): NRR is computed as if the matrix ended the month before. Shown, not used.
  - `evidence_to`: the last month any revenue figure reads, `min(as-of month, month)`. Screen and memo text: "Evidence to
    June 2019".
  - Text: "June 2019 (Complete)" / "June 2019 (Possibly partial)", month name and year, never a day.
- The as-of month keeps its meaning for the engine (the cut-off, and the forecast test of claim-matching.md table 2b). It
  is a setting, shown in the set-up fields only, never as the period of a figure.

## 3. Period and gaps per metric
Engine output `metric_periods`: one entry per computed block, `{"first": "YYYY-MM", "last": "YYYY-MM", "missing": [months]}`.
`missing` is a list of the months inside first..last, never a count.
| Blocks | Months read | Missing |
|---|---|---|
| `arr`, `mrr_series`, `revenue_series`, `customers_series`, `acv_path`, `segment_paths`, `cohort_retention`, `new_mrr_by_quarter` | revenue file months up to `evidence_to` | a month inside the range with no valid revenue row (valid invoice date, non-zero amount) |
| `nrr`, `gross_churn` | the months of their series (NRR without a Possibly partial month) | revenue-file missing months inside the range |
| `revenue_reconciliation`, `cac_payback` | P&L months up to the as-of month | a month inside the range absent from the P&L |
| `sales_cycle`, `win_rate`, `founder_win_rate` | close months of the deals the block used | none: a month without a closed deal is not a data gap |

- Screen: every metric card, chart and table title of the Dashboard carries "{first} – {last}" in month-name form ("Jan 2023 –
  Feb 2024"); when `missing` is not empty, "Months missing: Mar 2023, Jun 2023" under it.
- Memo: every figure in sections 1–6 that is not a register figure (which carries `observed_at`) carries its last month in
  brackets, "ARR 202,125 EUR (2024-02)". The requested analysis date is never printed next to a figure.
- A register row whose figure has missing months inside the claim's period shows the list next to the value (§4).

## 4. Claim-period coverage
New register fields: `period_coverage` ("Covered", "Partly covered", "Not covered"; null when no figure is read: no metric,
a direction, a forecast, an analyst answer pending) and `months_missing` (list).

Coverage is measured on the months the observed figure reads:
| Metric kind (claim-matching.md table 2a) | Months read |
|---|---|
| sum (Revenue) | every month of the claim's period |
| month (ARR, MRR, Customer count, NRR, gross churn) | the period's end month; no period: `evidence_to` (until claim-types-and-correction.md makes the period required) |
| quarter (New MRR, gross margin, CAC payback) | the quarter's three months, in the file the metric reads |
| as-of (ACV, sales cycle, win rate, NRR by segment) | the as-of figure; covered when it exists (unchanged) |
| growth (§5) | the months the basis compares |

A month is in the data when it lies inside its block's first..last and is not in its `missing` (a Possibly partial month is
not in the data for NRR and growth).
| Coverage | Rule | Label and reason |
|---|---|---|
| Covered | every month read is in the data | the normal rules (claim-matching.md §4, §4.1): only a Covered claim can be Verified or Contradicted |
| Partly covered | some months read are in the data, some are not | Inconclusive (evidence-labels.md §3), reason `claim period partly covered (months missing: {list})`; the figure over the months present is shown, `observed_at` "2023-01 to 2023-03 (3 of 12 months)" |
| Not covered | no month read is in the data | Unverified, reason `claim period not in supplied data: {detail}` |

Details of Not covered: `before {metric}'s first month, {first}`; `after the latest valid source period, {evidence_to}`;
`after {metric}'s last month, {last}` (a P&L metric); `months missing: {list}`; `{month} is possibly partial (tick 'Last
month is complete' to use it)`. A forecast (period ends after the as-of month) stays a forecast (claim-matching.md table 2b),
so a claim for a month between `evidence_to` and the as-of month is Not covered, never a forecast.

Replaced reasons: "before {metric}'s first month, {month}" and "months missing from the data: {months}" (claim-matching.md
table 2b, Q2) now read through this table.

## 5. Growth claims
- Basis: every growth claim (types `revenue_growth`, `growth`, `user_growth`) carries `growth_basis`: `mom`, `yoy`, `annualised`,
  `cumulative` or `unknown`. The parser sets it from cue words in the claim's line and borrowed label (whole words, any case
  unless shown in capitals):
  | Basis | Cues |
  |---|---|
  | mom | MoM, m/m, month-on-month, month over month, monthly (not "monthly recurring revenue"), per month |
  | yoy | YoY, y/y, year-on-year, year over year, annual (not "annual recurring revenue"), per year |
  | annualised | CAGR, annualised, annualized |
  | cumulative | since; over, when a year, a fiscal year or a duration follows ("over 2023", "over the last 12 months", "over 3 years"), never before a number ("over 15%") |
  Cues of more than one basis, or none: `unknown`. The analyst may set it (claim-types-and-correction.md §3, and the
  one-click task below). Measured on the 10 public test decks on this branch (`python -I` over `detect_candidates`, no
  network): 225 candidates, 8 growth claims; 2 get `mom` (buffer slide 5 "growing 40% per month", clevergig page 2 "growing
  15% MoM"), 6 stay `unknown` (front slide 15, moz page 35 twice, clevergig page 7, uber pages 17 and 24).
- Unknown basis: the claim is Unverified, reason `growth basis unknown: set the growth basis`, and the register row offers
  the one-click task "Set growth basis" with four buttons (MoM · YoY · Annualised · Cumulative). The answer is stored on the
  claim's inputs (`growth_basis`), as the metric is; it clears a Definition check answer (claim-matching.md §4.1).
- Metrics (table 2a gains four rows, unit %, direction higher, tolerance ±1 pp, check limit 10 pp): "Revenue growth"
  (`revenue_series`), "ARR growth" (`mrr_series` × 12), "MRR growth" (`mrr_series`), "Customer growth" (`customers_series`).
  Proposed: type `revenue_growth` → MRR growth on "MRR", ARR growth on "ARR", else Revenue growth; type `growth` → the same
  keywords, Customer growth on a customers keyword (deck-parser.md §2), else none (Unsupported "no metric").
  Type `user_growth` is unchanged here (claim-types-and-correction.md §2 gives it a population).
- The figures, computed on read from the stored monthly series (as the revenue sum of table 2b is), all four for the
  claim's period [s, e] (months), and the one matching the basis is shown and tested:
  | Basis | Figure (v = the metric's monthly value) | Months read |
  |---|---|---|
  | mom | v(e) ÷ v(e−1) − 1 | e−1, e |
  | yoy | month metric: v(e) ÷ v(e−12) − 1; Revenue: Σv(s..e) ÷ Σv(s−12..e−12) − 1 | e and e−12; Revenue: both windows |
  | cumulative | v(e) ÷ v(s) − 1; needs e > s | s, e |
  | annualised | (v(e) ÷ v(s))^(12 ÷ (e − s)) − 1; needs e > s | s, e |
  Shown as a percent with the comparison in `observed_at` ("2024-02 vs 2023-02"). A base of 0 or below gives no figure:
  Unsupported, `growth base is not positive`. A period of one month with basis cumulative or annualised: Unverified,
  `growth window not stated`. Coverage by §4 on the months read; a Possibly partial month is not read. Source: the series'
  citation with the basis's rule ("YoY growth = v(e) ÷ v(e−12) − 1").

## 6. Override rule
Changing the requested analysis date recomputes nothing and changes no metric's period label, no register row and no
figure; it changes the memo date line and the "as of" label of the analyst's text only. No value is ever produced for a
period the data does not cover (§4).

## 7. Contract and data boundary
- `backend/schemas/metrics.py` gains `source_period` and `metric_periods` (text months, no figure), and
  `contract_version` becomes 3, so stored results are recomputed on first read (interface-contracts.md §7, no model, no
  cost). `test_interface_contracts.py` pins both blocks (rule 23).
- Both blocks are server-only (not in the gateway allowlist); `analysis_date`, `last_month_complete`, `period_coverage`,
  `months_missing`, `growth_basis` and the new reasons join the boundary lists of `test_gateway_data_boundary.py` (rule 14).

## 8. Regression test (required in Release 1, plan 3)
Artefact (CLAUDE.md rule 13): a synthetic revenue file, monthly invoices July 2017 to June 2019 for five customers (built
by the test, no client data); no P&L, no CRM; the audit's as-of month set by the analyst to 2026-06-30 (not defaulted); no
target date; requested analysis date not set; machine date frozen at 2026-10-15. Observed failure: June 2026 shown against
June 2019 data. Variant: as-of month not set (defaulted to June 2019) with "Last month is complete" ticked.
Expected: `source_period` = June 2019, Complete (`complete_by` "as_of"; variant "analyst"); every `metric_periods` entry and
`arr.month` end 2019-06; the memo carries "Evidence to June 2019" under its date line; in the memo the string "2026" appears
only on the date line (the requested analysis date, which is the memo date); on the Dashboard "2026" appears only in the
requested analysis date; no register row's `observed_at` holds 2026.

## 9. Tests
Every new test is first shown failing on a deliberate violation (rule 11); the plan tests are committed first as strict
expected failures.
| Test | File |
|---|---|
| Plan 3 regression (§8), both variants, engine, memo and Dashboard | `test_dates_and_periods.py`; `Dashboard.test.jsx` |
| Plan 7.1: "15% growth" with no cue is Unverified with "Set growth basis"; with a "YoY" cue it is matched on the year-on-year figure only | `test_dates_and_periods.py`; `ClaimRegister.test.jsx` |
| Possibly partial: the last month is excluded from NRR and growth and kept in ARR and the series; ticking the box makes it Complete | `test_dates_and_periods.py` |
| Coverage: Covered, Partly covered (Inconclusive with the figure over the months present), Not covered (each detail) | `test_dates_and_periods.py`, `test_claim_matching.py` (fixture rows 10, 19, 33, 35 updated) |
| Override: a new analysis date changes the memo date only | `test_dates_and_periods.py` |
| `metric_periods` lists missing months, not a count | `test_dates_and_periods.py` |
| Contract (rule 23) and boundary (rule 14) | `test_interface_contracts.py`, `test_gateway_data_boundary.py` |

## 10. Decided (engineering, rule 19)
- The coverage is measured on the months a figure reads, so a gap elsewhere in a claim's year does not touch a December ARR
  figure; the gap list is still shown next to it.
- Growth figures are computed on read from the stored series, like the revenue sum; no engine field per claim period.
- "per month" is a MoM cue, the counterpart of the plan's "per year" (it gives buffer slide 5 its basis); "over" counts only
  before a period, so "over 15% growth" ("more than") is not read as cumulative (measured: none of the 8 growth claims on the
  10 decks carries "over" or "since").
- Cumulative growth reads the window's first and last month (v(e) ÷ v(s) − 1); the formula is printed with each figure.

## 11. Consequences to know
- TestCo (as-of 2024-02 from the last P&L month, revenue to 2024-02): the latest valid source period is "February 2024
  (Possibly partial)" until the box is ticked, so NRR reads January 2024 and the NRR claims for February 2024 are Not
  covered. The claim-matching fixture ticks the box so its rows keep their meaning; the measured default is pinned in
  `test_dates_and_periods.py`.
- Gross revenue churn still reads a Possibly partial month (the plan names growth and NRR); see "Decisions for you".

## Files
`backend/growth_engine.py`, `backend/schemas/metrics.py`, `backend/app/claim_matching.py`, `backend/app/decks/claims.py`
(growth basis), `backend/app/ic_memo.py`, `backend/server.py`, `frontend/src/pages/Dashboard.jsx`,
`frontend/src/components/Layout.jsx`, `frontend/src/components/AuditSetup.jsx`, `frontend/src/components/ClaimRegister.jsx`,
`frontend/src/lib/claimRegister.js`, `frontend/src/lib/claim_metrics.json`, the tests of §9.

## Done when
§9 passes with the full suite, and the §8 artefact shows June 2019 everywhere a figure is labelled.
